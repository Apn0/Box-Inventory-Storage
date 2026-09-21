import pytest
from build import parse_date, find_split_items, container_of, part_numbers, categorise, resolve_item, BULK_SENTINEL, COUNTED_MARK

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
    ("hc-sr04", {"sr04"}), # 'hc' is discarded, 'sr04' matches
    ("neo-6m gps", set()), # slug turns it into 'neo 6m gps'. 'neo' has no digits, '6m' lacks 2+ letters
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
    ("module", set()), # no digits
    ("sensor", set()), # no digits
    ("v2", set()), # only 1 letter
    ("m3", set()), # only 1 letter
    ("42", set()), # bare run of digits but less than 4 digits
    ("123", set()), # bare run of digits but less than 4 digits
    ("esp3", set()), # only 1 digit, requires 2+ digits according to actual regex
    ("", set()), # empty string
    ("   ", set()), # whitespace
])
def test_part_numbers(name, expected):
    """Test extracting part numbers from a string.
    Expects 2+ letters followed by 2+ digits, or a bare run of 4+ digits.
    """
    assert part_numbers(name) == expected

@pytest.mark.parametrize("name, note, expected", [
    # Basic matches
    ("ESP32", "", "mcu"),
    ("Capacitor", "10uF", "misc"), # Default category
    ("LED", "Red", "display"), # Case insensitive match

    # Matching in note vs name
    ("Unknown item", "Use as an mcu", "mcu"),
    ("stepper motor", "broken", "motor"),
    ("broken item", "stepper motor", "motor"),

    # Word boundaries (\b)
    ("mcu", "", "mcu"),
    ("mcus", "", "misc"), # Should not match \bmcu\b
    ("fan", "", "motor"), # \bfan\b
    ("fancy", "", "misc"), # Should not match
    ("adc", "", "interface"), # \badc\b
    ("adcs", "", "misc"),

    # Precedence (first matching rule wins)
    ("esp32", "with gps", "mcu"), # "mcu" comes before "sensor" (gps)
    ("gps", "with esp32", "mcu"), # even if gps is in name, esp32 matches the 'mcu' rule which is checked first

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

from build import build_items

def test_build_items_happy_path():
    raw_rows = [
        {"line": 2, "box": 2, "name": "Resistor", "qty_txt": "10", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0},
        {"line": 3, "box": 1, "name": "Capacitor", "qty_txt": "5", "note": "", "date": "2023-01-02", "time": "12:00", "src": 0},
    ]
    items = build_items(raw_rows)
    assert len(items) == 2
    # Should be sorted by box, then slug (1: Capacitor, then 2: Resistor)
    assert items[0]["box"] == 1
    assert items[0]["name"] == "Capacitor"
    assert items[1]["box"] == 2
    assert items[1]["name"] == "Resistor"

def test_build_items_grouping():
    raw_rows = [
        {"line": 2, "box": 1, "name": "Resistor", "qty_txt": "10", "note": "Old", "date": "2023-01-01", "time": "12:00", "src": 0},
        {"line": 3, "box": 1, "name": "resistor", "qty_txt": "15", "note": "New", "date": "2023-01-02", "time": "12:00", "src": 0},
        {"line": 4, "box": 2, "name": "Capacitor", "qty_txt": "5", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0},
    ]
    items = build_items(raw_rows)
    assert len(items) == 2

    resistors = [i for i in items if i["box"] == 1]
    assert len(resistors) == 1
    assert resistors[0]["qty"] == 15
    assert resistors[0]["note"] == "New"
    assert len(resistors[0]["history"]) == 2

def test_build_items_resolving_returns_none():
    raw_rows = [
        {"line": 2, "box": 1, "name": "Resistor", "qty_txt": "10", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0},
        {"line": 3, "box": 81, "name": "", "qty_txt": "", "note": "Empty Box", "date": "2023-01-01", "time": "12:00", "src": 0},
    ]
    items = build_items(raw_rows)
    # Box 81 with no name should be filtered out
    assert len(items) == 1
    assert items[0]["box"] == 1
    assert items[0]["name"] == "Resistor"

def test_build_items_sorting_by_box_and_slug():
    raw_rows = [
        {"line": 2, "box": 2, "name": "Zener Diode", "qty_txt": "1", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0},
        {"line": 3, "box": 2, "name": "Apple", "qty_txt": "1", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0},
        {"line": 4, "box": 1, "name": "Banana", "qty_txt": "1", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0},
    ]
    items = build_items(raw_rows)
    assert len(items) == 3
    # Order should be Box 1 Banana, Box 2 Apple, Box 2 Zener Diode
    assert items[0]["box"] == 1
    assert items[0]["name"] == "Banana"

    assert items[1]["box"] == 2
    assert items[1]["name"] == "Apple"

    assert items[2]["box"] == 2
    assert items[2]["name"] == "Zener Diode"


# Tests for resolve_item

def test_resolve_item_basic():
    history = [
        {"name": "Resistor", "qty_txt": "10", "note": "10k", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2}
    ]
    item = resolve_item(1, "resistor", history)
    assert item is not None
    assert item["id"] == "1-resistor"
    assert item["box"] == 1
    assert item["name"] == "Resistor"
    assert item["qty"] == 10
    assert item["peak"] == 10
    assert item["countType"] == "exact"
    assert item["status"] == "active"
    assert item["note"] == "10k"
    assert item["conflict"] is False
    assert item["restated"] is False
    assert item["history"] == []

def test_resolve_item_empty_name():
    history = [
        {"name": "", "qty_txt": "", "note": "Empty", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2}
    ]
    assert resolve_item(81, "item", history) is None

def test_resolve_item_sorting():
    history = [
        {"name": "Resistor", "qty_txt": "5", "note": "Old", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2},
        {"name": "Resistor", "qty_txt": "15", "note": "New", "date": "2023-01-02", "time": "12:00", "src": 0, "line": 3},
        {"name": "Resistor", "qty_txt": "10", "note": "Mid", "date": "2023-01-01", "time": "13:00", "src": 0, "line": 4},
    ]
    item = resolve_item(1, "resistor", history)
    assert item is not None
    assert item["qty"] == 15
    assert item["note"] == "New"
    assert item["peak"] == 15

def test_resolve_item_quantities_and_status():
    # Exact > 0
    history = [{"name": "R", "qty_txt": "1", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2}]
    item = resolve_item(1, "r", history)
    assert item["qty"] == 1
    assert item["status"] == "active"
    assert item["countType"] == "exact"

    # Exact 0
    history = [{"name": "R", "qty_txt": "0", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2}]
    item = resolve_item(1, "r", history)
    assert item["qty"] == 0
    assert item["status"] == "gone"
    assert item["countType"] == "exact"

    # Empty quantity
    history = [{"name": "R", "qty_txt": "", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2}]
    item = resolve_item(1, "r", history)
    assert item["qty"] is None
    assert item["status"] == "active"
    assert item["countType"] == "unknown"

    # Bulk quantity
    history = [{"name": "R", "qty_txt": str(BULK_SENTINEL), "note": "", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2}]
    item = resolve_item(1, "r", history)
    assert item["qty"] is None
    assert item["status"] == "active"
    assert item["countType"] == "bulk"

def test_resolve_item_peak_tracking():
    history = [
        {"name": "R", "qty_txt": "5", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2},
        {"name": "R", "qty_txt": str(BULK_SENTINEL), "note": "", "date": "2023-01-02", "time": "12:00", "src": 0, "line": 3},
        {"name": "R", "qty_txt": "2", "note": "", "date": "2023-01-03", "time": "12:00", "src": 0, "line": 4},
        {"name": "R", "qty_txt": "10", "note": "", "date": "2023-01-04", "time": "12:00", "src": 0, "line": 5},
    ]
    item = resolve_item(1, "r", history)
    assert item["peak"] == 10
    assert item["qty"] == 10

def test_resolve_item_conflict_and_restated():
    # Conflict: >1 entry, different quantities
    history = [
        {"name": "R", "qty_txt": "5", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2},
        {"name": "R", "qty_txt": "10", "note": "", "date": "2023-01-02", "time": "12:00", "src": 0, "line": 3},
    ]
    item = resolve_item(1, "r", history)
    assert item["conflict"] is True
    assert item["restated"] is False

    # Restated: >1 entry, same quantities
    history = [
        {"name": "R", "qty_txt": "5", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2},
        {"name": "R", "qty_txt": "5", "note": "", "date": "2023-01-02", "time": "12:00", "src": 0, "line": 3},
    ]
    item = resolve_item(1, "r", history)
    assert item["conflict"] is False
    assert item["restated"] is True

    # Deliberate conflict (src = 1)
    history = [
        {"name": "R", "qty_txt": "5", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2},
        {"name": "R", "qty_txt": "10", "note": "", "date": "2023-01-02", "time": "12:00", "src": 1, "line": 3},
    ]
    item = resolve_item(1, "r", history)
    assert item["conflict"] is False
    assert item["restated"] is False

    # Deliberate conflict (COUNTED_MARK in note)
    history = [
        {"name": "R", "qty_txt": "5", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2},
        {"name": "R", "qty_txt": "10", "note": f"abc {COUNTED_MARK} xyz", "date": "2023-01-02", "time": "12:00", "src": 0, "line": 3},
    ]
    item = resolve_item(1, "r", history)
    assert item["conflict"] is False
    assert item["restated"] is False

def test_resolve_item_note_fallback():
    history = [
        {"name": "R", "qty_txt": "5", "note": "First", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2},
        {"name": "R", "qty_txt": "10", "note": "", "date": "2023-01-02", "time": "12:00", "src": 0, "line": 3},
    ]
    item = resolve_item(1, "r", history)
    assert item["note"] == "First"

    # Note from latest is non-empty, use that instead
    history = [
        {"name": "R", "qty_txt": "5", "note": "First", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2},
        {"name": "R", "qty_txt": "10", "note": "Second", "date": "2023-01-02", "time": "12:00", "src": 0, "line": 3},
    ]
    item = resolve_item(1, "r", history)
    assert item["note"] == "Second"

    # All notes empty
    history = [
        {"name": "R", "qty_txt": "5", "note": "", "date": "2023-01-01", "time": "12:00", "src": 0, "line": 2},
        {"name": "R", "qty_txt": "10", "note": "", "date": "2023-01-02", "time": "12:00", "src": 0, "line": 3},
    ]
    item = resolve_item(1, "r", history)
    assert item["note"] == ""
