"""tools/place.py: where a photographed part goes.

The answer gets acted on with a part in hand, so the cases worth pinning are
the ones that would send it to the wrong box: counting parts that are about to
leave a box, missing a pile that owns its box, a full flag, or filing a part
that already exists under a second name.
"""
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("place", ROOT / "tools" / "place.py")
place = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(place)


def item(box, name, qty=1, countType="exact", category="misc", status="active", note=""):
    return {"box": box, "name": name, "qty": qty, "countType": countType,
            "category": category, "status": status, "note": note}


def part(name, old, qty=1, countType="exact"):
    return {"name": name, "oldBox": old, "qty": qty, "countType": countType}


# sensor block 4-6 (growth 7-8), power block 9-10 (growth 11-12 = last + 2)
PLAN = {
    "generated": "2026-10-11",
    "rules": {"perBox": 3, "row": 10, "container": 30},
    "boxes": {
        "4": {"category": "sensor", "parts": [part("BME280", 20), part("HC-SR04", 21), part("MPU6050", 22)]},
        "5": {"category": "sensor", "parts": [part("MQ gas sensors", 23, None, "bulk")]},
        "6": {"category": "sensor", "parts": [part("VEML7700", 24), part("tilt sensor", 6)]},
        "9": {"category": "power", "parts": [part("18650 charger module", 25, 4)]},
        "10": {"category": "power", "parts": [part("Buck converter", 26), part("Buck converter", 27)]},
    },
}


def live_all_pending():
    return [item(20, "BME280"), item(21, "HC-SR04"), item(22, "MPU6050"),
            item(23, "MQ gas sensors", None, "bulk"), item(24, "VEML7700"),
            item(6, "tilt sensor"), item(25, "18650 charger module", 4),
            item(26, "Buck converter", 2), item(27, "Buck converter", 3),
            item(7, "Old fastener pile", None, "bulk", "fastener"),
            item(401, "Bath salts", None, "bulk")]


# ---------------------------------------------------------------- the plan
def test_blocks_carry_growth_up_to_the_next_block_and_two_after_the_last():
    blocks = place.category_blocks(PLAN)
    assert blocks["sensor"]["boxes"] == [4, 5, 6]
    assert blocks["sensor"]["growth"] == [7, 8]
    assert blocks["power"]["growth"] == [11, 12]


def test_end_state_counts_what_arrives_not_what_is_there_now():
    final = place.final_contents(PLAN, live_all_pending())
    assert sorted(e["name"] for e in final[4]) == ["BME280", "HC-SR04", "MPU6050"]
    # box 7 is a growth box, but the old pile in it is not in the plan: it stays
    assert [e["name"] for e in final[7]] == ["Old fastener pile"]
    assert 20 not in final, "box 20's part is leaving, it must not count there"


def test_one_name_from_two_old_boxes_is_one_part_in_the_new_box():
    final = place.final_contents(PLAN, live_all_pending())
    assert [e["name"] for e in final[10]] == ["Buck converter"]
    assert final[10][0]["fromBoxes"] == [26, 27]


def test_a_used_up_part_takes_no_room():
    live = [i for i in live_all_pending() if i["name"] != "VEML7700"]
    final = place.final_contents(PLAN, live)
    assert [e["name"] for e in final[6]] == ["tilt sensor"]


def test_progress_reads_moves_back_out_of_the_log():
    live = live_all_pending()
    live = [i for i in live if i["name"] != "BME280"] + [item(4, "BME280")]
    t = place.plan_progress(PLAN, live)
    assert t == {"home": 1, "moved": 1, "pending": 7, "gone": 0}


def test_duplicate_names_in_one_plan_box_are_reported():
    assert place.duplicate_plan_names(PLAN) == [(10, "Buck converter", [26, 27])]


# ------------------------------------------------------------- proposals
def test_new_part_goes_to_the_first_block_box_with_room():
    p = place.propose_new("sensor", False, PLAN, live_all_pending(), set())
    assert p["box"] == 6, "4 is 3/3 and 5 holds a pile"
    assert any("4: 3/3" in s for s in p["skipped"])
    assert any("5: holds a bulk pile" in s for s in p["skipped"])


def test_a_full_flag_is_respected():
    p = place.propose_new("sensor", False, PLAN, live_all_pending(), {6})
    assert p["box"] == 8, "7 is taken by a pile the plan does not move"


def test_a_pile_needs_an_empty_box():
    p = place.propose_new("power", True, PLAN, live_all_pending(), set())
    assert p["box"] == 11
    assert p["kind"] == "growth"


def test_overflow_lands_after_the_block_and_says_so():
    p = place.propose_new("sensor", True, PLAN, live_all_pending(), {8})
    assert p["kind"] == "overflow"
    assert p["box"] not in (4, 5, 6, 7, 8, 9, 10)
    assert any("outside the plan" in w for w in p["warnings"])


def test_a_category_without_a_block_is_not_guessed():
    p = place.propose_new("misc", False, PLAN, live_all_pending(), set())
    assert p["box"] is None
    assert "--category" in p["why"]


def test_label_and_container_warnings():
    p = place.propose_new("sensor", False, PLAN, live_all_pending(), set(), labels_upto=5)
    assert p["box"] == 6
    assert any("no label yet" in w for w in p["warnings"])


def test_now_lists_what_still_has_to_leave_the_box():
    live = live_all_pending() + [item(11, "Encoder", 1)]
    plan = {**PLAN, "boxes": {**PLAN["boxes"],
                              "30": {"category": "switch", "parts": [part("Encoder", 11)]}}}
    p = place.propose_new("power", True, plan, live, set())
    assert p["box"] == 11
    assert p["now"] == [{"name": "Encoder", "qty": 1, "leavesFor": 30}]


# ------------------------------------------------------------- decisions
def test_existing_part_stays_with_its_siblings_and_adds_up():
    d = place.decide("HC-SR04", live_all_pending(), PLAN, set(), qty="2")
    assert d["verdict"] == "existing"
    assert d["box"] == 21, "with the rest, not ahead of them in the plan box"
    assert d["planBox"] == 4
    assert d["row"]["qty"] == "3", "the total, never the delta"


def test_existing_pile_stays_many():
    d = place.decide("MQ gas sensors", live_all_pending(), PLAN, set(), qty="2")
    assert d["row"]["qty"] == "many"


def test_part_number_finds_the_part_under_another_wording():
    d = place.decide("MPU-6050 gyro module", live_all_pending(), PLAN, set())
    assert d["verdict"] == "existing"
    assert d["name"] == "MPU6050"


def test_household_takes_the_lowest_free_number_from_401():
    d = place.decide("Coffee mug", live_all_pending(), PLAN, set(), household=True)
    assert d["box"] == 402
    assert d["container"] == "H1"


def test_new_row_is_bulk_when_qty_is_many():
    d = place.decide("Hall sensor", live_all_pending(), PLAN, set(), qty="many",
                     category="sensor")
    assert d["row"]["qty"] == "many"
    assert d["box"] == 7 or d["box"] == 8


# ----------------------------------------------------------------- search
@pytest.mark.parametrize("query,expect", [
    ("BME280", "BME280"),
    ("bme280 environmental", "BME280"),
    ("Buck converters", "Buck converter"),
])
def test_search_ranks_the_obvious_part_first(query, expect):
    assert place.find_matches(live_all_pending(), query)[0]["name"] == expect


def test_search_ignores_filler_words():
    assert place.similarity("module", "Buck converter module") < 0.3
