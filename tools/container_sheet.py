#!/usr/bin/env python3
"""Werkblad voor één container uit data/reorg_plan.json.

    python tools/container_sheet.py 1    ->  data/REORG_CONTAINER_1.md

Toont per nieuwe doos wat erin komt, daarna een haallijst per oude doos, en
tenslotte wat er na deze ronde nog in de oude dozen staat: dat blijft liggen
waar het ligt, zonder nieuw nummer.

Dit is de print-versie. Tikken terwijl je loopt gaat via Walk the shelf in de
app, die de verhuizing meteen in de sheet zet.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inventory_core.resolver import CATEGORY_LABELS, CONTAINER_SIZE  # noqa: E402

PLAN = ROOT / "data" / "reorg_plan.json"


def live_items():
    import main as cloud
    return [i for i in cloud.resolve_items() if i["status"] == "active"]


def main(container: int) -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    lo = (container - 1) * CONTAINER_SIZE + 1
    hi = container * CONTAINER_SIZE
    boxes = {int(n): b for n, b in plan["boxes"].items() if lo <= int(n) <= hi}
    if not boxes:
        print(f"container {container} is leeg in het plan", file=sys.stderr)
        return 1

    moving = {(p["oldBox"], p["name"]) for b in boxes.values() for p in b["parts"]}
    left = [i for i in live_items()
            if lo <= i["box"] <= hi and (i["box"], i["name"]) not in moving]

    out = []
    A = out.append
    A(f"# Container {container} — werkblad (dozen {lo}–{hi})")
    A("")
    A(f"Gemaakt {datetime.date.today().isoformat()}. "
      f"{len(boxes)} dozen vullen, {len(moving)} onderdelen, "
      f"uit {len({o for o, _ in moving})} oude dozen.")
    A("")
    A("Werk de haallijst af: pak een oude doos, leg de genoemde onderdelen in de "
      "nieuwe genummerde doos. Zeg het als je klaar bent, dan werk ik de sheet bij.")
    A("")
    A("## Haallijst — per oude doos")
    A("")
    A("| Oude doos | Onderdeel | Aantal | → nieuwe doos |")
    A("|---|---|---|---|")
    rows = [(p["oldBox"], p["name"], p["qty"] if p["countType"] == "exact" else "hoop", nb)
            for nb, b in sorted(boxes.items()) for p in b["parts"]]
    for old, name, qty, new in sorted(rows, key=lambda r: (r[0], r[3])):
        A(f"| {old} | {name} | {qty} | **{new}** |")
    A("")
    A("## Controle — wat hoort er straks in elke nieuwe doos")
    A("")
    A("| Nieuwe doos | Categorie | Onderdelen |")
    A("|---|---|---|")
    for nb, b in sorted(boxes.items()):
        names = "<br>".join(f"{p['name']} ({p['qty'] if p['countType'] == 'exact' else 'hoop'})"
                            for p in b["parts"])
        A(f"| {nb} | {CATEGORY_LABELS.get(b['category'], b['category'])} | {names} |")
    A("")
    if left:
        A(f"## Blijft voorlopig in de oude dozen {lo}–{hi}")
        A("")
        A(f"Deze {len(left)} onderdelen horen bij een latere categorie. Ze blijven "
          f"staan waar ze staan en krijgen geen nieuw nummer; er is geen tussenbak. "
          f"Zodra hun eigen container aan de beurt is gaan ze in één keer naar hun "
          f"eigen doos.")
        A("")
        A("| Oude doos | Onderdeel |")
        A("|---|---|")
        for i in sorted(left, key=lambda i: (i["box"], i["name"])):
            A(f"| {i['box']} | {i['name']} |")

    path = ROOT / "data" / f"REORG_CONTAINER_{container}.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {path}  ({len(boxes)} boxes, {len(moving)} parts, {len(left)} left behind)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1))
