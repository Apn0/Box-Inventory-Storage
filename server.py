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
import dataclasses
import datetime
import http.server
import json
import mimetypes
import pathlib
import queue
import urllib.parse
import re
import shutil
import socket
import socketserver
import struct
import sys
import threading
import zlib

ROOT = pathlib.Path(__file__).resolve().parent
INDEX = ROOT / "index.html"
INBOX = ROOT / "data" / "inbox"
REVIEW = ROOT / "data" / "review"
PHOTOS = ROOT / "data" / "photos"

SHEET_ID = "1ZVVkmA7tI_kqIUi5O-6cw5Az_qfGmKhydgy2QrFWFDQ"
BOX_GID = "788564724"
FORM_GID = "677102738"

ALLOWED_SUFFIX = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}
MAX_UPLOAD = 25 * 1024 * 1024          # a phone photo is ~2-8 MB
ACCENT = (29, 92, 255)

_build_lock = threading.Lock()

# One worker, one queue. Two photos identified at the same time would both read
# the inventory, both append, and the second would overwrite the first's count.
_work: "queue.Queue[pathlib.Path]" = queue.Queue()
_activity: list[dict] = []          # newest last; what the app shows as results
_activity_lock = threading.Lock()
AUTO = True                         # set False with --no-auto to just queue


def record(entry: dict) -> None:
    entry["at"] = datetime.datetime.now().isoformat(timespec="seconds")
    with _activity_lock:
        _activity.append(entry)
        del _activity[:-40]


def worker() -> None:
    """Identify each photo as it arrives, one at a time."""
    import identify                                    # imported here so the
                                                        # server starts even if
                                                        # identify.py is broken
    while True:
        path = _work.get()
        try:
            if not path.exists():                       # already handled
                continue
            record({"photo": path.name, "state": "working"})
            print(f"  identifying {path.name}…")
            # unattended: file only confident matches to parts already on record.
            # Anything else waits in the queue for a human look.
            for out in identify.process([path], unattended=True):
                if not out.get("ok"):
                    out["state"] = "failed"
                    print(f"   failed: {out.get('error')}")
                else:
                    out["state"] = "confirm"
                    out["id"] = out["photo"]
                    pending = identify.load_pending()
                    pending = [p for p in pending if p["id"] != out["id"]]
                    pending.append(out)
                    identify.save_pending(pending)
                    print(f"   asks: {out['name']} -> box {out['box']} "
                          f"(recorded {out.get('recorded')})")
                record(out)
        except Exception as exc:                        # noqa: BLE001
            record({"photo": path.name, "state": "failed", "ok": False,
                    "error": str(exc)[:200]})
            print(f"   worker error: {exc}")
        finally:
            _work.task_done()


# ----------------------------------------------------------------- tiny PNG
def png(size: int) -> bytes:
    """A solid accent square with a lighter box outline — enough for a launcher icon."""
    r, g, b = ACCENT
    pad, thick = size // 5, max(2, size // 24)
    rows = []

    edge_pixel = b'\xff\xff\xff'
    bg_pixel = bytes((r, g, b))

    bg_row_data = [bg_pixel for _ in range(size)]
    bg_row_bytes = b'\x00' + b''.join(bg_row_data)

    thick_row_data = [
        edge_pixel if (pad <= x < size - pad) else bg_pixel
        for x in range(size)
    ]
    thick_row_bytes = b'\x00' + b''.join(thick_row_data)

    inner_row_data = [
        edge_pixel if (pad <= x < size - pad and (x - pad < thick or size - pad - x <= thick))
        else bg_pixel
        for x in range(size)
    ]
    inner_row_bytes = b'\x00' + b''.join(inner_row_data)

    for y in range(size):
        if y < pad or y >= size - pad:
            rows.append(bg_row_bytes)
        elif y - pad < thick or size - pad - y <= thick:
            rows.append(thick_row_bytes)
        else:
            rows.append(inner_row_bytes)

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


def _photos_in(folder: pathlib.Path) -> list[dict]:
    if not folder.exists():
        return []
    return sorted(
        ({"name": p.name, "size": p.stat().st_size,
          "at": datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")}
         for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIX),
        key=lambda d: d["at"], reverse=True)


def inbox_list() -> list[dict]:
    return _photos_in(INBOX)


def review_list() -> list[dict]:
    """Identified, but held back because it was not safe to file unattended."""
    return _photos_in(REVIEW)


@dataclasses.dataclass
class Response:
    code: int
    body: bytes
    ctype: str
    extra: dict | None = None
    cache: str = "no-store"


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "BoxInventory/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    # -------------------------------------------------------------- helpers
    def _send(self, response: Response) -> None:
        self.send_response(response.code)
        self.send_header("Content-Type", response.ctype)
        self.send_header("Content-Length", str(len(response.body)))
        self.send_header("Cache-Control", response.cache)
        for k, v in (response.extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(response.body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(Response(code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8"))

    # ------------------------------------------------------------------ GET
    def _handle_get_index(self) -> None:
        if not INDEX.exists():
            return self._json(500, {"error": "index.html missing — run build.py"})
        # Let the phone keep a copy: when this machine is off, the app falls
        # back to it and you can still read the inventory in a shop. Short
        # max-age so a running server always wins.
        return self._send(Response(200, INDEX.read_bytes(), "text/html; charset=utf-8",
                          cache="max-age=30, stale-if-error=604800"))

    def _handle_get_manifest(self) -> None:
        return self._send(Response(200, json.dumps(MANIFEST).encode("utf-8"), "application/manifest+json"))

    def _handle_get_icon(self, path: str) -> None:
        return self._send(Response(200, png(192 if "192" in path else 512), "image/png"))

    def _handle_get_inbox(self) -> None:
        with _activity_lock:
            recent = list(_activity)
        import identify
        changes = identify.load_changes()
        return self._json(200, {"pending": inbox_list(), "auto": AUTO,
                                "working": _work.unfinished_tasks,
                                "review": len(review_list()),
                                "confirm": identify.load_pending(),
                                "changes": changes[-12:][::-1],
                                "activity": recent})

    def _handle_get_proxy(self) -> None:
        import urllib.request
        qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
        gid = (qs.get("gid") or [""])[0]
        if not gid.isdigit():
            return self._json(400, {"error": "gid must be a number"})
        url = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
               f"/export?format=csv&gid={gid}")
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                body = r.read()
        except Exception as exc:                   # noqa: BLE001
            return self._json(502, {"error": str(exc)[:200]})
        return self._send(Response(200, body, "text/csv; charset=utf-8"))

    def _handle_get_inventory(self) -> None:
        target = ROOT / "data" / "inventory.json"
        if target.is_file():
            return self._send(Response(200, target.read_bytes(), "application/json; charset=utf-8"))
        return self._json(404, {"error": "not built yet"})

    def _handle_get_media(self, path: str, folder: pathlib.Path) -> None:
        name = pathlib.PurePosixPath(urllib.parse.unquote(path)).name
        target = folder / name
        if target.is_file() and folder.resolve() in target.resolve().parents:
            ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
            return self._send(Response(200, target.read_bytes(), ctype))
        return self._json(404, {"error": "not found"})

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            return self._handle_get_index()

        if path == "/manifest.webmanifest":
            return self._handle_get_manifest()

        if path in ("/icon-192.png", "/icon-512.png"):
            return self._handle_get_icon(path)

        if path == "/inbox":
            return self._handle_get_inbox()

        # CSV of one sheet tab, fetched server-side. docs.google.com sends no
        # CORS headers, so a served page cannot read it directly — this makes
        # the read same-origin. Locked to our sheet: gid is the only input.
        if path == "/proxy":
            import urllib.request
            qs = urllib.parse.parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")
            gid = (qs.get("gid") or [""])[0]
            if gid not in {BOX_GID, FORM_GID}:
                return self._json(403, {"error": "forbidden gid"})
            url = (f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
                   f"/export?format=csv&gid={gid}")
            try:
                with urllib.request.urlopen(url, timeout=20) as r:
                    body = r.read()
            except Exception as exc:                   # noqa: BLE001
                return self._json(502, {"error": str(exc)[:200]})
            return self._send(Response(200, body, "text/csv; charset=utf-8"))

        # the freshly built inventory, so the page can update without a reload
        if path == "/data/inventory.json":
            return self._handle_get_inventory()

        # photos, so the confirmation card can show what it is asking about
        for prefix, folder in (("/data/photos/", PHOTOS), ("/data/review/", REVIEW)):
            if path.startswith(prefix):
                return self._handle_get_media(path, folder)

        return self._json(404, {"error": "not found"})

    def _handle_upload(self) -> None:
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
        if AUTO:
            _work.put(INBOX / name)
        return self._json(200, {"ok": True, "saved": name,
                                "queued": AUTO, "pending": len(inbox_list())})

    def _handle_quickadd(self) -> None:
        import identify
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_UPLOAD:
                return self._json(413, {"error": f"too large ({length} bytes)"})
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "bad body"})

        name = (body.get("name") or "").strip()
        if not name:
            return self._json(400, {"error": "name is required"})
        try:
            box = int(body.get("box"))
        except (TypeError, ValueError):
            return self._json(400, {"error": "box must be a number"})

        with _build_lock:
            try:
                done = identify.commit({"photo": None, "name": name, "box": box,
                                        "note": body.get("note", "")},
                                       body.get("qty"), box, name)
            except Exception as exc:               # noqa: BLE001
                return self._json(500, {"error": str(exc)[:200]})
        record({"photo": None, "state": "done", "ok": True,
                "name": done["name"], "box": done["box"], "to": done["quantity"]})
        print(f"  typed: {done['name']} -> box {done['box']} = {done['quantity']}")
        return self._json(200, {"ok": True, **done})

    def _handle_confirm_dismiss(self, path: str) -> None:
        import identify
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_UPLOAD:
                return self._json(413, {"error": f"too large ({length} bytes)"})
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "bad body"})

        entries = identify.load_pending()
        entry = next((e for e in entries if e["id"] == body.get("id")), None)
        if entry is None:
            return self._json(404, {"error": "no such pending photo"})

        entries = [e for e in entries if e["id"] != entry["id"]]
        if path == "/dismiss":
            photo_filename = pathlib.Path(entry["photo"]).name
            src = REVIEW / photo_filename
            if src.exists():                       # keep the photo, file nothing
                (ROOT / "data" / "ignored").mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(ROOT / "data" / "ignored" / photo_filename))
            identify.save_pending(entries)
            record({"photo": entry["photo"], "state": "dismissed", "ok": True,
                    "name": entry.get("name")})
            return self._json(200, {"ok": True, "dismissed": entry["id"]})

        with _build_lock:
            try:
                done = identify.commit(entry, body.get("qty"),
                                       body.get("box"), body.get("name"))
            except Exception as exc:               # noqa: BLE001
                return self._json(500, {"error": str(exc)[:200]})
            identify.save_pending(entries)
        record({"photo": entry["photo"], "state": "done", "ok": True,
                "name": done["name"], "box": done["box"], "to": done["quantity"]})
        print(f"  confirmed: {done['name']} -> box {done['box']} = {done['quantity']}")
        return self._json(200, {"ok": True, **done})

    def _handle_undo(self) -> None:
        import identify
        with _build_lock:
            try:
                undone = identify.undo_last()
            except Exception as exc:               # noqa: BLE001
                return self._json(409, {"error": str(exc)[:200]})
        if not undone:
            return self._json(200, {"ok": False, "message": "nothing to undo"})
        names = ", ".join(r["name"] for r in undone["rows"])
        record({"state": "undone", "ok": True, "name": names})
        print(f"  undone: {names}")
        return self._json(200, {"ok": True, "undone": undone["rows"]})

    def _handle_identify(self) -> None:
        pending = inbox_list()
        if not pending:
            return self._json(200, {"ok": True, "message": "inbox empty"})
        for entry in pending:
            _work.put(INBOX / entry["name"])
        return self._json(202, {"ok": True, "started": len(pending)})

    # ----------------------------------------------------------------- POST
    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]

        if path == "/upload":
            return self._handle_upload()

        # Typed or spoken entry: no photo, no vision call, nothing to identify.
        # For a part you can name, this is the whole pipeline.
        if path == "/quickadd":
            return self._handle_quickadd()

        if path in ("/confirm", "/dismiss"):
            return self._handle_confirm_dismiss(path)

        if path == "/undo":
            return self._handle_undo()

        if path == "/identify":
            return self._handle_identify()

        return self._json(404, {"error": "not found"})


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
    except OSError as exc:
        print(f"Warning: could not resolve local hostname: {exc}", file=sys.stderr)
    # a private-range address on the same /24 as a typical home router first
    found.sort(key=lambda ip: (not ip.startswith("192.168."), ip))
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8781)
    ap.add_argument("--host", default="127.0.0.1", help="bind address (default: 127.0.0.1)")
    ap.add_argument("--no-auto", action="store_true",
                    help="just queue photos; do not identify them on arrival")
    args = ap.parse_args()

    global AUTO
    AUTO = not args.no_auto

    if not INDEX.exists():
        sys.exit("index.html missing — run build.py first")
    INBOX.mkdir(parents=True, exist_ok=True)

    threading.Thread(target=worker, daemon=True).start()
    if AUTO:
        for entry in inbox_list():        # anything left over from last time
            _work.put(INBOX / entry["name"])

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
    if args.host.startswith("127."):
        print(f"  here:   http://127.0.0.1:{args.port}")
        print("\n  (Listening on localhost only. To allow phone connections, run with: --host 0.0.0.0)")
    else:
        for ip in lan_ips():
            print(f"  phone:  http://{ip}:{args.port}")
        print(f"  here:   http://localhost:{args.port}")
    print(f"\n  inbox:  {INBOX}  ({len(inbox_list())} waiting)")
    print(f"  auto:   {'on — photos are identified as they arrive' if AUTO else 'off (--no-auto)'}")
    if not args.host.startswith("127."):
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
