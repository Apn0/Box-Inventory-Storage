import time
import random

MAX_BOX_ITEMS = 40

def suggest_box_old(active: list[dict], category: str) -> int:
    per_box: dict[int, int] = {}
    for i in active:
        per_box[i["box"]] = per_box.get(i["box"], 0) + 1

    same_cat = sorted({i["box"] for i in active if i["category"] == category and i["box"] < 400})
    for b in same_cat:
        if per_box.get(b, 0) < MAX_BOX_ITEMS:
            return b

    used = {i["box"] for i in active if i["box"] < 400}
    b = 1
    while b in used:
        b += 1
    return b

def suggest_box_new(active: list[dict], category: str) -> int:
    per_box: dict[int, int] = {}
    same_cat = set()

    for i in active:
        b = i["box"]
        per_box[b] = per_box.get(b, 0) + 1
        if b < 400 and i.get("category") == category:
            same_cat.add(b)

    for b in sorted(same_cat):
        if per_box.get(b, 0) < MAX_BOX_ITEMS:
            return b

    b = 1
    while b in per_box and b < 400:
        b += 1
    return b

# Create a mock active list
active = []
categories = ["Electronics", "Books", "Clothing", "Toys"]

# Generate some active items
for i in range(100000):
    active.append({
        "box": random.randint(1, 500),
        "category": random.choice(categories)
    })

def run_benchmark(func, iterations=100):
    start = time.perf_counter()
    for _ in range(iterations):
        func(active, "Electronics")
    end = time.perf_counter()
    return end - start

if __name__ == "__main__":
    t_old = run_benchmark(suggest_box_old)
    t_new = run_benchmark(suggest_box_new)
    print(f"Old time: {t_old:.4f} seconds")
    print(f"New time: {t_new:.4f} seconds")
    print(f"Improvement: {(t_old - t_new) / t_old * 100:.2f}%")
