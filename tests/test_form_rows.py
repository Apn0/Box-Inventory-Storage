"""The form tab must reach the resolver.

Every edit the app makes — a new count, an undo, a [BOX FULL] flag — is posted to
the hidden Google Form and lands in the "Form responses" tab, not in the BOX tab.
A refactor (e2ea4b6) once left that parsing in a helper nobody called, so the
Python side silently resolved the BOX tab alone and every app edit was invisible
to build.py, main.py and identify.py for days. These tests pin it down.
"""
from inventory_core.resolver import BOX_FULL_ITEM, build_items, find_full_boxes, parse_raw_rows

BOX_CSV = (
    "Box,Item,Qty,Note,UpdatedAt\n"
    "5,INA219 current/voltage sensor,2,,2026-03-26\n"
    "6,MQ gas sensors,99,,2026-03-26\n"
)


def resolve(form_csv):
    rows = parse_raw_rows(BOX_CSV, form_csv)
    items = build_items(rows)
    if isinstance(items, tuple):          # build_items gained a second return value
        items = items[0]
    return rows, items


def active(items):
    return {(i["box"], i["name"]): i for i in items if i["status"] == "active"}


def test_form_rows_are_parsed_at_all():
    rows, _ = resolve("Timestamp,Box,Item,Qty,Note\n"
                      "14/10/2026 00:48:16,10,INA219 current/voltage sensor,3,moved\n")
    assert [r for r in rows if r["src"] == 1], "form rows never reached raw_rows"


def test_form_row_beats_an_older_box_row():
    _, items = resolve("Timestamp,Box,Item,Qty,Note\n"
                       "14/10/2026 00:48:16,10,INA219 current/voltage sensor,3,moved\n"
                       "14/10/2026 00:48:17,5,INA219 current/voltage sensor,0,moved\n")
    a = active(items)
    assert (5, "INA219 current/voltage sensor") not in a, "the old box was not emptied"
    assert a[(10, "INA219 current/voltage sensor")]["qty"] == 3


def test_form_row_carries_the_time_so_same_day_order_holds():
    """Two edits on one day: the later timestamp wins, not the later line."""
    _, items = resolve("Timestamp,Box,Item,Qty,Note\n"
                       "14/10/2026 09:00:00,6,MQ gas sensors,4,\n"
                       "14/10/2026 08:00:00,6,MQ gas sensors,9,\n")
    assert active(items)[(6, "MQ gas sensors")]["qty"] == 4


def test_box_full_flag_posted_from_the_app_is_seen():
    rows, items = resolve("Timestamp,Box,Item,Qty,Note\n"
                          f"14/10/2026 00:48:25,5,{BOX_FULL_ITEM},1,krap\n")
    assert 5 in set(find_full_boxes(rows, items))
