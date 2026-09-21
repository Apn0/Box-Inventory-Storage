import pytest
from build import parse_date, find_split_items, container_of, part_numbers, categorise, find_free_boxes

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

def test_find_free_boxes_empty():
    assert find_free_boxes([]) == []

def test_find_free_boxes_no_free():
    items = [
        {"box": 1, "status": "active"},
        {"box": 2, "status": "active"},
        {"box": 3, "status": "active"},
    ]
    assert find_free_boxes(items) == []

def test_find_free_boxes_emptied():
    items = [
        {"box": 1, "status": "active"},
        {"box": 2, "status": "depleted"},
    ]
    free_boxes = find_free_boxes(items)
    assert len(free_boxes) == 1
    assert free_boxes[0] == {"box": 2, "container": "1", "reason": "emptied"}

def test_find_free_boxes_never_used():
    items = [
        {"box": 1, "status": "active"},
        {"box": 3, "status": "active"},
    ]
    free_boxes = find_free_boxes(items)
    assert len(free_boxes) == 1
    assert free_boxes[0] == {"box": 2, "container": "1", "reason": "never used"}

def test_find_free_boxes_high_range():
    items = [
        {"box": 400, "status": "active"},
        {"box": 402, "status": "depleted"},
    ]
    free_boxes = find_free_boxes(items)
    assert len(free_boxes) == 2
    assert free_boxes[0] == {"box": 401, "container": "H1", "reason": "never used"}
    assert free_boxes[1] == {"box": 402, "container": "H1", "reason": "emptied"}

def test_find_free_boxes_high_range_emptied():
    items = [
        {"box": 400, "status": "active"},
        {"box": 401, "status": "depleted"},
    ]
    free_boxes = find_free_boxes(items)
    assert len(free_boxes) == 1
    assert free_boxes[0] == {"box": 401, "container": "H1", "reason": "emptied"}

def test_find_free_boxes_mixed():
    items = [
        {"box": 1, "status": "active"},
        {"box": 3, "status": "depleted"},
        {"box": 400, "status": "active"},
        {"box": 402, "status": "depleted"},
    ]
    free_boxes = find_free_boxes(items)
    assert len(free_boxes) == 4
    # Check that they match the right details
    assert {"box": 2, "container": "1", "reason": "never used"} in free_boxes
    assert {"box": 3, "container": "1", "reason": "emptied"} in free_boxes
    assert {"box": 401, "container": "H1", "reason": "never used"} in free_boxes
    assert {"box": 402, "container": "H1", "reason": "emptied"} in free_boxes
