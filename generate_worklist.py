import json

d = json.load(open('data/inventory.json', encoding='utf-8'))

def container_sort_key(c):
    try: return int(c)
    except: return 9999

items = sorted(d['items'], key=lambda x: (container_sort_key(x.get('container', '9999')), x['box'], x['name']))

with open('walkthrough_worklist.md', 'w', encoding='utf-8') as f:
    f.write("# Inventory Walk-Through Worklist\n\n")
    f.write("*Note: 99 indicates 'a pile' (do not add up).*\n\n")
    
    current_container = None
    for item in items:
        c = item.get('container', 'Unknown')
        if c != current_container:
            if current_container is not None:
                f.write("\n")
            f.write(f"## Container {c}\n\n")
            f.write("| Box | Item | Last Known Qty | Found Qty | Notes / Findings |\n")
            f.write("|-----|------|----------------|-----------|------------------|\n")
            current_container = c
            
        qty = item['qty']
        if qty is None or qty == 99 or qty == "99":
            qty_str = "99 (Pile)"
        else:
            qty_str = str(qty)
            
        conflict_marker = " ⚠️ (Conflict)" if item.get('conflict') else ""
        
        f.write(f"| {item['box']} | {item['name']}{conflict_marker} | {qty_str} | | |\n")

print("Created walkthrough_worklist.md")
