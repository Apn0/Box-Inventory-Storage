#!/usr/bin/env python3
"""
Pull a fresh copy of the Box Inventory Storage Google Sheet, then rebuild.

Run:  python sync.py

Keeps a timestamped .bak of the previous CSV so a bad download can be undone.
"""

import datetime
import pathlib
import shutil
import subprocess
import sys
import json
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
RAW = ROOT / "data" / "inventory_raw.csv"
FORM_CSV = ROOT / "data" / "form_responses.csv"

config_file = ROOT / "config.json"
if config_file.exists():
    try:
        _cfg = json.loads(config_file.read_text(encoding="utf-8"))
        SHEET_ID = _cfg.get("sheet_id", "1ZVVkmA7tI_kqIUi5O-6cw5Az_qfGmKhydgy2QrFWFDQ")
        BOX_GID = _cfg.get("box_gid", 788564724)
        FORM_GID = _cfg.get("form_gid", 677102738)
    except Exception:
        SHEET_ID = "1ZVVkmA7tI_kqIUi5O-6cw5Az_qfGmKhydgy2QrFWFDQ"
        BOX_GID = 788564724
        FORM_GID = 677102738
else:
    SHEET_ID = "1ZVVkmA7tI_kqIUi5O-6cw5Az_qfGmKhydgy2QrFWFDQ"
    BOX_GID = 788564724
    FORM_GID = 677102738

URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={BOX_GID}"
FORM_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={FORM_GID}"


def main() -> int:
    print(f"downloading {URL}")
    try:
        with urllib.request.urlopen(URL, timeout=60) as r:
            body = r.read()
    except urllib.error.URLError as exc:
        print(f"download failed: {exc}", file=sys.stderr)
        print("(is the sheet still shared as 'anyone with the link'?)", file=sys.stderr)
        return 1

    text = body.decode("utf-8-sig", errors="replace")
    if "Box" not in text.split("\n", 1)[0]:
        print("that does not look like the inventory sheet — first line was:", file=sys.stderr)
        print("  " + text.split("\n", 1)[0][:200], file=sys.stderr)
        return 1

    rows = text.count("\n")
    if RAW.exists():
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = RAW.with_suffix(f".csv.{stamp}.bak")
        shutil.copy2(RAW, bak)
        print(f"previous CSV kept at {bak.name}")

        # Check for unmerged offline rows
        local_lines = set(RAW.read_text("utf-8-sig", errors="replace").splitlines())
        cloud_lines = set(text.splitlines())
        offline_unique = [l for l in local_lines if l and l not in cloud_lines and not l.startswith("Box,")]
        if offline_unique:
            offline_file = RAW.parent / "offline_unmerged.csv"
            with offline_file.open("a", encoding="utf-8") as fh:
                for line in offline_unique:
                    fh.write(line + "\n")
            print(f"WARNING: preserved {len(offline_unique)} unmerged offline rows in {offline_file}")

    RAW.write_bytes(body)
    print(f"wrote {RAW}  ({rows} lines)")

    # The form tab holds every row the app wrote. Replacing the local mirror
    # with the cloud copy is safe: the cloud is the superset (post_to_form
    # mirrors locally only after the cloud accepted the row).
    try:
        with urllib.request.urlopen(FORM_URL, timeout=60) as r:
            form_body = r.read()
        if form_body.decode("utf-8-sig", errors="replace").startswith("Timestamp"):
            FORM_CSV.write_bytes(form_body)
            print(f"wrote {FORM_CSV}  ({form_body.count(b'\n')} rows)")
    except (urllib.error.URLError, OSError) as exc:
        print(f"form tab skipped: {exc}")

    return subprocess.call([sys.executable, str(ROOT / "build.py")])


if __name__ == "__main__":
    raise SystemExit(main())
