#!/usr/bin/env python3
"""Tickable werkblad voor een container, uit data/reorg_plan.json.

    python tools/container_page.py 1   ->  data/REORG_CONTAINER_1.html

Dezelfde inhoud als container_sheet.py (de .md), maar als pagina waarin je elke
regel kunt aanvinken. De pagina wordt als Artifact gepubliceerd; de vinkjes gaan
naar de `db` van dat Artifact, zodat ze bewaard blijven en ik ze kan uitlezen om
alleen te verwerken wat echt verhuisd is.

De HTML is tools/container_page.template.html met "__DATA__" als plek voor de
gegevens. Hij mist met opzet doctype/html/head/body: die zet het publiceren eromheen.
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inventory_core.resolver import CATEGORY_LABELS, CONTAINER_SIZE  # noqa: E402

PLAN = ROOT / "data" / "reorg_plan.json"
TEMPLATE = ROOT / "tools" / "container_page.template.html"
HOLD_BASE = 300


def slug(name: str) -> str:
    """Doc-id voor de db: alleen letters, cijfers en '-' zijn daar toegestaan."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or "x"


def live_items():
    import main as cloud
    return [i for i in cloud.resolve_items() if i["status"] == "active"]


def build(container: int) -> dict:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    lo = (container - 1) * CONTAINER_SIZE + 1
    hi = container * CONTAINER_SIZE
    boxes = {int(n): b for n, b in plan["boxes"].items() if lo <= int(n) <= hi}
    if not boxes:
        raise SystemExit(f"container {container} is leeg in het plan")

    pull, new_boxes, seen = [], [], set()
    for nb, b in sorted(boxes.items()):
        parts = []
        for p in b["parts"]:
            key = f"c{container}-b{p['oldBox']}-{slug(p['name'])}"
            while key in seen:                      # twee namen die hetzelfde slugen
                key += "-2"
            seen.add(key)
            row = {"k": key, "oldBox": p["oldBox"], "newBox": nb, "name": p["name"],
                   "qty": p["qty"], "countType": p["countType"],
                   "sameNumber": p["oldBox"] == nb}
            pull.append(row)
            parts.append({k: row[k] for k in ("k", "name", "qty", "countType", "oldBox")})
        new_boxes.append({"box": nb, "category": b["category"],
                          "categoryLabel": CATEGORY_LABELS.get(b["category"], b["category"]),
                          "parts": parts})

    pull.sort(key=lambda r: (r["oldBox"], r["newBox"], r["name"]))
    moving = {(r["oldBox"], r["name"]) for r in pull}
    hold: dict[int, list[str]] = {}
    for i in live_items():
        if lo <= i["box"] <= hi and (i["box"], i["name"]) not in moving:
            hold.setdefault(i["box"], []).append(i["name"])

    return {
        "container": container, "lo": lo, "hi": hi,
        "generated": datetime.date.today().isoformat(),
        "pull": pull,
        "oldBoxes": sorted({r["oldBox"] for r in pull}),
        "newBoxes": new_boxes,
        "hold": [{"oldBox": b, "newBox": HOLD_BASE + b, "names": sorted(n)}
                 for b, n in sorted(hold.items())],
    }


def main(container: int) -> int:
    data = build(container)
    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("<title>Container Haallijst</title>",
                        f"<title>Herindeling container {container}</title>")
    page = page.replace('"__DATA__"', json.dumps(data, ensure_ascii=False))
    if "__DATA__" in page:
        raise SystemExit("placeholder niet vervangen")

    out = ROOT / "data" / f"REORG_CONTAINER_{container}.html"
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out}  ({len(page) / 1024:.0f} KB, {len(data['pull'])} regels, "
          f"{len(data['newBoxes'])} nieuwe dozen, "
          f"{sum(len(h['names']) for h in data['hold'])} blijven staan)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(int(sys.argv[1]) if len(sys.argv) > 1 else 1))
