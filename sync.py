#!/usr/bin/env python3
"""
Pull a fresh copy of the Box Inventory Storage Google Sheet, then rebuild.

Run:  python sync.py

Keeps a timestamped .bak of the previous CSV so a bad download can be undone.
"""
from __future__ import annotations

import datetime
import pathlib
import shutil
import subprocess
import sys
import urllib.request

SHEET_ID = "1ZVVkmA7tI_kqIUi5O-6cw5Az_qfGmKhydgy2QrFWFDQ"
URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"

ROOT = pathlib.Path(__file__).resolve().parent
RAW = ROOT / "data" / "inventory_raw.csv"


def main() -> int:
    print(f"downloading {URL}")
    try:
        with urllib.request.urlopen(URL, timeout=60) as r:
            body = r.read()
    except Exception as exc:
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

    RAW.write_bytes(body)
    print(f"wrote {RAW}  ({rows} lines)")

    return subprocess.call([sys.executable, str(ROOT / "build.py")])


if __name__ == "__main__":
    raise SystemExit(main())
