#!/usr/bin/env python3
"""Waar hoort dit onderdeel? Bestaand onderdeel -> zijn doos; nieuw -> de beste doos volgens het plan.

    python tools/place.py "TP4056 Li-ion charger module" --qty 3
    python tools/place.py "M3x8 socket head screw" --qty many
    python tools/place.py "kurk onderzetters" --household
    python tools/place.py --find "mosfet"        # alleen zoeken
    python tools/place.py --status               # ruimte per categorie

Leest alleen: de live sheet (of met --offline de spiegels in data/) en
data/reorg_plan.json. Er gaat niets naar de sheet. Het toont de regel die je
daarna met tools/post_rows.py (--dry-run eerst) kunt posten.

Beslisregels, in deze volgorde:

1. Bestaat het onderdeel al (zelfde naam, of een uniek gedeeld partnummer):
   leg het bij zijn soortgenoten, in de doos waar die NU liggen. Nooit alvast
   in de plandoos: dan staat één onderdeel in twee dozen ("also still in" in
   Walk the shelf). Het nieuwe aantal is het TOTAAL, nooit het verschil.
2. Nieuw onderdeel: de doos waar het na de herindeling hoort, dus direct goed:
   - categorie uit de naam (zelfde regex als de app), of --category;
   - binnen het blok van die categorie in het plan, op nummer;
   - max `rules.perBox` (3) onderdelen per doos, geteld op de EINDSTAND: wat het
     plan erin zet plus wat er na het plan bij is gekomen, en niet wat er nog uit
     moet;
   - een losse hoop (bulk) krijgt een eigen, lege doos; een doos met een hoop
     neemt niets anders;
   - een doos met [BOX FULL] neemt niets;
   - dan de groeidozen na het blok (de lege nummers tot het volgende blok);
   - geen ruimte meer: het eerste nummer na het blok dat in het plan en op de
     plank vrij is, met de waarschuwing dat het blok dan uitloopt.
3. Huishoudelijk (--household): 400-serie, buiten het plan. Eén soort per doos:
   het laagste vrije nummer vanaf 401 (container H1 begint bij 401).

Een plandoos boven het labelnummer (--labels-upto, standaard 90 zoals de app)
heeft nog geen sticker op de plank; dat wordt erbij gezegd, niet overgeslagen.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime
import difflib
import json
import pathlib
import re
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inventory_core.resolver import (  # noqa: E402
    CATEGORY_LABELS, DEFAULT_CATEGORY, build_items, categorise, container_of,
    find_full_boxes, parse_raw_rows, part_numbers,
)
from utils import slug  # noqa: E402

PLAN = ROOT / "data" / "reorg_plan.json"
CONFIG = ROOT / "config.json"
OFFLINE_BOX = ROOT / "data" / "inventory_raw.csv"
OFFLINE_FORM = ROOT / "data" / "form_responses.csv"
HOUSEHOLD_BASE = 400          # 400+ = household, outside the plan
HOUSEHOLD_FIRST = 401         # container H1 = 401-430; 400 itself was never a box
LABELS_DEFAULT = 90          # app.js LABELS_DEFAULT
GROWTH_AFTER_LAST = 2        # REORG_PLAN.md: "na elke categorie 2 lege dozen"
PHOTO_NOTE = "(photo-counted)"

# Words that say nothing about WHICH part it is. Left in, "XY module" matches
# every other module on the shelf.
STOPWORDS = {
    "a", "an", "and", "the", "with", "for", "of", "in", "on", "to", "x",
    "module", "modules", "board", "boards", "breakout", "pcs", "pc", "piece",
    "pieces", "set", "kit", "assorted", "mini", "small", "large", "type",
    "unknown", "new", "old", "black", "white", "red", "blue", "green",
}


# ------------------------------------------------------------------ loading
def _fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8-sig", errors="replace")


def load_rows(offline: bool = False) -> tuple[list[dict], dict]:
    """Raw log rows plus where they came from."""
    if offline:
        box = OFFLINE_BOX.read_text(encoding="utf-8-sig")
        form = OFFLINE_FORM.read_text(encoding="utf-8-sig") if OFFLINE_FORM.exists() else ""
        source = f"offline mirrors {OFFLINE_BOX.name} + {OFFLINE_FORM.name}"
    else:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        base = f"https://docs.google.com/spreadsheets/d/{cfg['sheet_id']}/export?format=csv&gid="
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            box, form = ex.map(_fetch, [base + str(cfg["box_gid"]), base + str(cfg["form_gid"])])
        source = f"live sheet {cfg['sheet_id']} (BOX gid {cfg['box_gid']} + Form gid {cfg['form_gid']})"
    rows = parse_raw_rows(box, form)
    meta = {"source": source, "rawRows": len(rows),
            "fetched": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    return rows, meta


def load_plan() -> dict:
    return json.loads(PLAN.read_text(encoding="utf-8"))


# ------------------------------------------------------------------- search
_LETTER_DASH_DIGIT = re.compile(r"(?<=[A-Za-z])[-_ ](?=\d)")


def pn(name: str) -> set[str]:
    """Part numbers, also when written with a dash: MPU-6050 == MPU6050."""
    return part_numbers(name) | part_numbers(_LETTER_DASH_DIGIT.sub("", name))


def _tokens(text: str) -> set[str]:
    return {t for t in slug(text).split() if t not in STOPWORDS and len(t) > 1}


def _tok_eq(a: str, b: str) -> bool:
    """sensor ~ sensors, mosfet ~ mosfets; not esp32 ~ esp32s3 by accident below 4 chars."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 4 and long_.startswith(short) and len(long_) - len(short) <= 2


def similarity(query: str, name: str, note: str = "") -> float:
    """0..1. Exact name 1.0; shared part number 0.9; else token overlap + spelling."""
    q, n = slug(query), slug(name)
    if not q or not n:
        return 0.0
    if q == n:
        return 1.0
    if pn(query) & pn(name):
        return 0.9
    qt, nt = _tokens(query), _tokens(name) | (_tokens(note) if note else set())
    if not qt or not nt:
        return round(0.4 * difflib.SequenceMatcher(None, q, n).ratio(), 3)
    hit = sum(1 for a in qt if any(_tok_eq(a, b) for b in nt))
    jac = hit / len(qt | _tokens(name)) if (qt | _tokens(name)) else 0.0
    cover = hit / len(qt)
    seq = difflib.SequenceMatcher(None, q, n).ratio()
    return round(min(0.89, 0.45 * cover + 0.3 * jac + 0.25 * seq), 3)


def find_matches(active: list[dict], query: str, top: int = 8, floor: float = 0.25) -> list[dict]:
    scored = [(similarity(query, i["name"], i.get("note", "")), i) for i in active]
    scored = [(s, i) for s, i in scored if s >= floor]
    scored.sort(key=lambda t: (-t[0], t[1]["box"], t[1]["name"].lower()))
    return [dict(i, score=s) for s, i in scored[:top]]


def existing_part(active: list[dict], query: str) -> list[dict]:
    """Every active record of this exact part: same name, or one part number
    that no other part carries. Several boxes back = the part is split."""
    key = slug(query)
    same = [i for i in active if slug(i["name"]) == key]
    if same:
        return same
    wanted = pn(query)
    if not wanted:
        return []
    hits = [i for i in active if wanted & pn(i["name"])]
    if len({slug(i["name"]) for i in hits}) == 1:
        return hits
    return []   # no hit, or the number is on two different parts: a human decides


# ----------------------------------------------------------------- the plan
def plan_targets(plan: dict) -> dict[tuple[str, int], int]:
    """(slug, old box) -> new box, for every part the plan moves or keeps."""
    return {(slug(p["name"]), p["oldBox"]): int(nb)
            for nb, b in plan["boxes"].items() for p in b["parts"]}


def category_blocks(plan: dict) -> dict[str, dict]:
    """category -> its boxes in the plan, plus the growth boxes behind them."""
    by_cat: dict[str, list[int]] = {}
    for nb, b in plan["boxes"].items():
        by_cat.setdefault(b["category"], []).append(int(nb))
    order = sorted(by_cat, key=lambda c: min(by_cat[c]))
    blocks = {}
    for k, cat in enumerate(order):
        boxes = sorted(by_cat[cat])
        hi = boxes[-1]
        nxt = min(by_cat[order[k + 1]]) if k + 1 < len(order) else hi + GROWTH_AFTER_LAST + 1
        blocks[cat] = {"boxes": boxes, "growth": list(range(hi + 1, nxt)),
                       "lo": boxes[0], "hi": hi, "next": nxt}
    return blocks


def final_contents(plan: dict, active: list[dict]) -> dict[int, list[dict]]:
    """What each box < 400 holds once the plan is walked: the plan's parts for it
    (unless used up everywhere) plus anything filed there that the plan does not
    move out. One entry per part name per box, as the append-log keys it."""
    live = {(slug(i["name"]), i["box"]): i for i in active}
    leaving = set()
    out: dict[int, dict[str, dict]] = {}
    for nb, b in plan["boxes"].items():
        to = int(nb)
        for p in b["parts"]:
            k = slug(p["name"])
            if p["oldBox"] != to:
                leaving.add((k, p["oldBox"]))
            here, there = live.get((k, p["oldBox"])), live.get((k, to))
            found = there or here
            if found is None:
                continue        # used up / zeroed: takes no room any more
            entry = out.setdefault(to, {}).setdefault(k, {
                "name": p["name"], "countType": found["countType"],
                "qty": found["qty"], "source": "plan", "fromBoxes": []})
            entry["fromBoxes"].append(p["oldBox"])
            entry["moved"] = entry.get("moved", True) and (to == p["oldBox"] or bool(there and not here))
            if found["countType"] == "bulk":
                entry["countType"] = "bulk"
    for i in active:
        b, k = i["box"], slug(i["name"])
        if b >= HOUSEHOLD_BASE or (k, b) in leaving or k in out.get(b, {}):
            continue
        out.setdefault(b, {})[k] = {"name": i["name"], "countType": i["countType"],
                                    "qty": i["qty"], "source": "filed", "fromBoxes": [b],
                                    "moved": True}
    return {b: list(v.values()) for b, v in out.items()}


def plan_progress(plan: dict, active: list[dict]) -> dict:
    live = {(slug(i["name"]), i["box"]) for i in active}
    tally = {"home": 0, "moved": 0, "pending": 0, "gone": 0}
    for nb, b in plan["boxes"].items():
        to = int(nb)
        for p in b["parts"]:
            k = slug(p["name"])
            here, there = (k, p["oldBox"]) in live, (k, to) in live
            if to == p["oldBox"] and here:
                tally["home"] += 1
            elif there and not here:
                tally["moved"] += 1
            elif here:
                tally["pending"] += 1
            else:
                tally["gone"] += 1
    return tally


def duplicate_plan_names(plan: dict) -> list[tuple[int, str, list[int]]]:
    """A name the plan sends to one box from two old boxes. Walk the shelf
    writes the moved quantity as the box total, so the second tap replaces the
    first count instead of adding to it."""
    out = []
    for nb, b in plan["boxes"].items():
        seen: dict[str, list[int]] = {}
        for p in b["parts"]:
            if p["oldBox"] != int(nb):
                seen.setdefault(slug(p["name"]), []).append(p["oldBox"])
        for k, olds in seen.items():
            if len(olds) > 1:
                name = next(p["name"] for p in b["parts"] if slug(p["name"]) == k)
                out.append((int(nb), name, olds))
    return sorted(out)


# ------------------------------------------------------------------ proposal
def _box_report(box: int, final: dict, active: list[dict], targets: dict,
                full: set, labels_upto: int) -> dict:
    now = [{"name": i["name"], "qty": i["qty"] if i["countType"] == "exact" else i["countType"],
            "leavesFor": (targets.get((slug(i["name"]), box))
                          if targets.get((slug(i["name"]), box)) not in (None, box) else None)}
           for i in active if i["box"] == box]
    return {"box": box, "container": container_of(box),
            "final": [e["name"] for e in final.get(box, [])],
            "now": now, "full": box in full, "labelled": box <= labels_upto}


def propose_new(category: str, bulk: bool, plan: dict, active: list[dict], full: set,
                labels_upto: int = LABELS_DEFAULT, alternatives: int = 2) -> dict:
    per_box = int(plan.get("rules", {}).get("perBox", 3))
    blocks = category_blocks(plan)
    final = final_contents(plan, active)
    targets = plan_targets(plan)
    if category not in blocks:
        return {"box": None, "why": f"category '{category}' has no block in the plan "
                f"(blocks: {', '.join(blocks)}); choose one with --category",
                "alternatives": []}
    blk = blocks[category]
    picks, skipped = [], []
    for kind, boxes in (("block", blk["boxes"]), ("growth", blk["growth"])):
        for b in boxes:
            inside = final.get(b, [])
            has_pile = any(e["countType"] == "bulk" for e in inside)
            if b in full:
                skipped.append(f"{b}: marked [BOX FULL]")
                continue
            if has_pile:
                skipped.append(f"{b}: holds a bulk pile (own box)")
                continue
            if bulk and inside:
                skipped.append(f"{b}: a pile needs an empty box, {len(inside)} part(s) planned")
                continue
            if len(inside) >= per_box:
                skipped.append(f"{b}: {len(inside)}/{per_box} parts planned")
                continue
            why = (f"{CATEGORY_LABELS.get(category, category)} {kind} box, "
                   f"{len(inside)}/{per_box} parts at end state")
            picks.append({"box": b, "kind": kind, "why": why})
    if not picks:
        used = set(final) | {i["box"] for i in active if i["box"] < HOUSEHOLD_BASE}
        n = blk["next"]
        while n in used or str(n) in plan["boxes"]:
            n += 1
        picks.append({"box": n, "kind": "overflow",
                      "why": f"block {blk['lo']}-{blk['hi']} and its growth boxes are full; "
                             f"{n} is the first number free in plan and on the shelf"})
    home = container_of(blk["lo"])
    for p in picks:
        p.update(_box_report(p["box"], final, active, targets, full, labels_upto))
        p["warnings"] = []
        if p["container"] != home:
            p["warnings"].append(f"container {p['container']}, the block starts in container {home}")
        if not p["labelled"]:
            p["warnings"].append(f"no label yet (labels go up to {labels_upto})")
        if p["kind"] == "overflow":
            p["warnings"].append("outside the plan: the category no longer fits its block")
    best = picks[0]
    return {**best, "category": category, "alternatives": picks[1:1 + alternatives],
            "skipped": skipped}


def propose_household(active: list[dict]) -> dict:
    used = {i["box"] for i in active if i["box"] >= HOUSEHOLD_BASE}
    b = HOUSEHOLD_FIRST
    while b in used:
        b += 1
    return {"box": b, "container": container_of(b), "kind": "household",
            "why": f"lowest free household number ({len(used)} household boxes in use)"}


def decide(query: str, active: list[dict], plan: dict, full: set, *, qty: str = "1",
           note: str = "", category: str | None = None, household: bool = False,
           labels_upto: int = LABELS_DEFAULT) -> dict:
    """The whole answer for one photographed part."""
    bulk = str(qty).strip().lower() in ("many", "99", "bulk", "hoop")
    same = existing_part(active, query)
    targets = plan_targets(plan)
    if same:
        here = max(same, key=lambda i: (i["countType"] == "exact", i["qty"] or 0))
        moving = targets.get((slug(here["name"]), here["box"]))
        add = None if bulk else int(qty)
        if here["countType"] == "exact" and add is not None:
            new_qty, how = str(here["qty"] + add), f"{here['qty']} + {add} = {here['qty'] + add}"
        else:
            new_qty, how = "many", "bulk pile, stays 'many'"
        return {"verdict": "existing", "box": here["box"], "name": here["name"],
                "category": here["category"],
                "boxes": sorted({i["box"] for i in same}),
                "planBox": moving if moving not in (None, here["box"]) else None,
                "row": {"box": here["box"], "name": here["name"], "qty": new_qty,
                        "note": PHOTO_NOTE},
                "why": f"already in box {here['box']}; count {how}"}
    if household:
        prop = propose_household(active)
        cat = category or categorise(query, note)
    else:
        cat = category or categorise(query, note)
        prop = propose_new(cat, bulk, plan, active, full, labels_upto)
    row = None if prop["box"] is None else {
        "box": prop["box"], "name": query, "qty": "many" if bulk else str(int(qty)),
        "note": f"{note} {PHOTO_NOTE}".strip()}
    return {"verdict": "new", "name": query, "category": cat, **prop, "row": row}


# --------------------------------------------------------------------- CLI
def _qty_txt(i: dict) -> str:
    return str(i["qty"]) if i["countType"] == "exact" else i["countType"]


def print_matches(matches: list[dict], targets: dict) -> None:
    if not matches:
        print("  (no similar parts on record)")
    for m in matches:
        t = targets.get((slug(m["name"]), m["box"]))
        plan = f" plan->{t}" if t not in (None, m["box"]) else ""
        print(f"  {m['score']:.2f}  box {m['box']:>3}  {_qty_txt(m):>7}  [{m['category']}]  "
              f"{m['name'][:70]}{plan}")


def print_status(plan: dict, active: list[dict], full: set, labels_upto: int) -> None:
    per_box = int(plan["rules"]["perBox"])
    final = final_contents(plan, active)
    print(f"{'category':<20} {'block':>9} {'room':>5} {'empty':>6}  growth")
    for cat, blk in category_blocks(plan).items():
        room = sum(max(0, per_box - len(final.get(b, []))) for b in blk["boxes"]
                   if b not in full and not any(e["countType"] == "bulk" for e in final.get(b, [])))
        empty = [b for b in blk["growth"] if not final.get(b) and b not in full]
        print(f"{CATEGORY_LABELS.get(cat, cat):<20} {blk['lo']:>4}-{blk['hi']:<4} {room:>5} "
              f"{len(empty):>6}  {','.join(map(str, blk['growth'])) or '-'}")
    t = plan_progress(plan, active)
    print(f"\nplan {plan.get('generated')}: {sum(t.values())} parts - {t['home']} home, "
          f"{t['moved']} moved, {t['pending']} still to move, {t['gone']} used up")
    print(f"[BOX FULL]: {', '.join(map(str, sorted(full))) or 'none'}  |  labels up to {labels_upto}")
    for nb, name, olds in duplicate_plan_names(plan):
        print(f"WARNING plan box {nb}: '{name}' arrives from boxes {olds}; Walk the shelf "
              f"writes each move as the box total, so the last tap overwrites the earlier count")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", nargs="?", help="part name as a supplier would write it")
    ap.add_argument("--qty", default="1", help="count in hand, or 'many' for a pile")
    ap.add_argument("--note", default="", help="markings, size, colour (helps the category)")
    ap.add_argument("--category", choices=sorted(CATEGORY_LABELS), help="override the regex category")
    ap.add_argument("--household", action="store_true", help="not electronics: 400-series")
    ap.add_argument("--find", metavar="QUERY", help="only list similar parts")
    ap.add_argument("--status", action="store_true", help="room per category block")
    ap.add_argument("--labels-upto", type=int, default=LABELS_DEFAULT)
    ap.add_argument("--offline", action="store_true", help="use data/*.csv mirrors, not the live sheet")
    ap.add_argument("--json", action="store_true", help="machine-readable result")
    args = ap.parse_args(argv)
    if not (args.name or args.find or args.status):
        ap.error("give a part name, --find or --status")
    qty = str(args.qty).strip().lower()
    if not (qty in ("many", "99", "bulk", "hoop") or (qty.isdigit() and int(qty) > 0)):
        ap.error("--qty is a whole number > 0 or 'many'")

    rows, meta = load_rows(args.offline)
    items = build_items(rows)
    active = [i for i in items if i["status"] == "active"]
    full = set(find_full_boxes(rows, items))
    plan = load_plan()
    targets = plan_targets(plan)

    if not args.json:
        print(f"source: {meta['source']}\nfetched: {meta['fetched']}  raw rows {meta['rawRows']}  "
              f"active parts {len(active)}  boxes {len({i['box'] for i in active})}\n")
    if args.status:
        print_status(plan, active, full, args.labels_upto)
        return 0
    if args.find:
        matches = find_matches(active, args.find, top=15)
        if args.json:
            print(json.dumps({"meta": meta, "matches": matches}, ensure_ascii=False, indent=1, default=str))
        else:
            print_matches(matches, targets)
        return 0

    res = decide(args.name, active, plan, full, qty=qty, note=args.note, category=args.category,
                 household=args.household, labels_upto=args.labels_upto)
    res["similar"] = [m for m in find_matches(active, args.name, top=6)
                      if slug(m["name"]) != slug(res["name"])]
    if args.json:
        print(json.dumps({"meta": meta, **res}, ensure_ascii=False, indent=1, default=str))
        return 0

    print(f"part: {args.name}   qty in hand: {qty}   category: {res['category']} "
          f"({CATEGORY_LABELS.get(res['category'], res['category'])})")
    if res["verdict"] == "existing":
        print(f"\nEXISTING -> box {res['box']}   ({res['why']})")
        if len(res["boxes"]) > 1:
            print(f"  split over boxes {res['boxes']}")
        if res["planBox"]:
            print(f"  plan moves it to box {res['planBox']} later (Walk the shelf); keep it with the rest until then")
    elif res["box"] is None:
        print(f"\nNO PLACE -> {res['why']}")
    else:
        print(f"\nNEW -> box {res['box']} (container {res['container']})   {res['why']}")
        for w in res.get("warnings", []):
            print(f"  ! {w}")
        if res.get("final"):
            print(f"  end state also holds: {'; '.join(res['final'])}")
        for x in res.get("now", []):
            move = f"  -> leaves for {x['leavesFor']}" if x["leavesFor"] else ""
            print(f"  on the shelf now: {x['name']} ({x['qty']}){move}")
        for a in res.get("alternatives", []):
            print(f"  alt: box {a['box']} - {a['why']}" + (f" [{'; '.join(a['warnings'])}]" if a["warnings"] else ""))
    print("\nsimilar on record:")
    print_matches(res["similar"], targets)
    if res.get("row"):
        print("\nrow (post with tools/post_rows.py, --dry-run first):")
        print("  " + json.dumps(res["row"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
