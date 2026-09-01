import timeit

setup_code = """
import random

def slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

import re
PART_NUMBER = re.compile(r"^(?:[a-z]{2,}\d{2,}[a-z0-9]*|\d{4,})$")

def find_existing_old(items: list[dict], name: str) -> dict | None:
    active = [i for i in items if i["status"] == "active"]
    key = slug(name)
    for item in active:
        if slug(item["name"]) == key:
            return item

    def part_numbers(n: str) -> set[str]:
        return {t for t in slug(n).split() if PART_NUMBER.match(t)}

    wanted = part_numbers(name)
    if wanted:
        hits = [i for i in active if part_numbers(i["name"]) & wanted]
        if len(hits) == 1:
            return hits[0]
    return None

def suggest_box_old(items: list[dict], category: str) -> int:
    active = [i for i in items if i["status"] == "active"]
    per_box: dict[int, int] = {}
    for i in active:
        per_box[i["box"]] = per_box.get(i["box"], 0) + 1

    same_cat = sorted({i["box"] for i in active if i["category"] == category and i["box"] < 400})
    for b in same_cat:
        if per_box.get(b, 0) < 6:
            return b

    used = {i["box"] for i in active if i["box"] < 400}
    b = 1
    while b in used:
        b += 1
    return b

def run_identify_old(items, result):
    existing = find_existing_old(items, result["name"]) or (
        find_existing_old(items, result["matches_existing"]) if result.get("matches_existing") else None)

    if existing:
        return existing

    box = suggest_box_old(items, result.get("category", "misc"))
    return box

def find_existing_new(active: list[dict], name: str) -> dict | None:
    key = slug(name)
    for item in active:
        if slug(item["name"]) == key:
            return item

    def part_numbers(n: str) -> set[str]:
        return {t for t in slug(n).split() if PART_NUMBER.match(t)}

    wanted = part_numbers(name)
    if wanted:
        hits = [i for i in active if part_numbers(i["name"]) & wanted]
        if len(hits) == 1:
            return hits[0]
    return None

def suggest_box_new(active: list[dict], category: str) -> int:
    per_box: dict[int, int] = {}
    same_cat = set()
    used = set()

    for i in active:
        b = i["box"]
        per_box[b] = per_box.get(b, 0) + 1
        if b < 400:
            used.add(b)
            if i["category"] == category:
                same_cat.add(b)

    for b in sorted(same_cat):
        if per_box.get(b, 0) < 6:
            return b

    b = 1
    while b in used:
        b += 1
    return b

def run_identify_new(items, result):
    active = [i for i in items if i["status"] == "active"]
    existing = find_existing_new(active, result["name"]) or (
        find_existing_new(active, result["matches_existing"]) if result.get("matches_existing") else None)

    if existing:
        return existing

    box = suggest_box_new(active, result.get("category", "misc"))
    return box

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

result = {
    "name": "Missing Part DEF567",
    "matches_existing": "Another Missing XYZ890",
    "quantity": 1,
    "category": "cat5"
}

def old():
    run_identify_old(items, result)

def new():
    run_identify_new(items, result)
"""

print("Identify Old Time:", timeit.timeit("old()", setup=setup_code, number=100))
print("Identify New Time:", timeit.timeit("new()", setup=setup_code, number=100))
