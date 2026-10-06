#!/usr/bin/env python3
"""
Build the Box Inventory app.

Reads  data/inventory_raw.csv   (verbatim export of the Google Sheet)
Writes data/inventory.json      (normalized, resolved, categorised)
       index.html               (single-file offline app, data injected)

Run:  python build.py
"""

import csv
import bisect
import datetime
import json
import operator
import pathlib
import re
import sys

from utils import slug

ROOT = pathlib.Path(__file__).resolve().parent
RAW = ROOT / "data" / "inventory_raw.csv"
FORM_CSV = ROOT / "data" / "form_responses.csv"
OUT_JSON = ROOT / "data" / "inventory.json"
TEMPLATE = ROOT / "src" / "app.template.html"
OUT_HTML = ROOT / "index.html"

# Quantities in the sheet that never meant a literal count.
BULK_SENTINEL = 99
# Marker identify.py writes into the Note of rows it appends. Must match
# COUNTED_MARK in identify.py.
COUNTED_MARK = "photo-counted"
# Boxes are stored in containers holding this many numbered boxes.
CONTAINER_SIZE = 30
# "This box is physically full" is stored as an ordinary row, so it rides the
# same append log and newest-row-wins resolver as a part: Qty 1 = full, 0 = has
# room again. It is a flag, never a part. Must match BOX_FULL in
# src/app.template.html.
BOX_FULL_ITEM = "[BOX FULL]"
BOX_FULL_SLUG = slug(BOX_FULL_ITEM)

# ---------------------------------------------------------------- categories
# Ordered: first matching rule wins. Patterns are matched against the
# lower-cased item name plus its note.
_CATEGORY_RULES_RAW: list[tuple[str, str]] = [
    ("mcu",        r"esp32|esp8266|xiao|microcontroller|\bmcu\b"),
    ("sensor",     r"\bmq-|mq gas|guva|heart-rate|neo-6m|gps|ens160|aht2|gyro|accelerom|"
                   r"mpu6050|hc-sr04|tilt sensor|tof|vl53|veml|hall sensor|reed |"
                   r"vibration (sensor|switch)|pressure sensor|load cell|current sensor|"
                   r"current transformer|ina219|audio-wave|lm393|magnetic switch|rd-03d|"
                   r"capacitive touch|ir receiver|laser sensor|mps20n|voltage sensor|"
                   r"coil-type vibration|pressure-sensitive"),
    ("power",      r"charger|converter|buck|boost|step-up|step-down|mt3608|mini-360|hw-187|"
                   r"mp1584|cr6030|pd trigger|fast-charge|solar charge|18650|battery|"
                   r"batteries|lr44|\bac/dc\b|power module|power meter|v meter|"
                   r"level indicator|usb-a power"),
    ("driver",     r"tmc2209|uln2003|motor driver|h-bridge|tc1508|mosfet|relay|\bssr\b|"
                   r"pwm controller|speed controller|stepper driver|xy-mos|lr7843"),
    ("motor",      r"stepper motor|servo|dc motor|gear motor|brushed dc|vibration motor|"
                   r"\bfan\b|micro dc"),
    ("display",    r"oled|7-seg|\bled\b|leds|cob|rgb|traffic-light|candle|flasher|display"),
    ("comms",      r"wi-fi|wifi|uart|ir transmitter|nfc|sim card|rj-45|tracker tag|"
                   r"walkie|receiver \(dongle\)|wireless mouse|laser diode"),
    ("interface",  r"ads1115|\badc\b|hx711|pcm1808|i2s|555 timer|breakout|serial adapter|"
                   r"usb-to-ttl|hw-477|sku7810"),
    ("switch",     r"switch|button|potentiometer|encoder|knob|key lock|\bkeys?\b|"
                   r"navigation tactile|piezoelectric spark"),
    ("connector",  r"xt60|usb|hdmi|barrel|header pin|terminal|alligator|wire connector|"
                   r"kroonsteentje|audio plug|adapter|coupling|connector|iec panel|"
                   r"strip connector|cable reel"),
    ("fastener",   r"bolt|screw|\bnuts?\b|washer|standoff|tap bits|drill|countersink|"
                   r"barrel nut|mounting hardware|lock nut|lock washer"),
    ("mechanical", r"gear|pulley|belt|bearing|idler|rail|carriage|tube|tubing|heatsink|"
                   r"disk|bracket|mechanical parts|nozzle|clamp|padlock|clip|"
                   r"elastic band|spacer"),
    ("tool",       r"tool|bit set|measuring tape|keycap remover|radiator valve|tape|"
                   r"lens kit|hemming"),
    ("material",   r"scrap|shavings|sawdust|flakes|granules|seeds|salts|foam|earplug|"
                   r"popsicle|hot-glue|shoelace|gemstone|coil|sticker|label"),
]
CATEGORY_RULES = [(cat, re.compile(pattern)) for cat, pattern in _CATEGORY_RULES_RAW]
DEFAULT_CATEGORY = "misc"

CATEGORY_LABELS = {
    "mcu": "MCU / boards",
    "sensor": "Sensors",
    "power": "Power",
    "driver": "Drivers / switching",
    "motor": "Motors",
    "display": "LED / display",
    "comms": "Comms / RF / optical",
    "interface": "ADC / interface",
    "switch": "Switches / controls",
    "connector": "Connectors / cable",
    "fastener": "Fasteners",
    "mechanical": "Mechanical",
    "tool": "Tools",
    "material": "Raw material",
    "misc": "Misc",
}


# A part number: letters followed by digits (tmc2209, mt3608, esp32, ads1115),
# or a bare run of digits (18650). Distinctive enough to identify a part on its
# own, which plain words like "module" or "sensor" are not.
PART_NUMBER = re.compile(r"^(?:[a-z]{2,}\d{2,}[a-z0-9]*|\d{4,})$")


def part_numbers(name: str) -> set[str]:
    return {t for t in slug(name).split() if PART_NUMBER.match(t)}



def categorise(name: str, note: str) -> str:
    hay = f"{name} {note}".lower()
    for cat, pattern in CATEGORY_RULES:
        if pattern.search(hay):
            return cat
    return DEFAULT_CATEGORY


def parse_date(value: str) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {value!r}")


def container_of(box: int) -> str:
    """Boxes live in containers of CONTAINER_SIZE.

    Boxes below 400 and the 400-series are two physically separate sets of
    containers, so each set is numbered from its own start ("1", "H1", ...).
    Must stay identical to containerOf() in src/app.template.html.
    """
    base = 400 if box >= 400 else 0
    n = (box - base - 1) // CONTAINER_SIZE + 1
    return ("H" if base else "") + str(n)


def load_raw_rows() -> list[dict] | None:
    if not RAW.exists():
        print(f"missing {RAW}", file=sys.stderr)
        return None

    raw_rows = []
    with RAW.open(newline="", encoding="utf-8-sig") as fh:
        for line_no, row in enumerate(csv.DictReader(fh), start=2):
            box_txt = (row.get("Box") or "").strip()
            if not box_txt:
                continue
            raw_rows.append(
                {
                    "line": line_no,
                    "box": int(box_txt),
                    "name": (row.get("Item") or "").strip(),
                    "qty_txt": (row.get("Qty") or "").strip(),
                    "note": (row.get("Note") or "").strip(),
                    "date": parse_date(row.get("UpdatedAt") or ""),
                    "time": "00:00:00",
                    "src": 0,
                }
            )

    # Rows written through the Google Form (phone counts, photo confirms).
    # They carry a real time of day, so a form write on the same day as a
    # hand edit deliberately wins; being deliberate recounts, they are also
    # exempt from the ambiguity flag. Same rules as the JS resolver in
    # src/app.template.html — keep the two in step.
    if FORM_CSV.exists():
        with FORM_CSV.open(newline="", encoding="utf-8-sig") as fh:
            for line_no, row in enumerate(csv.DictReader(fh), start=2):
                box_txt = (row.get("Box") or "").strip()
                name = (row.get("Item") or "").strip()
                if not box_txt or not name or not box_txt.lstrip("-").isdigit():
                    continue
                ts = (row.get("Timestamp") or "").strip()
                date_part, _, time_part = ts.partition(" ")
                try:
                    date = parse_date(date_part)
                except ValueError:
                    date = None
                raw_rows.append(
                    {
                        "line": line_no,
                        "box": int(box_txt),
                        "name": name,
                        "qty_txt": (row.get("Qty") or "").strip(),
                        "note": (row.get("Note") or "").strip(),
                        "date": date,
                        "time": time_part or "00:00:01",
                        "src": 1,
                    }
                )
    return raw_rows


def resolve_item(box: int, key_slug: str, history: list[dict]) -> dict | None:
    history_sort_key = lambda r: (r["date"] or "", r["time"], r["src"], r["line"])
    history.sort(key=history_sort_key)
    latest = history[-1]

    if not latest["name"]:
        # Box 81: a placeholder row with no item at all.
        return None

    distinct = {r["qty_txt"] for r in history}
    restated = len(history) > 1 and len(distinct) == 1
    # Differing quantities normally mean the sheet contradicts itself. A row
    # identify.py wrote is a deliberate recount, not an ambiguity — it says
    # so in its Note, so it must not raise a false flag on every photo filed.
    deliberate = (latest.get("src", 0) == 1
                  or COUNTED_MARK in (latest["note"] or "").lower())
    conflict = len(history) > 1 and len(distinct) > 1 and not deliberate

    qty_txt = latest["qty_txt"]
    if qty_txt == "":
        count_type, qty = "unknown", None
    elif int(qty_txt) == BULK_SENTINEL:
        count_type, qty = "bulk", None
    else:
        count_type, qty = "exact", int(qty_txt)

    status = "gone" if (count_type == "exact" and qty == 0) else "active"

    # The highest count ever recorded. Without it "running low" fires on
    # every part you simply own one of, which was 128 of 242 items — noise
    # that hides the handful actually being used up.
    peak = qty if count_type == "exact" else None
    for r in history:
        if r["qty_txt"].isdigit() and int(r["qty_txt"]) != BULK_SENTINEL:
            peak = max(peak or 0, int(r["qty_txt"]))

    note = latest["note"] or next((r["note"] for r in reversed(history) if r["note"]), "")

    return {
        "id": f"{box}-{key_slug}" if key_slug else f"{box}-item",
        "box": box,
        "container": container_of(box),
        "name": latest["name"],
        "qty": qty,
        "peak": peak,
        "countType": count_type,
        "status": status,
        "note": note,
        "category": categorise(latest["name"], note),
        "updated": latest["date"],
        "conflict": conflict,
        "restated": restated,
        "history": [
            {"qty": r["qty_txt"], "date": r["date"], "note": r["note"]}
            for r in history
        ]
        if len(history) > 1
        else [],
    }


def group_rows(raw_rows: list[dict]) -> dict[tuple[int, str], list[dict]]:
    """Group into one record per (box, item), newest row wins."""
    groups: dict[tuple[int, str], list[dict]] = {}
    for row in raw_rows:
        key = (row["box"], slug(row["name"]))
        groups.setdefault(key, []).append(row)
    return groups


def build_items(raw_rows: list[dict]) -> tuple[list[dict], dict[int, dict]]:
    groups = group_rows(raw_rows)

    items = []
    full_newest = {}
    # Sort keys for performance
    group_sort_key = operator.itemgetter(0)

    for (box, key_slug), history in sorted(groups.items(), key=group_sort_key):
        if key_slug == BOX_FULL_SLUG:
            history_sort_key = lambda r: (r["date"] or "", r.get("time", "00:00:00"), r.get("src", 0), r["line"])
            newest_row = max(history, key=history_sort_key)
            full_newest[box] = newest_row
            continue                     # a box flag, see find_full_boxes
        item = resolve_item(box, key_slug, history)
        if item is not None:
            items.append(item)

    return items, full_newest


def find_free_boxes(items: list[dict]) -> list[dict]:
    used_boxes_set = {i["box"] for i in items}
    used_boxes = sorted(used_boxes_set)
    split_idx = bisect.bisect_left(used_boxes, 400)
    low = used_boxes[:split_idx]
    high = used_boxes[split_idx:]

    active_keys = {i["box"] for i in items if i["status"] == "active"}

    free_boxes = []
    for lo, hi in ((1, max(low) if low else 0), (400, max(high) if high else 0)):
        free_box_nums = set(range(lo, hi + 1)) - active_keys
        for b in sorted(free_box_nums):
            reason = "emptied" if b in used_boxes_set else "never used"
            free_boxes.append({"box": b, "container": container_of(b), "reason": reason})
    return free_boxes


def find_full_boxes(full_newest: dict[int, dict], items: list[dict]) -> list[int]:
    """Boxes whose newest BOX_FULL row says full and that still hold a part.

    An emptied box cannot be full, so the flag lapses by itself once the last
    part leaves — no stale "full" on a box that is sitting empty.
    """
    occupied = {i["box"] for i in items if i["status"] == "active"}
    full = []
    for box, r in full_newest.items():
        txt = r["qty_txt"].strip()
        if txt.lstrip("-").isdigit() and int(txt) != 0 and box in occupied:
            full.append(box)
    return sorted(full)


def find_split_items(items: list[dict]) -> list[dict]:
    by_name: dict[str, list[int]] = {}
    orig_name: dict[str, str] = {}
    for i in items:
        if i["status"] != "active":
            continue
        k = slug(i["name"])
        by_name.setdefault(k, []).append(i["box"])
        if k not in orig_name:
            orig_name[k] = i["name"]
    split_items = [
        {"name": orig_name[k], "boxes": sorted(set(v))}
        for k, v in by_name.items()
        if len(set(v)) > 1
    ]
    split_items.sort(key=lambda s: s["name"].lower())
    return split_items


def main() -> int:
    raw_rows = load_raw_rows()
    if raw_rows is None:
        return 1

    items, full_newest = build_items(raw_rows)
    free_boxes = find_free_boxes(items)
    split_items = find_split_items(items)
    full_boxes = find_full_boxes(full_newest, items)

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

    template = TEMPLATE.read_text(encoding="utf-8")
    marker = "/*__INVENTORY_DATA__*/null"
    if marker not in template:
        print(f"template is missing the {marker} marker", file=sys.stderr)
        return False
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    OUT_HTML.write_text(template.replace(marker, payload), encoding="utf-8")
    return True


def print_stats(raw_rows: list[dict], items: list[dict], free_boxes: list[dict], split_items: list[dict]) -> None:
    active = [i for i in items if i["status"] == "active"]
    print(f"raw rows        {len(raw_rows)}")
    print(f"merged records  {len(items)}  ({len(active)} active, {len(items) - len(active)} gone)")
    print(f"bulk (was 99)   {sum(1 for i in active if i['countType'] == 'bulk')}")
    print(f"conflicts       {sum(1 for i in items if i['conflict'])}")
    print(f"restated rows   {sum(1 for i in items if i['restated'])}")
    print(f"free boxes      {len(free_boxes)}")
    print(f"split items     {len(split_items)}")
    print(f"categories      {len({i['category'] for i in active})}")
    uncat = [i['name'] for i in active if i['category'] == DEFAULT_CATEGORY]
    print(f"uncategorised   {len(uncat)}")
    for n in uncat:
        print(f"   - {n}")
    print(f"\nwrote {OUT_JSON}\nwrote {OUT_HTML}")


if __name__ == "__main__":
    raise SystemExit(main())
