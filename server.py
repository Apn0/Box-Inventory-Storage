#!/usr/bin/env python3
"""
Serve the Box Inventory app to the phone, and take photos back from it.

    python server.py

Then on the phone (same WiFi):  http://<pc-ip>:8777
Chrome menu -> "Add to Home screen" gives it an icon and opens it fullscreen.

The camera button in the app posts straight here. Photos land in data/inbox/ and
stay queued until they are identified, so snapping works even when the vision
API has no credit. Nothing is deleted — identified photos move to data/photos/.

Standard library only: no pip install, no build step.
"""
from __future__ import annotations

import argparse
import datetime
import http.server
import json
import mimetypes
import pathlib
import re
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import zlib

ROOT = pathlib.Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
INBOX = ROOT / "data" / "inbox"
PHOTOS = ROOT / "data" / "photos"

ALLOWED_SUFFIX = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}
MAX_UPLOAD = 25 * 1024 * 1024          # a phone photo is ~2-8 MB
ACCENT = (29, 92, 255)

_build_lock = threading.Lock()


# ----------------------------------------------------------------- tiny PNG
def png(size: int) -> bytes:
    """A solid accent square with a lighter box outline — enough for a launcher icon."""
    r, g, b = ACCENT
    pad, thick = size // 5, max(2, size // 24)
    rows = []
    for y in range(size):
        row = bytearray([0])                      # filter byte: none
        for x in range(size):
            edge = (pad <= x < size - pad and pad <= y < size - pad and
                    (x - pad < thick or size - pad - x <= thick or
                     y - pad < thick or size - pad - y <= thick))
            row += bytes((255, 255, 255) if edge else (r, g, b))
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + chunk(b"IEND", b""))


MANIFEST = {
    "name": "Box Inventory",
    "short_name": "Boxes",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#0e1117",
    "theme_color": "#1d5cff",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
    ],
}


def safe_name(raw: str) -> str:
    """Phone filenames are untrusted input — keep only a basename we chose the shape of."""
    stem = pathlib.PurePosixPath(raw.replace("\\", "/")).name
    suffix = pathlib.PurePosixPath(stem).suffix.lower()
    if suffix not in ALLOWED_SUFFIX:
        suffix = ".jpg"
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", pathlib.PurePosixPath(stem).stem)[:60] or "photo"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    return f"{stamp}_{clean}{suffix}"


def inbox_list() -> list[dict]:
    if not INBOX.exists():
        return []
    return sorted(
        ({"name": p.name, "size": p.stat().st_size,
          "at": datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}
         for p in INBOX.iterdir() if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIX),
        key=lambda d: d["at"], reverse=True)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "BoxInventory/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    # -------------------------------------------------------------- helpers
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8")

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            if not INDEX.exists():
                return self._json(500, {"error": "index.html missing — run build.py"})
            return self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")

        if path == "/manifest.webmanifest":
            return self._send(200, json.dumps(MANIFEST).encode("utf-8"), "application/manifest+json")

        if path in ("/icon-192.png", "/icon-512.png"):
            return self._send(200, png(192 if "192" in path else 512), "image/png")

        if path == "/inbox":
            return self._json(200, {"pending": inbox_list()})

        # photos already filed, referenced by the app
        if path.startswith("/data/photos/"):
            name = pathlib.PurePosixPath(path).name
            target = PHOTOS / name
            if target.is_file() and target.parent.resolve() == PHOTOS.resolve():
                ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
                return self._send(200, target.read_bytes(), ctype)
            return self._json(404, {"error": "not found"})

        return self._json(404, {"error": "not found"})

    # ----------------------------------------------------------------- POST
    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]

        if path == "/upload":
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self._json(400, {"error": "bad length"})
            if length <= 0:
                return self._json(400, {"error": "empty upload"})
            if length > MAX_UPLOAD:
                return self._json(413, {"error": f"too large ({length} bytes)"})

            data = self.rfile.read(length)
            INBOX.mkdir(parents=True, exist_ok=True)
            name = safe_name(self.headers.get("X-Filename", "photo.jpg"))
            (INBOX / name).write_bytes(data)
            print(f"  photo received: {name} ({len(data)//1024} KB)")
            return self._json(200, {"ok": True, "saved": name, "pending": len(inbox_list())})

        if path == "/identify":
            if _build_lock.locked():
                return self._json(409, {"error": "already running"})
            pending = inbox_list()
            if not pending:
                return self._json(200, {"ok": True, "message": "inbox empty"})
            threading.Thread(target=self._run_identify, daemon=True).start()
            return self._json(202, {"ok": True, "started": len(pending)})

        return self._json(404, {"error": "not found"})

    def _run_identify(self) -> None:
        with _build_lock:
            print("  running identify.py on the inbox…")
            proc = subprocess.run(
                [sys.executable, str(ROOT / "identify.py"), str(INBOX / "*"), "--yes"],
                capture_output=True, text=True)
            print((proc.stdout or "") + (proc.stderr or ""))


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    # NOT allow_reuse_address: on Windows SO_REUSEADDR lets a second process bind
    # a port that is already listening, and requests then go to whichever socket
    # the OS picks — a silent, very confusing failure. Fail loudly instead.
    allow_reuse_address = False


def port_in_use(port: int) -> str | None:
    """Return the address already answering on `port`, over either IP family."""
    for family, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as s:
                s.settimeout(0.4)
                if s.connect_ex((addr, port)) == 0:
                    return addr
        except OSError:
            continue
    return None


def lan_ips() -> list[str]:
    """Best-effort list of addresses the phone might actually be able to reach."""
    found = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith(("127.", "169.254.")) and ip not in found:
                found.append(ip)
    except OSError:
        pass
    # a private-range address on the same /24 as a typical home router first
    found.sort(key=lambda ip: (not ip.startswith("192.168."), ip))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8781)
    ap.add_argument("--host", default="0.0.0.0", help="bind address (default: all interfaces)")
    args = ap.parse_args()

    if not INDEX.exists():
        sys.exit("index.html missing — run build.py first")
    INBOX.mkdir(parents=True, exist_ok=True)

    # Binding alone is not a reliable conflict check on Windows: a server on the
    # IPv6 wildcard and one on the IPv4 wildcard both bind the same port happily,
    # and "localhost" then reaches whichever the resolver picks. Probe instead.
    if (holder := port_in_use(args.port)):
        sys.exit(f"port {args.port} already answers on {holder} — something else is "
                 f"serving it.\nStart with --port {args.port + 1} instead.")

    try:
        srv = Server((args.host, args.port), Handler)
    except OSError as exc:
        sys.exit(f"cannot listen on port {args.port}: {exc}")
    print(f"Box Inventory server on port {args.port}\n")
    for ip in lan_ips():
        print(f"  phone:  http://{ip}:{args.port}")
    print(f"  here:   http://localhost:{args.port}")
    print(f"\n  inbox:  {INBOX}  ({len(inbox_list())} waiting)")
    print("\n  If the phone cannot connect: check the Windows firewall prompt, and")
    print("  note that an active VPN can stop the phone reaching this machine.")
    print("\n  Ctrl-C to stop.\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
