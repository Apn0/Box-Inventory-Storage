import timeit

setup_code = """
import random
import uuid

def _norm(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

import re
PART_NUMBER = re.compile(r"^(?:[a-z]{2,}\d{2,}[a-z0-9]*|\d{4,})$")

def _part_numbers(name: str) -> set[str]:
    return {t for t in _norm(name).split() if PART_NUMBER.match(t)}

def find_existing_old(data: dict, name: str) -> dict | None:
    active = [i for i in data["items"] if i["status"] == "active"]
    key = _norm(name)

    for item in active:                                   # exact wins
        if _norm(item["name"]) == key:
            return item

    wanted = _part_numbers(name)                          # then the part number
    if wanted:
        hits = [i for i in active if _part_numbers(i["name"]) & wanted]
        if len(hits) == 1:
            return hits[0]
    return None

import collections
def suggest_box_old(data: dict, category: str) -> tuple[int, str]:
    active = [i for i in data["items"] if i["status"] == "active"]
    per_box = collections.Counter(i["box"] for i in active)

    same_cat = sorted({i["box"] for i in active
                       if i["category"] == category and i["box"] < 400})
    for b in same_cat:
        if per_box[b] < 6:
            return b, "box"

    free = [f["box"] for f in data.get("freeBoxes", []) if f["box"] < 400]
    if free:
        return free[0], "box"

    nxt = max((i["box"] for i in active if i["box"] < 400), default=0) + 1
    return nxt, "box"

def decide_old(data, result):
    qty = max(0, int(result["quantity"]))
    existing = find_existing_old(data, result["name"]) or (
        find_existing_old(data, result["matches_existing"]) if result["matches_existing"] else None)

    if existing:
        return existing

    return suggest_box_old(data, result["category"])

def find_existing_new(active: list[dict], name: str) -> dict | None:
    key = _norm(name)

    for item in active:                                   # exact wins
        if _norm(item["name"]) == key:
            return item

    wanted = _part_numbers(name)                          # then the part number
    if wanted:
        hits = [i for i in active if _part_numbers(i["name"]) & wanted]
        if len(hits) == 1:
            return hits[0]
    return None

def suggest_box_new(data: dict, active: list[dict], category: str) -> tuple[int, str]:
    per_box = collections.Counter(i["box"] for i in active)

    same_cat = sorted({i["box"] for i in active
                       if i["category"] == category and i["box"] < 400})
    for b in same_cat:
        if per_box[b] < 6:
            return b, "box"

    free = [f["box"] for f in data.get("freeBoxes", []) if f["box"] < 400]
    if free:
        return free[0], "box"

    nxt = max((i["box"] for i in active if i["box"] < 400), default=0) + 1
    return nxt, "box"

def decide_new(data, active, result):
    qty = max(0, int(result["quantity"]))
    existing = find_existing_new(active, result["name"]) or (
        find_existing_new(active, result["matches_existing"]) if result["matches_existing"] else None)

    if existing:
        return existing

    return suggest_box_new(data, active, result["category"])

# Generate large dataset
items = []
for i in range(10000):
    items.append({
        "name": f"Part {i} ABC1234",
        "status": "active" if i % 2 == 0 else "inactive",
        "box": i % 100,
        "category": f"cat{i%10}",
        "countType": "exact",
        "qty": 1
    })

data = {"items": items, "freeBoxes": []}
result = {
    "name": "Missing Part DEF567",
    "matches_existing": "Another Missing XYZ890",
    "quantity": 1,
    "category": "cat5"
}

def run_old():
    decide_old(data, result)

def run_new():
    active = [i for i in data["items"] if i["status"] == "active"]
    decide_new(data, active, result)
"""

print("Old Time:", timeit.timeit("run_old()", setup=setup_code, number=100))
print("New Time:", timeit.timeit("run_new()", setup=setup_code, number=100))
