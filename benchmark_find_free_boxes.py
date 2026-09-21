import time
import random
from build import find_free_boxes

def generate_items(num_items):
    items = []
    # Create random item data
    for i in range(1, num_items + 1):
        for j in range(random.randint(1, 3)):
            status = "active" if random.random() > 0.3 else "gone"
            # Some boxes < 400, some > 400
            box_num = i if i < 400 else i + 100
            items.append({"box": box_num, "status": status})
    return items

def run_benchmark(iterations=1000, num_items=500):
    items = generate_items(num_items)

    start_time = time.perf_counter()
    for _ in range(iterations):
        find_free_boxes(items)
    end_time = time.perf_counter()

    elapsed = end_time - start_time
    print(f"Benchmark: {iterations} iterations, {len(items)} items")
    print(f"Time taken: {elapsed:.4f} seconds")
    return elapsed

if __name__ == "__main__":
    run_benchmark()
