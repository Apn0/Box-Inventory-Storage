import bisect
import csv
import datetime
import operator
import re
from io import StringIO
from typing import Iterable, Any, Dict, List, Optional, Tuple, Set

from utils import slug

# Quantities in the sheet that never meant a literal count.
BULK_SENTINEL = 99
# Marker identify.py writes into the Note of rows it appends.
COUNTED_MARK = "photo-counted"
# Boxes are stored in containers holding this many numbered boxes.
CONTAINER_SIZE = 30
# "This box is physically full" flag.
BOX_FULL_ITEM = "[BOX FULL]"
BOX_FULL_SLUG = slug(BOX_FULL_ITEM)

# ---------------------------------------------------------------- categories
_CATEGORY_RULES_RAW: List[Tuple[str, str]] = [
    ("mcu",        r"esp32|esp8266|xiao|microcontroller|\bmcu\b"),
    ("sensor",     r"\bmq-|mq gas|guva|heart-rate|neo-6m|gps|bme|bmp|environmental sensor|ens160|aht2|gyro|accelerom|"
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

PART_NUMBER = re.compile(r"^(?:[a-z]{2,}\d{2,}[a-z0-9]*|\d{4,})$")

def part_numbers(name: str) -> Set[str]:
    return {t for t in slug(name).split() if PART_NUMBER.match(t)}

def categorise(name: str, note: str) -> str:
    hay = f"{name} {note}".lower()
    for cat, pattern in CATEGORY_RULES:
        if pattern.search(hay):
            return cat
    return DEFAULT_CATEGORY

def parse_date(value: str) -> Optional[str]:
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
    base = 400 if box >= 400 else 0
    n = (box - base - 1) // CONTAINER_SIZE + 1
    return ("H" if base else "") + str(n)

def parse_raw_rows(box_csv_text: str, form_csv_text: Optional[str] = None) -> List[Dict]:
    """Parse CSV text into the common raw_rows format."""
    raw_rows = []
    
    box_reader = csv.DictReader(StringIO(box_csv_text))
    for line_no, row in enumerate(box_reader, start=2):
        box_txt = (row.get("Box") or "").strip()
        if not box_txt or not box_txt.lstrip("-").isdigit():
            continue
        updated_txt = (row.get("UpdatedAt") or "").strip()
        date_part, _, _ = updated_txt.partition(" ")
        try:
            box_date = parse_date(date_part)
        except ValueError:
            box_date = None
        raw_rows.append(
            {
                "line": line_no,
                "box": int(box_txt),
                "name": (row.get("Item") or "").strip(),
                "qty_txt": (row.get("Qty") or "").strip(),
                "note": (row.get("Note") or "").strip(),
                "date": box_date,
                "time": "00:00:00",
                "src": 0,
            }
        )

    if form_csv_text:
        form_reader = csv.DictReader(StringIO(form_csv_text))
        for line_no, row in enumerate(form_reader, start=2):
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

def resolve_item(box: int, key_slug: str, history: List[Dict]) -> Optional[Dict]:
    history_sort_key = lambda r: (r["date"] or "", r["time"], r["src"], r["line"])
    history.sort(key=history_sort_key)
    latest = history[-1]

    if not latest["name"]:
        return None

    def norm_qty(q: str) -> str:
        s = (q or "").strip().lower()
        if s == "99" or s == "many":
            return "many"
        if s == "" or s == "?":
            return "?"
        return s

    qty_values = [norm_qty(r["qty_txt"]) for r in history]
    distinct = {q for q in qty_values}
    restated = len(history) > 1 and len(distinct) == 1
    
    deliberate = (latest.get("src", 0) == 1
                  or COUNTED_MARK in (latest["note"] or "").lower())
    conflict = len(history) > 1 and len(distinct) > 1 and not deliberate

    qty_txt = latest["qty_txt"].strip().lower()
    if qty_txt == "" or qty_txt == "?":
        count_type, qty = "unknown", None
    elif qty_txt == "many" or (qty_txt.lstrip('-').isdigit() and int(qty_txt) == BULK_SENTINEL):
        count_type, qty = "bulk", None
    else:
        try:
            qty = int(qty_txt)
            count_type = "exact"
        except ValueError:
            count_type, qty = "unknown", None

    status = "gone" if (count_type == "exact" and qty == 0) else "active"

    peak = qty if count_type == "exact" else None
    for r in history:
        qt = r["qty_txt"].strip().lower()
        if qt.lstrip('-').isdigit() and int(qt) != BULK_SENTINEL:
            peak = max(peak or 0, int(qt))

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

def group_rows(raw_rows: List[Dict]) -> Dict[Tuple[int, str], List[Dict]]:
    groups: Dict[Tuple[int, str], List[Dict]] = {}
    for row in raw_rows:
        key = (row["box"], slug(row["name"]))
        groups.setdefault(key, []).append(row)
    return groups

def build_items(raw_rows: List[Dict]) -> List[Dict]:
    groups = group_rows(raw_rows)
    items = []
    group_sort_key = operator.itemgetter(0)

    for (box, key_slug), history in sorted(groups.items(), key=group_sort_key):
        if key_slug == BOX_FULL_SLUG:
            continue
        item = resolve_item(box, key_slug, history)
        if item is not None:
            items.append(item)

    return items

def find_free_boxes(items: List[Dict]) -> List[Dict]:
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

def find_full_boxes(raw_rows: List[Dict], items: List[Dict]) -> List[int]:
    newest: Dict[int, Dict] = {}
    for r in raw_rows:
        if slug(r["name"]) != BOX_FULL_SLUG:
            continue
        key = (r["date"] or "", r.get("time", "00:00:00"), r.get("src", 0), r["line"])
        if r["box"] not in newest or key >= newest[r["box"]][0]:
            newest[r["box"]] = (key, r)
    occupied = {i["box"] for i in items if i["status"] == "active"}
    full = []
    for box, (_key, r) in newest.items():
        txt = r["qty_txt"].strip()
        if txt.lstrip("-").isdigit() and int(txt) != 0 and box in occupied:
            full.append(box)
    return sorted(full)

def find_split_items(items: List[Dict]) -> List[Dict]:
    by_name: Dict[str, List[int]] = {}
    orig_name: Dict[str, str] = {}
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

