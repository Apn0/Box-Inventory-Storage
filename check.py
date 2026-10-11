import json

d = json.load(open('data/inventory.json', encoding='utf-8'))
boxes = {}
conflicts = []
for item in d['items']:
    b = item['box']
    boxes.setdefault(b, []).append(item['updated'])
    if item.get('conflict'):
        conflicts.append(item)

box_last_audit = []
for b, dates in boxes.items():
    dates = [x for x in dates if x]
    if dates:
        box_last_audit.append({'box': b, 'last': max(dates)})

box_last_audit.sort(key=lambda x: x['last'])
print('OLDEST AUDITS (Bottom 10):')
for x in box_last_audit[:10]:
    print(f"Box {x['box']}: {x['last']}")
    
print('\nCONFLICTS:', len(conflicts))
for c in conflicts:
    print(f"Box {c['box']}: {c['name']}")
    
print('\nFULL BOXES:', d.get('fullBoxes'))
