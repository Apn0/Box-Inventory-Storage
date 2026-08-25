import time
from build import slug

# Dummy data generation
items = []
for idx in range(10000):
    # To create some splits, every 5th item shares a name
    base_idx = idx // 5
    items.append({
        "status": "active",
        "name": f"Item Name {base_idx}",
        "box": idx % 100
    })

def original_method(items):
    by_name = {}
    for i in items:
        if i["status"] != "active":
            continue
        by_name.setdefault(slug(i["name"]), []).append(i["box"])
    split_items = [
        {"name": next(i["name"] for i in items if slug(i["name"]) == k), "boxes": sorted(set(v))}
        for k, v in by_name.items()
        if len(set(v)) > 1
    ]
    return split_items

def optimized_method(items):
    by_name = {}
    orig_name = {}
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
    return split_items

start = time.perf_counter()
original_method(items)
end = time.perf_counter()
print(f"Original method: {end - start:.4f} seconds")

start = time.perf_counter()
optimized_method(items)
end = time.perf_counter()
print(f"Optimized method: {end - start:.4f} seconds")
