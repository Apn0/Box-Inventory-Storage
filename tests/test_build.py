import pytest
from build import parse_date

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
import unittest
from build import categorise, DEFAULT_CATEGORY

class TestCategorise(unittest.TestCase):
    def test_specific_categories(self):
        # mcu
        self.assertEqual(categorise("esp32", ""), "mcu")
        # sensor
        self.assertEqual(categorise("mq gas sensor", ""), "sensor")
        # power
        self.assertEqual(categorise("fast-charge module", ""), "power")
        # driver
        self.assertEqual(categorise("motor driver board", ""), "driver")

    def test_default_category(self):
        self.assertEqual(categorise("unknown widget", ""), DEFAULT_CATEGORY)
        self.assertEqual(categorise("foo", "bar"), DEFAULT_CATEGORY)

    def test_case_insensitivity(self):
        self.assertEqual(categorise("ESP32", ""), "mcu")
        self.assertEqual(categorise("Mq GaS", ""), "sensor")
        self.assertEqual(categorise("CHARGER", ""), "power")

    def test_matching_in_note(self):
        self.assertEqual(categorise("unknown item", "contains an esp32"), "mcu")
        self.assertEqual(categorise("random board", "this is a charger"), "power")

    def test_first_match_wins(self):
        # "mcu" comes before "power" in CATEGORY_RULES
        # so "esp32 charger" should match "mcu"
        self.assertEqual(categorise("esp32 charger", ""), "mcu")

        # "sensor" comes before "driver"
        self.assertEqual(categorise("gps motor driver", ""), "sensor")

    def test_regex_boundaries(self):
        # \bmcu\b shouldn't match "amcu" or "mcux"
        self.assertEqual(categorise("amcu", ""), DEFAULT_CATEGORY)
        self.assertEqual(categorise("mcux", ""), DEFAULT_CATEGORY)
        self.assertEqual(categorise("an mcu board", ""), "mcu")


from build import build_items

class TestBuildItems(unittest.TestCase):
    def _make_row(self, **kwargs):
        """Helper to create a default row for build_items input."""
        row = {
            "box": 1,
            "name": "Test Item",
            "qty_txt": "1",
            "note": "",
            "date": "2023-01-01",
            "time": "12:00:00",
            "src": 0,
            "line": 1
        }
        row.update(kwargs)
        return row

    def test_newest_row_wins(self):
        """Test that the newest row is selected based on date/time."""
        rows = [
            self._make_row(date="2023-01-01", time="12:00:00", note="old note"),
            self._make_row(date="2023-01-02", time="10:00:00", note="new note"),
        ]
        items = build_items(rows)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["note"], "new note")

        # Check reverse order
        rows = [
            self._make_row(date="2023-01-02", time="10:00:00", note="new note"),
            self._make_row(date="2023-01-01", time="12:00:00", note="old note"),
        ]
        items = build_items(rows)
        self.assertEqual(items[0]["note"], "new note")

    def test_conflict_resolution_restated(self):
        """Two rows with same quantity are not a conflict, just restated."""
        rows = [
            self._make_row(date="2023-01-01", qty_txt="5"),
            self._make_row(date="2023-01-02", qty_txt="5"),
        ]
        items = build_items(rows)
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]["restated"])
        self.assertFalse(items[0]["conflict"])

    def test_conflict_resolution_conflict(self):
        """Two rows with different quantity are a conflict."""
        rows = [
            self._make_row(date="2023-01-01", qty_txt="5"),
            self._make_row(date="2023-01-02", qty_txt="3"),
        ]
        items = build_items(rows)
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["restated"])
        self.assertTrue(items[0]["conflict"])

    def test_conflict_resolution_deliberate_src(self):
        """If the latest row has src=1, it is a deliberate recount, no conflict."""
        rows = [
            self._make_row(date="2023-01-01", qty_txt="5", src=0),
            self._make_row(date="2023-01-02", qty_txt="3", src=1),
        ]
        items = build_items(rows)
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["conflict"])

    def test_conflict_resolution_deliberate_note(self):
        """If the latest row has photo-counted note, it is deliberate, no conflict."""
        rows = [
            self._make_row(date="2023-01-01", qty_txt="5", note=""),
            self._make_row(date="2023-01-02", qty_txt="3", note="verified photo-counted today"),
        ]
        items = build_items(rows)
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["conflict"])

    def test_peak_calculation(self):
        """Peak should track the maximum exact quantity."""
        from build import BULK_SENTINEL
        rows = [
            self._make_row(date="2023-01-01", qty_txt="10"),
            self._make_row(date="2023-01-02", qty_txt="2"),
            self._make_row(date="2023-01-03", qty_txt=str(BULK_SENTINEL)), # should be ignored
        ]
        items = build_items(rows)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["peak"], 10)
        self.assertEqual(items[0]["qty"], None)
        self.assertEqual(items[0]["countType"], "bulk")

if __name__ == "__main__":
    unittest.main()
