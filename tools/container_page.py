#!/usr/bin/env python3
"""Tickable werkblad: maak een oude doos in één keer helemaal leeg.

    python tools/container_page.py 1   ->  data/REORG_CONTAINER_1.html

Eén werkblad per oude container (doos 1-30 = container 1). Per oude doos staat
álles wat erin zit, met de nieuwe doos waar het heen gaat. Zo is de oude doos na
één keer pakken leeg en vrij, in plaats van dat er restjes blijven staan die een
tijdelijk 3xx-nummer nodig hebben (Arno, 2026-10-14).

Wat niet geplaatst kan worden omdat het nummer boven de labels uitkomt, gaat naar
één wachtbak (doos 300) tot die categorie aan de beurt is.

De HTML is tools/container_page.template.html met "__DATA__" als plek voor de
gegevens. Hij mist met opzet doctype/html/head/body: die zet het publiceren eromheen.
"""
from __future__ import annotations

import argparse
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
WAIT_BOX = 300          # de wachtbak voor nummers waar nog geen label voor is
MAX_LABEL = 90          # labels die Arno heeft


def slug(name: str) -> str:
    """Doc-id voor de db: alleen letters, cijfers en '-' zijn daar toegestaan."""
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or "x"


def build(container: int, max_label: int) -> dict:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    lo = (container - 1) * CONTAINER_SIZE + 1
    hi = container * CONTAINER_SIZE

    rows, seen = [], set()
    for nb, b in sorted(plan["boxes"].items(), key=lambda x: int(x[0])):
        for p in b["parts"]:
            if not lo <= p["oldBox"] <= hi:
                continue
            target = int(nb)
            waits = target > max_label
            key = f"c{container}-b{p['oldBox']}-{slug(p['name'])}"
            while key in seen:                      # twee namen die hetzelfde slugen
                key += "-2"
            seen.add(key)
            rows.append({"k": key, "oldBox": p["oldBox"],
                         "newBox": WAIT_BOX if waits else target,
                         "finalBox": target, "waits": waits,
                         "category": b["category"],
                         "categoryLabel": CATEGORY_LABELS.get(b["category"], b["category"]),
                         "name": p["name"], "qty": p["qty"], "countType": p["countType"],
                         "sameNumber": p["oldBox"] == target})

    rows.sort(key=lambda r: (r["oldBox"], r["newBox"], r["name"]))
    pull = [r for r in rows if not r["waits"]]
    waiting = [r for r in rows if r["waits"]]

    by_new: dict[int, list] = {}
    for r in pull:
        by_new.setdefault(r["newBox"], []).append(r)
    new_boxes = [{"box": nb, "categoryLabel": parts[0]["categoryLabel"],
                  "parts": [{k: p[k] for k in ("k", "name", "qty", "countType", "oldBox")}
                            for p in parts]}
                 for nb, parts in sorted(by_new.items())]

    wait_by_old: dict[int, list] = {}
    for r in waiting:
        wait_by_old.setdefault(r["oldBox"], []).append(r)

    return {
        "container": container, "lo": lo, "hi": hi,
        "generated": datetime.date.today().isoformat(),
        "pull": pull + waiting,
        "oldBoxes": sorted({r["oldBox"] for r in rows}),
        "newBoxes": new_boxes,
        "hold": [{"oldBox": b, "newBox": WAIT_BOX,
                  "names": [f"{r['name']}  (hoort in {r['finalBox']})" for r in sorted(rs, key=lambda r: r["name"])]}
                 for b, rs in sorted(wait_by_old.items())],
        "holdCopy": {
            "tab": "Wachtbak",
            "intro": f"Deze onderdelen horen in doos {min((r['finalBox'] for r in waiting), default=0)}"
                     f"–{max((r['finalBox'] for r in waiting), default=0)}. Daar heb je nog geen "
                     f"labels voor, dus ze gaan samen in één wachtbak.",
            "note": f"Plak <b>{WAIT_BOX}</b> op die bak. In de app staan ze dan in doos {WAIT_BOX}, "
                    f"dus je kunt ze gewoon terugvinden. Zodra je de labels boven de "
                    f"{max_label} hebt, leg ik ze alsnog op hun eigen nummer.",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("container", type=int, nargs="?", default=1)
    ap.add_argument("--max-label", type=int, default=MAX_LABEL)
    args = ap.parse_args()

    data = build(args.container, args.max_label)
    page = TEMPLATE.read_text(encoding="utf-8")
    page = page.replace("<title>Container Haallijst</title>",
                        f"<title>Herindeling container {args.container}</title>")
    page = page.replace('"__DATA__"', json.dumps(data, ensure_ascii=False))
    if "__DATA__" in page:
        raise SystemExit("placeholder niet vervangen")

    out = ROOT / "data" / f"REORG_CONTAINER_{args.container}.html"
    out.write_text(page, encoding="utf-8")
    waiting = sum(len(h["names"]) for h in data["hold"])
    print(f"wrote {out}  ({len(page) / 1024:.0f} KB)\n"
          f"  oude dozen {data['lo']}-{data['hi']}: {len(data['oldBoxes'])} dozen leeg te maken, "
          f"{len(data['pull'])} onderdelen\n"
          f"  {len(data['newBoxes'])} nieuwe dozen te vullen, {waiting} naar de wachtbak {WAIT_BOX}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
