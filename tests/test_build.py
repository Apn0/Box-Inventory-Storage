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

def test_resolve_item_empty_name():
    history = [
        {"name": "", "qty_txt": "5", "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": ""}
    ]
    assert resolve_item(81, "empty-item", history) is None

def test_resolve_item_exact_quantity():
    history = [
        {"name": "Resistor", "qty_txt": "5", "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": ""}
    ]
    res = resolve_item(1, "resistor", history)
    assert res is not None
    assert res["countType"] == "exact"
    assert res["qty"] == 5
    assert res["peak"] == 5
    assert res["status"] == "active"
    assert res["conflict"] is False
    assert res["restated"] is False
    assert res["id"] == "1-resistor"

def test_resolve_item_zero_quantity():
    history = [
        {"name": "Capacitor", "qty_txt": "0", "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": ""}
    ]
    res = resolve_item(1, "capacitor", history)
    assert res is not None
    assert res["countType"] == "exact"
    assert res["qty"] == 0
    assert res["peak"] == 0
    assert res["status"] == "gone"

def test_resolve_item_unknown_quantity():
    history = [
        {"name": "Inductor", "qty_txt": "", "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": ""}
    ]
    res = resolve_item(1, "inductor", history)
    assert res is not None
    assert res["countType"] == "unknown"
    assert res["qty"] is None
    assert res["peak"] is None
    assert res["status"] == "active"

def test_resolve_item_bulk_quantity():
    history = [
        {"name": "LEDs", "qty_txt": str(BULK_SENTINEL), "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": ""}
    ]
    res = resolve_item(1, "leds", history)
    assert res is not None
    assert res["countType"] == "bulk"
    assert res["qty"] is None
    assert res["peak"] is None
    assert res["status"] == "active"

def test_resolve_item_multiple_history_restated():
    history = [
        {"name": "Wire", "qty_txt": "10", "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": ""},
        {"name": "Wire", "qty_txt": "10", "date": "2023-01-02", "time": "12:00:00", "src": 0, "line": 2, "note": ""}
    ]
    res = resolve_item(1, "wire", history)
    assert res is not None
    assert res["restated"] is True
    assert res["conflict"] is False
    assert len(res["history"]) == 2

def test_resolve_item_multiple_history_conflict():
    history = [
        {"name": "Wire", "qty_txt": "10", "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": ""},
        {"name": "Wire", "qty_txt": "5", "date": "2023-01-02", "time": "12:00:00", "src": 0, "line": 2, "note": ""}
    ]
    res = resolve_item(1, "wire", history)
    assert res is not None
    assert res["restated"] is False
    assert res["conflict"] is True
    assert len(res["history"]) == 2
    assert res["qty"] == 5

def test_resolve_item_multiple_history_deliberate_src():
    history = [
        {"name": "Wire", "qty_txt": "10", "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": ""},
        {"name": "Wire", "qty_txt": "5", "date": "2023-01-02", "time": "12:00:00", "src": 1, "line": 2, "note": ""}
    ]
    res = resolve_item(1, "wire", history)
    assert res is not None
    assert res["conflict"] is False
    assert res["qty"] == 5

def test_resolve_item_multiple_history_deliberate_note():
    history = [
        {"name": "Wire", "qty_txt": "10", "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": ""},
        {"name": "Wire", "qty_txt": "5", "date": "2023-01-02", "time": "12:00:00", "src": 0, "line": 2, "note": COUNTED_MARK}
    ]
    res = resolve_item(1, "wire", history)
    assert res is not None
    assert res["conflict"] is False
    assert res["qty"] == 5

def test_resolve_item_peak_calculation():
    history = [
        {"name": "Screws", "qty_txt": "2", "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": ""},
        {"name": "Screws", "qty_txt": "10", "date": "2023-01-02", "time": "12:00:00", "src": 0, "line": 2, "note": ""},
        {"name": "Screws", "qty_txt": "5", "date": "2023-01-03", "time": "12:00:00", "src": 0, "line": 3, "note": ""}
    ]
    res = resolve_item(1, "screws", history)
    assert res is not None
    assert res["qty"] == 5
    assert res["peak"] == 10

def test_resolve_item_note_fallback():
    history = [
        {"name": "Nuts", "qty_txt": "10", "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": "Original note"},
        {"name": "Nuts", "qty_txt": "5", "date": "2023-01-02", "time": "12:00:00", "src": 0, "line": 2, "note": ""}
    ]
    res = resolve_item(1, "nuts", history)
    assert res is not None
    assert res["note"] == "Original note"

def test_resolve_item_sorting():
    history = [
        {"name": "Nuts", "qty_txt": "5", "date": "2023-01-02", "time": "12:00:00", "src": 0, "line": 2, "note": ""},
        {"name": "Nuts", "qty_txt": "10", "date": "2023-01-01", "time": "12:00:00", "src": 0, "line": 1, "note": "Original note"}
    ]
    # resolve_item sorts the input list in-place
    res = resolve_item(1, "nuts", history)
    assert res is not None
    assert res["qty"] == 5
    assert res["note"] == "Original note"
    assert history[0]["qty_txt"] == "10"
    assert history[-1]["qty_txt"] == "5"
