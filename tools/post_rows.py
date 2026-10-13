#!/usr/bin/env python3
"""Post een handvol losse regels naar de sheet, uit een JSON-bestand.

    python tools/post_rows.py rows.json --dry-run
    python tools/post_rows.py rows.json --yes

Voor de herindeling werkt Arno hardop: hij meldt per doos wat er echt in zat en
wat er verhuisd is. Dat zijn correcties die niet in reorg_plan.json staan, dus
apply_move.py kan ze niet bedenken. Dit is dezelfde append-log-regel als daar:
eerst de nieuwe plek vullen, dan pas de oude op 0.

rows.json = [{"box": 10, "name": "...", "qty": "3", "note": "..."}, ...] in de
volgorde waarin ze gepost moeten worden.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
PAUSE = 1.0


def post(box: int, name: str, qty: str, note: str) -> int:
    data = urllib.parse.urlencode({
        CONFIG["form_entries"]["box"]: str(box),
        CONFIG["form_entries"]["name"]: name,
        CONFIG["form_entries"]["qty"]: qty,
        CONFIG["form_entries"]["note"]: note,
    }).encode("utf-8")
    req = urllib.request.Request(CONFIG["form_url"], data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rows")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()
    if not (args.dry_run or args.yes):
        print("gebruik --dry-run of --yes", file=sys.stderr)
        return 2

    rows = json.loads(pathlib.Path(args.rows).read_text(encoding="utf-8"))
    for r in rows:
        print(f"  doos {r['box']:>4}  {r['qty']:>5}  {r['name'][:52]:<52} {r.get('note', '')[:40]}")
    print(f"{len(rows)} regels")
    if args.dry_run:
        return 0

    for n, r in enumerate(rows, 1):
        post(r["box"], r["name"], str(r["qty"]), r.get("note", ""))
        print(f"  [{n}/{len(rows)}] doos {r['box']} <- {r['name'][:46]} = {r['qty']}")
        time.sleep(PAUSE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
