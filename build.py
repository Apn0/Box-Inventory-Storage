#!/usr/bin/env python3
"""
Build the Box Inventory app.

Reads  data/inventory_raw.csv   (verbatim export of the Google Sheet)
Writes data/inventory.json      (normalized, resolved, categorised)
       data/snapshot.js         (static ES module export)

Run:  python build.py
"""
from __future__ import annotations

import datetime
import json
import pathlib
import sys

from inventory_core.resolver import (
    CONTAINER_SIZE,
    BULK_SENTINEL,
    CATEGORY_LABELS,
    DEFAULT_CATEGORY,
    BOX_FULL_ITEM,
    BOX_FULL_SLUG,
    parse_date,
    part_numbers,
    categorise,
    container_of,
    COUNTED_MARK,
    parse_raw_rows,
    build_items,
    find_free_boxes,
    find_full_boxes,
    find_split_items,
    group_rows,
    resolve_item,
)

ROOT = pathlib.Path(__file__).resolve().parent
RAW = ROOT / "data" / "inventory_raw.csv"
FORM_CSV = ROOT / "data" / "form_responses.csv"
OUT_JSON = ROOT / "data" / "inventory.json"
OUT_SNAPSHOT_JS = ROOT / "data" / "snapshot.js"

def load_local_rows() -> list[dict] | None:
    if not RAW.exists():
        print(f"missing {RAW}", file=sys.stderr)
        return None
    box_csv_text = RAW.read_text(encoding="utf-8-sig")
    form_csv_text = FORM_CSV.read_text(encoding="utf-8-sig") if FORM_CSV.exists() else None
    return parse_raw_rows(box_csv_text, form_csv_text)

def main() -> int:
    raw_rows = load_local_rows()
    if raw_rows is None:
        return 1

    items = build_items(raw_rows)
    free_boxes = find_free_boxes(items)
    split_items = find_split_items(items)
    full_boxes = find_full_boxes(raw_rows, items)

    if not write_outputs(raw_rows, items, free_boxes, split_items, full_boxes):
        return 1

    print_stats(raw_rows, items, free_boxes, split_items)
    return 0

def write_outputs(raw_rows: list[dict], items: list[dict], free_boxes: list[dict],
                  split_items: list[dict], full_boxes: list[int] | None = None) -> bool:
    data = {
        "meta": {
            "source": "Google Sheet export (Box, Item, Qty, Note, UpdatedAt)",
            "generated": datetime.date.today().isoformat(),
            "rawRows": len(raw_rows),
            "containerSize": CONTAINER_SIZE,
            "bulkSentinel": BULK_SENTINEL,
            "categoryLabels": CATEGORY_LABELS,
        },
        "items": items,
        "freeBoxes": free_boxes,
        "splitItems": split_items,
        "fullBoxes": full_boxes or [],
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    OUT_SNAPSHOT_JS.write_text(f"export const snapshot = {payload};\n", encoding="utf-8")
    return True

def print_stats(raw_rows: list[dict], items: list[dict], free_boxes: list[dict], split_items: list[dict]) -> None:
    active = [i for i in items if i["status"] == "active"]
    print(f"raw rows        {len(raw_rows)}")
    print(f"merged records  {len(items)}  ({len(active)} active, {len(items) - len(active)} gone)")
    print(f"bulk            {sum(1 for i in active if i['countType'] == 'bulk')}")
    print(f"conflicts       {sum(1 for i in items if i['conflict'])}")
    print(f"restated rows   {sum(1 for i in items if i['restated'])}")
    print(f"free boxes      {len(free_boxes)}")
    print(f"split items     {len(split_items)}")
    print(f"categories      {len({i['category'] for i in active})}")
    uncat = [i['name'] for i in active if i['category'] == DEFAULT_CATEGORY]
    print(f"uncategorised   {len(uncat)}")
    for n in uncat:
        print(f"   - {n}")
    print(f"\nwrote {OUT_JSON}\nwrote {OUT_SNAPSHOT_JS}")

if __name__ == "__main__":
    raise SystemExit(main())
