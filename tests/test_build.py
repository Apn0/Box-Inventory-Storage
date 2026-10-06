from build import resolve_item, BULK_SENTINEL, COUNTED_MARK
import pytest
from build import parse_date, group_rows, find_split_items, container_of, part_numbers, categorise, build_items, find_free_boxes

def test_parse_date_happy_paths():
    assert parse_date("01/12/2023") == "2023-12-01"
    assert parse_date("2023-12-01") == "2023-12-01"
    assert parse_date("01-12-2023") == "2023-12-01"


def test_parse_date_empty_inputs():
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("   ") is None


def test_parse_date_error_paths():
    with pytest.raises(ValueError, match="unparseable date: 'not a date'"):
        parse_date("not a date")

    with pytest.raises(ValueError, match="unparseable date: '2023/12/01'"):
        parse_date("2023/12/01")

    with pytest.raises(ValueError, match="unparseable date: '32/01/2023'"):
        parse_date("32/01/2023")

    with pytest.raises(ValueError, match="unparseable date: '2023-13-01'"):
        parse_date("2023-13-01")

def test_find_free_boxes_empty():
    assert find_free_boxes([]) == []

def test_find_free_boxes_active_continuous():
    items = [
        {"box": 1, "status": "active"},
        {"box": 2, "status": "active"}
    ]
    assert find_free_boxes(items) == []

def test_find_free_boxes_emptied():
    items = [
        {"box": 1, "status": "active"},
        {"box": 2, "status": "inactive"},
        {"box": 3, "status": "active"}
    ]
    result = find_free_boxes(items)
    assert len(result) == 1
    assert result[0] == {"box": 2, "container": container_of(2), "reason": "emptied"}

def test_find_free_boxes_never_used():
    items = [
        {"box": 1, "status": "active"},
        {"box": 4, "status": "active"}
    ]
    result = find_free_boxes(items)
    assert len(result) == 2
    assert result[0] == {"box": 2, "container": container_of(2), "reason": "never used"}
    assert result[1] == {"box": 3, "container": container_of(3), "reason": "never used"}

def test_find_free_boxes_high():
    items = [
        {"box": 400, "status": "active"},
        {"box": 402, "status": "active"}
    ]
    result = find_free_boxes(items)
    assert len(result) == 1
    assert result[0] == {"box": 401, "container": container_of(401), "reason": "never used"}

def test_find_free_boxes_mixed():
    items = [
        {"box": 1, "status": "active"},
        {"box": 2, "status": "inactive"},
        {"box": 4, "status": "active"},
        {"box": 400, "status": "active"},
        {"box": 402, "status": "inactive"}
    ]
    result = find_free_boxes(items)
    assert len(result) == 4
    assert result[0] == {"box": 2, "container": container_of(2), "reason": "emptied"}
    assert result[1] == {"box": 3, "container": container_of(3), "reason": "never used"}
    assert result[2] == {"box": 401, "container": container_of(401), "reason": "never used"}
    assert result[3] == {"box": 402, "container": container_of(402), "reason": "emptied"}


def test_find_split_items_basic():
    items = [
        {"name": "Resistor 10k", "box": 1, "status": "active"},
        {"name": "Resistor 10k", "box": 2, "status": "active"},
        {"name": "Capacitor 100uF", "box": 1, "status": "active"},
    ]
    result = find_split_items(items)
    assert result == [{"name": "Resistor 10k", "boxes": [1, 2]}]


def test_find_split_items_ignores_inactive():
    items = [
        {"name": "LED Blue", "box": 3, "status": "active"},
        {"name": "LED Blue", "box": 4, "status": "gone"},
    ]
    result = find_split_items(items)
    assert result == []


def test_find_split_items_slug_matching():
    items = [
        {"name": "ESP32 Board", "box": 5, "status": "active"},
        {"name": "esp32 board", "box": 6, "status": "active"},
        {"name": "  esp32  BOARD ", "box": 7, "status": "active"},
    ]
    result = find_split_items(items)
    assert len(result) == 1
    assert result[0]["name"] == "ESP32 Board"
    assert result[0]["boxes"] == [5, 6, 7]


def test_find_split_items_duplicate_boxes():
    items = [
        {"name": "Wire", "box": 8, "status": "active"},
        {"name": "Wire", "box": 8, "status": "active"},
    ]
    result = find_split_items(items)
    assert result == []


def test_find_split_items_sorting():
    items = [
        {"name": "Zener Diode", "box": 10, "status": "active"},
        {"name": "Zener Diode", "box": 11, "status": "active"},
        {"name": "Arduino", "box": 12, "status": "active"},
        {"name": "Arduino", "box": 13, "status": "active"},
    ]
    result = find_split_items(items)
    assert len(result) == 2
    assert result[0]["name"] == "Arduino"
    assert result[1]["name"] == "Zener Diode"


@pytest.mark.parametrize("box, expected", [
    (1, "1"),
    (2, "1"),
    (30, "1"),
    (31, "2"),
    (60, "2"),
    (61, "3"),
    (399, "14"),
    (400, "H0"),
    (401, "H1"),
    (430, "H1"),
    (431, "H2"),
    (460, "H2"),
    (461, "H3"),
])
def test_container_of(box, expected):
    """Boxes are grouped into containers of size 30.
    The 400-series starts a new physical set of containers with an 'H' prefix.
    """
    assert container_of(box) == expected


@pytest.mark.parametrize("name, expected", [
    # Happy paths - typical part numbers
    ("tmc2209", {"tmc2209"}),
    ("mt3608 module", {"mt3608"}),
    ("esp32 board", {"esp32"}),
    ("ads1115 adc", {"ads1115"}),
    # Case insensitivity (slug converts to lower)
    ("ESP32", {"esp32"}),
    ("LM393 Sensor", {"lm393"}),
    # Special characters and separators
    ("hc-sr04", {"sr04"}),  # 'hc' is discarded, 'sr04' matches
    # slug turns it into 'neo 6m gps'. 'neo' has no digits, '6m' lacks 2+
    # letters
    ("neo-6m gps", set()),
    # Multiple parts
    ("esp32 with mt3608", {"esp32", "mt3608"}),
    # Bare runs of digits (4+ digits)
    ("18650 battery", {"18650"}),
    ("sku7810", {"sku7810"}),
    # Part numbers with trailing letters/digits
    ("esp32c3 board", {"esp32c3"}),
    ("ch340g chip", {"ch340g"}),
    ("lm2596s module", {"lm2596s"}),
    # Negatives - should not match
    ("module", set()),  # no digits
    ("sensor", set()),  # no digits
    ("v2", set()),  # only 1 letter
    ("m3", set()),  # only 1 letter
    ("42", set()),  # bare run of digits but less than 4 digits
    ("123", set()),  # bare run of digits but less than 4 digits
    ("esp3", set()),  # only 1 digit, requires 2+ digits according to actual regex
    ("", set()),  # empty string
    ("   ", set()),  # whitespace
])
def test_part_numbers(name, expected):
    """Test extracting part numbers from a string.
    Expects 2+ letters followed by 2+ digits, or a bare run of 4+ digits.
    """
    assert part_numbers(name) == expected


@pytest.mark.parametrize("name, note, expected", [
    # Basic matches
    ("ESP32", "", "mcu"),
    ("Capacitor", "10uF", "misc"),  # Default category
    ("LED", "Red", "display"),  # Case insensitive match

    # Matching in note vs name
    ("Unknown item", "Use as an mcu", "mcu"),
    ("stepper motor", "broken", "motor"),
    ("broken item", "stepper motor", "motor"),

    # Word boundaries (\b)
    ("mcu", "", "mcu"),
    ("mcus", "", "misc"),  # Should not match \bmcu\b
    ("fan", "", "motor"),  # \bfan\b
    ("fancy", "", "misc"),  # Should not match
    ("adc", "", "interface"),  # \badc\b
    ("adcs", "", "misc"),

    # Precedence (first matching rule wins)
    ("esp32", "with gps", "mcu"),  # "mcu" comes before "sensor" (gps)
    # even if gps is in name, esp32 matches the 'mcu' rule which is checked
    # first
    ("gps", "with esp32", "mcu"),

    # Complex names
    ("esp8266 node mcu", "", "mcu"),
    ("18650 battery holder", "", "power"),
    ("M3 screw", "10mm", "fastener"),
    ("Wire connector", "2-pin", "connector"),
    ("Arduino", "Breakout board", "interface"),
])
def test_categorise(name, note, expected):
    """Test the categorise function for assigning categories to items based on regex patterns."""
    assert categorise(name, note) == expected


def test_resolve_item_basic():
    history = [
        {
            "name": "Resistor",
            "qty_txt": "10",
            "note": "Some note",
            "date": "2023-10-01",
            "time": "10:00:00",
            "src": 0,
            "line": 1
        }
    ]
    result = resolve_item(1, "resistor", history)
    assert result is not None
    assert result["id"] == "1-resistor"
    assert result["box"] == 1
    assert result["name"] == "Resistor"
    assert result["qty"] == 10
    assert result["countType"] == "exact"
    assert result["status"] == "active"
    assert result["peak"] == 10
    assert result["note"] == "Some note"
    assert result["conflict"] is False
    assert result["restated"] is False
    assert result["history"] == []


def test_resolve_item_sorting():
    history = [
        {
            "name": "Capacitor",
            "qty_txt": "5",
            "note": "Later",
            "date": "2023-10-02",
            "time": "10:00:00",
            "src": 0,
            "line": 2
        },
        {
            "name": "Capacitor",
            "qty_txt": "2",
            "note": "Earlier",
            "date": "2023-10-01",
            "time": "10:00:00",
            "src": 0,
            "line": 1
        }
    ]
    result = resolve_item(1, "capacitor", history)
    assert result["qty"] == 5
    assert result["note"] == "Later"
    assert len(result["history"]) == 2
    assert result["history"][0]["qty"] == "2"  # The earlier one
    assert result["history"][1]["qty"] == "5"  # The later one


def test_resolve_item_empty_name():
    history = [
        {
            "name": "",
            "qty_txt": "10",
            "note": "",
            "date": "2023-10-01",
            "time": "10:00:00",
            "src": 0,
            "line": 1
        }
    ]
    result = resolve_item(1, "empty", history)
    assert result is None


def test_resolve_item_qty_and_status():
    # Unknown quantity
    history_unknown = [{"name": "Item1",
                        "qty_txt": "",
                        "note": "",
                        "date": "2023-10-01",
                        "time": "10:00:00",
                        "src": 0,
                        "line": 1}]
    res = resolve_item(1, "item1", history_unknown)
    assert res["countType"] == "unknown"
    assert res["qty"] is None
    assert res["status"] == "active"

    # Bulk quantity
    history_bulk = [{"name": "Item2",
                     "qty_txt": str(BULK_SENTINEL),
                     "note": "",
                     "date": "2023-10-01",
                     "time": "10:00:00",
                     "src": 0,
                     "line": 1}]
    res2 = resolve_item(2, "item2", history_bulk)
    assert res2["countType"] == "bulk"
    assert res2["qty"] is None
    assert res2["status"] == "active"
    assert res2["peak"] is None

    # Exact quantity gone
    history_gone = [{"name": "Item3",
                     "qty_txt": "0",
                     "note": "",
                     "date": "2023-10-01",
                     "time": "10:00:00",
                     "src": 0,
                     "line": 1}]
    res3 = resolve_item(3, "item3", history_gone)
    assert res3["countType"] == "exact"
    assert res3["qty"] == 0
    assert res3["status"] == "gone"


def test_resolve_item_peak():
    history = [
        {"name": "PeakItem",
         "qty_txt": "2",
         "note": "",
         "date": "2023-10-01",
         "time": "10:00:00",
         "src": 0,
         "line": 1},
        {"name": "PeakItem",
         "qty_txt": "15",
         "note": "",
         "date": "2023-10-02",
         "time": "10:00:00",
         "src": 0,
         "line": 2},
        {"name": "PeakItem",
         "qty_txt": "5",
         "note": "",
         "date": "2023-10-03",
         "time": "10:00:00",
         "src": 0,
         "line": 3}
    ]
    res = resolve_item(1, "peakitem", history)
    assert res["qty"] == 5
    assert res["peak"] == 15


def test_resolve_item_conflict_restated():
    # Restated
    history_restated = [
        {"name": "RestatedItem", "qty_txt": "5", "note": "",
            "date": "2023-10-01", "time": "10:00:00", "src": 0, "line": 1},
        {"name": "RestatedItem", "qty_txt": "5", "note": "",
            "date": "2023-10-02", "time": "10:00:00", "src": 0, "line": 2}
    ]
    res_restated = resolve_item(1, "restateditem", history_restated)
    assert res_restated["restated"] is True
    assert res_restated["conflict"] is False

    # Conflict
    history_conflict = [
        {"name": "ConflictItem", "qty_txt": "5", "note": "",
            "date": "2023-10-01", "time": "10:00:00", "src": 0, "line": 1},
        {"name": "ConflictItem", "qty_txt": "10", "note": "",
            "date": "2023-10-02", "time": "10:00:00", "src": 0, "line": 2}
    ]
    res_conflict = resolve_item(1, "conflictitem", history_conflict)
    assert res_conflict["restated"] is False
    assert res_conflict["conflict"] is True

    # Conflict overridden by deliberate recount source=1
    history_deliberate_src = [
        {"name": "ConflictItem", "qty_txt": "5", "note": "",
            "date": "2023-10-01", "time": "10:00:00", "src": 0, "line": 1},
        {"name": "ConflictItem", "qty_txt": "10", "note": "",
            "date": "2023-10-02", "time": "10:00:00", "src": 1, "line": 2}
    ]
    res_delib_src = resolve_item(1, "conflictitem", history_deliberate_src)
    assert res_delib_src["conflict"] is False

    # Conflict overridden by deliberate recount note
    history_deliberate_note = [
        {"name": "ConflictItem", "qty_txt": "5", "note": "",
            "date": "2023-10-01", "time": "10:00:00", "src": 0, "line": 1},
        {"name": "ConflictItem", "qty_txt": "10", "note": COUNTED_MARK,
            "date": "2023-10-02", "time": "10:00:00", "src": 0, "line": 2}
    ]
    res_delib_note = resolve_item(1, "conflictitem", history_deliberate_note)
    assert res_delib_note["conflict"] is False


def test_resolve_item_note_resolution():
    history = [
        {"name": "NoteItem", "qty_txt": "5", "note": "Old Note",
            "date": "2023-10-01", "time": "10:00:00", "src": 0, "line": 1},
        {"name": "NoteItem",
         "qty_txt": "5",
         "note": "",
         "date": "2023-10-02",
         "time": "10:00:00",
         "src": 0,
         "line": 2}
    ]
    res = resolve_item(1, "noteitem", history)
    assert res["note"] == "Old Note"


def test_build_items_basic():
    raw_rows = [
        # Box 2: "Arduino" (only 1 row)
        {"box": 2, "name": "Arduino", "qty_txt": "1", "note": "",
            "date": "2023-10-01", "time": "10:00:00", "src": 0, "line": 3},
        # Box 1: "Zener Diode" (will be sorted after "Resistor" in the same
        # box)
        {"box": 1, "name": "Zener Diode", "qty_txt": "20", "note": "",
            "date": "2023-10-01", "time": "10:00:00", "src": 0, "line": 4},
        # Box 1: "Resistor" (duplicate - newest wins)
        {"box": 1, "name": "Resistor", "qty_txt": "10", "note": "Old",
            "date": "2023-10-01", "time": "10:00:00", "src": 0, "line": 1},
        {"box": 1, "name": "Resistor", "qty_txt": "5", "note": "New",
            "date": "2023-10-02", "time": "10:00:00", "src": 0, "line": 2},
    ]

    items, _ = build_items(raw_rows)

    # Should sort by box then name: 1-Resistor, 1-Zener Diode, 2-Arduino
    assert len(items) == 3

    assert items[0]["box"] == 1
    assert items[0]["name"] == "Resistor"
    assert items[0]["qty"] == 5
    assert items[0]["note"] == "New"

    assert items[1]["box"] == 1
    assert items[1]["name"] == "Zener Diode"
    assert items[1]["qty"] == 20

    assert items[2]["box"] == 2
    assert items[2]["name"] == "Arduino"
    assert items[2]["qty"] == 1


def test_build_items_empty_ignored():
    raw_rows = [
        {"box": 1, "name": "Valid Item", "qty_txt": "1", "note": "",
            "date": "2023-10-01", "time": "10:00:00", "src": 0, "line": 1},
        {"box": 1, "name": "", "qty_txt": "5", "note": "Empty placeholder",
            "date": "2023-10-01", "time": "10:00:00", "src": 0, "line": 2},
    ]

    items, _ = build_items(raw_rows)

    assert len(items) == 1
    assert items[0]["name"] == "Valid Item"


def test_build_items_empty_input():
    items, _ = build_items([])
    assert items == []


def test_build_items_mocked(mocker):
    # Mock group_rows to return predefined out-of-order groups
    mock_group_rows = mocker.patch("build.group_rows")
    mock_group_rows.return_value = {
        (2, "b-slug"): [{"history": "b"}],
        (1, "a-slug"): [{"history": "a"}],
        (1, "c-slug"): [{"history": "c"}],  # Will be resolved as None
    }

    # Mock resolve_item to return items or None
    def side_effect_resolve_item(box, key_slug, history):
        if key_slug == "c-slug":
            return None
        return {"box": box, "name": key_slug,
                "slug": key_slug, "resolved": True}

    mock_resolve_item = mocker.patch(
        "build.resolve_item",
        side_effect=side_effect_resolve_item)

    # Call build_items with dummy raw rows
    raw_rows = [{"dummy": "row"}]
    items, _ = build_items(raw_rows)

    # Verify group_rows was called with raw_rows
    mock_group_rows.assert_called_once_with(raw_rows)

    # Verify resolve_item was called for each sorted group
    assert mock_resolve_item.call_count == 3
    mock_resolve_item.assert_any_call(1, "a-slug", [{"history": "a"}])
    mock_resolve_item.assert_any_call(1, "c-slug", [{"history": "c"}])
    mock_resolve_item.assert_any_call(2, "b-slug", [{"history": "b"}])

    # Verify the output list only contains non-None items in expected sorted
    # order
    assert len(items) == 2
    assert items[0] == {
        "box": 1,
        "name": "a-slug",
        "slug": "a-slug",
        "resolved": True}
    assert items[1] == {
        "box": 2,
        "name": "b-slug",
        "slug": "b-slug",
        "resolved": True}


def test_resolve_item_id_fallback():
    history = [
        {"name": "NamelessItem", "qty_txt": "5", "note": "",
            "date": "2023-10-01", "time": "10:00:00", "src": 0, "line": 1}
    ]
    res = resolve_item(1, "", history)
    assert res["id"] == "1-item"


def test_resolve_item_complex_history():
    history = [
        {"name": "Resistor",
         "qty_txt": "10",
         "note": "",
         "date": "2023-01-01",
         "time": "10:00:00",
         "src": 0,
         "line": 1},
        {"name": "Resistor", "qty_txt": "5", "note": "used 5",
            "date": "2023-01-02", "time": "11:00:00", "src": 0, "line": 2},
        {"name": "Resistor", "qty_txt": "20", "note": COUNTED_MARK,
            "date": "2023-01-03", "time": "12:00:00", "src": 0, "line": 3},
        {"name": "Resistor", "qty_txt": "15", "note": "used 5",
            "date": "2023-01-04", "time": "13:00:00", "src": 0, "line": 4},
    ]
    # Scramble the order to test sorting logic
    history = [history[2], history[0], history[3], history[1]]

    result = resolve_item(1, "resistor", history)

    assert result["name"] == "Resistor"
    assert result["qty"] == 15
    assert result["peak"] == 20
    assert result["countType"] == "exact"
    assert result["status"] == "active"
    # distinct qtys > 1 and last is not deliberate
    assert result["conflict"] is True
    assert len(result["history"]) == 4
    # ensure sorted properly by dates
    assert result["history"][0]["qty"] == "10"
    assert result["history"][1]["qty"] == "5"
    assert result["history"][2]["qty"] == "20"
    assert result["history"][3]["qty"] == "15"


def test_group_rows_basic():
    raw_rows = [
        {"box": 1, "name": "Resistor", "qty_txt": "10"},
        {"box": 1, "name": "Resistor", "qty_txt": "5"},
        {"box": 2, "name": "Capacitor", "qty_txt": "2"},
    ]
    from build import group_rows
    groups = group_rows(raw_rows)
    assert len(groups) == 2

    assert (1, "resistor") in groups
    assert len(groups[(1, "resistor")]) == 2
    assert groups[(1, "resistor")][0]["qty_txt"] == "10"
    assert groups[(1, "resistor")][1]["qty_txt"] == "5"

    assert (2, "capacitor") in groups
    assert len(groups[(2, "capacitor")]) == 1


def test_group_rows_empty():
    from build import group_rows
    groups = group_rows([])
    assert groups == {}


def test_group_rows_slug_normalization():
    raw_rows = [
        {"box": 1, "name": "ESP32 Board", "qty_txt": "1"},
        {"box": 1, "name": "esp32 board", "qty_txt": "2"},
        {"box": 1, "name": "  ESP32   BOARD  ", "qty_txt": "3"},
    ]
    from build import group_rows
    groups = group_rows(raw_rows)
    assert len(groups) == 1

    key = (1, "esp32 board")
    assert key in groups
    assert len(groups[key]) == 3
    assert groups[key][0]["qty_txt"] == "1"
    assert groups[key][1]["qty_txt"] == "2"
    assert groups[key][2]["qty_txt"] == "3"


def test_group_rows_different_boxes():
    raw_rows = [
        {"box": 1, "name": "Arduino", "qty_txt": "1"},
        {"box": 2, "name": "Arduino", "qty_txt": "2"},
    ]
    from build import group_rows
    groups = group_rows(raw_rows)
    assert len(groups) == 2
    assert (1, "arduino") in groups
    assert (2, "arduino") in groups
