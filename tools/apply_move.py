#!/usr/bin/env python3
"""Werk de Google Sheet bij nadat een container fysiek verhuisd is.

    python tools/apply_move.py 1 --dry-run     # laat zien wat er zou gebeuren
    python tools/apply_move.py 1 --yes         # schrijft echt

De sheet is een append-log met "nieuwste rij wint per (doos, onderdeel)", dus
verhuizen = twee rijen: 0 in de oude doos (die wordt daarmee leeg) en het aantal
in de nieuwe doos. Er wordt nooit iets verwijderd; terugdraaien kan door de oude
waarden opnieuw te posten (het journaal hieronder bewaart ze).

Oude dozen met een nummer dat nu door een nieuw label gebruikt wordt, krijgen
tijdelijk 300+nummer zolang er nog spullen in staan — anders zouden twee
verschillende fysieke dozen hetzelfde nummer hebben.
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inventory_core.resolver import CONTAINER_SIZE  # noqa: E402

PLAN = ROOT / "data" / "reorg_plan.json"
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
HOLD_BASE = 300
PAUSE = 1.0          # seconden tussen posts, om Google niet te bestoken


def qty_text(item) -> str:
    if item["countType"] == "exact":
        return str(item["qty"])
    return "many" if item["countType"] == "bulk" else "?"


def post(box: int, name: str, qty: str, note: str) -> bool:
    data = urllib.parse.urlencode({
        CONFIG["form_entries"]["box"]: str(box),
        CONFIG["form_entries"]["name"]: name,
        CONFIG["form_entries"]["qty"]: qty,
        CONFIG["form_entries"]["note"]: note,
    }).encode("utf-8")
    req = urllib.request.Request(CONFIG["form_url"], data=data)
    with urllib.request.urlopen(req, timeout=30) as r:
        return 200 <= r.status < 300


def live_items():
    import main as cloud
    return [i for i in cloud.resolve_items() if i["status"] == "active"]


def build_ops(container: int, items: list[dict]) -> list[dict]:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    lo, hi = (container - 1) * CONTAINER_SIZE + 1, container * CONTAINER_SIZE
    target = {}                                  # (naam) -> nieuwe doos
    for nb, b in plan["boxes"].items():
        if lo <= int(nb) <= hi:
            for p in b["parts"]:
                target[p["name"]] = int(nb)

    by_name_box = {(i["name"], i["box"]): i for i in items}
    ops = []
    for name, new_box in target.items():
        here = [i for i in items if i["name"] == name]
        if not here:
            ops.append({"kind": "missing", "name": name, "newBox": new_box})
            continue
        for item in here:
            if item["box"] == new_box:
                continue                          # al goed geboekt
            ops.append({"kind": "move", "name": name, "oldBox": item["box"],
                        "newBox": new_box, "qty": qty_text(item),
                        "note": item["note"] or ""})

    # alles wat nog in de oude dozen lo..hi staat en nú niet verhuist
    moved = {(o["oldBox"], o["name"]) for o in ops if o["kind"] == "move"}
    for item in items:
        if lo <= item["box"] <= hi and (item["box"], item["name"]) not in moved \
                and item["name"] not in target:
            ops.append({"kind": "hold", "name": item["name"], "oldBox": item["box"],
                        "newBox": HOLD_BASE + item["box"], "qty": qty_text(item),
                        "note": item["note"] or ""})
    return ops


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("container", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true", help="echt schrijven")
    args = ap.parse_args()
    if not (args.dry_run or args.yes):
        print("gebruik --dry-run of --yes", file=sys.stderr)
        return 2

    items = live_items()
    ops = build_ops(args.container, items)
    moves = [o for o in ops if o["kind"] == "move"]
    holds = [o for o in ops if o["kind"] == "hold"]
    missing = [o for o in ops if o["kind"] == "missing"]

    print(f"container {args.container}: {len(moves)} verhuizingen, "
          f"{len(holds)} tijdelijke nummers, {len(missing)} niet gevonden")
    for o in moves + holds:
        print(f"  {o['oldBox']:>4} -> {o['newBox']:<4} {o['qty']:>5}  {o['name'][:60]}")
    for o in missing:
        print(f"  ?? niet in de inventaris: {o['name'][:60]} (zou naar {o['newBox']})")
    print(f"\n{2 * (len(moves) + len(holds))} rijen te posten "
          f"(~{2 * (len(moves) + len(holds)) * PAUSE / 60:.0f} min)")
    if args.dry_run:
        return 0

    today = datetime.date.today().isoformat()
    journal = {"container": args.container, "at": datetime.datetime.now().isoformat(),
               "ops": ops, "posted": []}
    jpath = ROOT / "data" / f"reorg_applied_container_{args.container}.json"
    try:
        for n, o in enumerate(moves + holds, 1):
            # eerst de nieuwe plek vullen, dan pas de oude leegmaken: als het
            # halverwege misgaat staat het onderdeel nergens op 0 zonder dat het
            # ergens anders staat
            post(o["newBox"], o["name"], o["qty"], o["note"])
            journal["posted"].append({"box": o["newBox"], "name": o["name"], "qty": o["qty"]})
            time.sleep(PAUSE)
            post(o["oldBox"], o["name"], "0",
                 f"verplaatst naar doos {o['newBox']} (reorg {today})")
            journal["posted"].append({"box": o["oldBox"], "name": o["name"], "qty": "0"})
            time.sleep(PAUSE)
            print(f"  [{n}/{len(moves) + len(holds)}] {o['oldBox']} -> {o['newBox']}  {o['name'][:50]}")
    finally:
        jpath.write_text(json.dumps(journal, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"journaal: {jpath}")

    # controle: lees de sheet opnieuw en kijk of het er echt staat
    time.sleep(5)
    after = {(i["name"], i["box"]) for i in live_items()}
    bad = [o for o in moves + holds if (o["name"], o["newBox"]) not in after]
    print(f"\ncontrole: {len(moves) + len(holds) - len(bad)} van "
          f"{len(moves) + len(holds)} staan op hun nieuwe plek")
    for o in bad:
        print(f"  MIST: {o['name'][:60]} in doos {o['newBox']}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
