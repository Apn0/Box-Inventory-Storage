"""The "box is physically full" flag: a [BOX FULL] row, never a part."""
from build import BOX_FULL_ITEM, build_items, find_free_boxes, find_full_boxes
import identify
import main


def row(box, name, qty, date, line, src=0, time="00:00:00"):
    return {"box": box, "name": name, "qty_txt": qty, "note": "", "date": date,
            "time": time, "src": src, "line": line}


PARTS = [
    row(1, "Resistor 10k", "12", "2026-09-01", 2),
    row(2, "Resistor 10k", "3", "2026-09-01", 3),
    row(3, "ESP32-C3", "2", "2026-09-01", 4),
]


def test_flag_row_is_not_a_part():
    items, full_newest = build_items(PARTS + [row(1, BOX_FULL_ITEM, "1", "2026-09-02", 5)])
    assert [i["name"] for i in items if i["box"] == 1] == ["Resistor 10k"]
    assert all("box full" not in i["name"].lower() for i in items)


def test_newest_flag_row_wins():
    flags = [row(1, BOX_FULL_ITEM, "1", "2026-09-02", 5),
             row(1, BOX_FULL_ITEM, "0", "2026-09-03", 6),      # room again
             row(2, BOX_FULL_ITEM, "0", "2026-09-02", 7),
             row(2, BOX_FULL_ITEM, "1", "2026-09-02", 1, src=1, time="12:00:00")]
    items, full_newest = build_items(PARTS + flags)
    assert find_full_boxes(full_newest, items) == [2]


def test_an_emptied_box_is_never_full():
    rows = PARTS + [row(3, "ESP32-C3", "0", "2026-09-05", 8),      # last part gone
                    row(3, BOX_FULL_ITEM, "1", "2026-09-02", 9)]
    items, full_newest = build_items(rows)
    assert find_full_boxes(full_newest, items) == []
    assert 3 in {f["box"] for f in find_free_boxes(items)}


def test_flag_alone_does_not_occupy_a_box():
    rows = PARTS + [row(7, BOX_FULL_ITEM, "1", "2026-09-02", 9)]
    items, full_newest = build_items(rows)
    assert 7 not in {i["box"] for i in items}
    assert find_full_boxes(full_newest, items) == []


def test_cloud_propose_box_skips_full_boxes():
    active = [{"box": 1, "category": "sensor", "boxFull": True},
              {"box": 2, "category": "sensor", "boxFull": False}]
    assert main.propose_box(active, "sensor") == 2
    only_full = [{"box": 1, "category": "sensor", "boxFull": True}]
    assert main.propose_box(only_full, "sensor") == 2      # next unused number


def test_cloud_resolver_drops_flag_and_marks_items(monkeypatch):
    box_csv = ("Box,Item,Qty,Note,UpdatedAt\r\n"
               "1,Resistor 10k,12,,01/09/2026\r\n"
               f"1,{BOX_FULL_ITEM},1,,02/09/2026\r\n"
               "2,ESP32-C3,2,,01/09/2026\r\n")
    monkeypatch.setattr(main, "_fetch", lambda url: box_csv if url == main.BOX_CSV_URL else "")
    items = main.resolve_items()
    assert sorted(i["name"] for i in items) == ["ESP32-C3", "Resistor 10k"]
    assert {i["box"]: i["boxFull"] for i in items} == {1: True, 2: False}


def test_pc_propose_box_skips_full_boxes():
    data = {"freeBoxes": [{"box": 9, "reason": "never used"}], "fullBoxes": [1]}
    active = [{"box": 1, "category": "sensor"}, {"box": 4, "category": "sensor"}]
    assert identify.propose_box(data, active, "sensor")[0] == 4
    data["fullBoxes"] = [1, 4]
    assert identify.propose_box(data, active, "sensor")[0] == 9
