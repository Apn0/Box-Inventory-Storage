import unittest
from identify import find_existing

class TestFindExisting(unittest.TestCase):
    def setUp(self):
        self.data = {
            "items": [
                {"name": "TMC2209 stepper driver", "status": "active", "box": 1},
                {"name": "ATMEGA328P microcontroller", "status": "inactive", "box": 2},
                {"name": "ADS1115 ADC", "status": "active", "box": 3},
                {"name": "18650 battery holder", "status": "active", "box": 4},
                {"name": "18650 battery", "status": "active", "box": 5},
                {"name": "Generic resistor", "status": "active", "box": 6},
                {"name": "ESP32-WROOM-32", "status": "active", "box": 7},
            ]
        }

    def test_exact_match(self):
        # Exact string match
        result = find_existing(self.data, "TMC2209 stepper driver")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 1)

    def test_normalized_exact_match(self):
        # Case insensitive and special characters should still match exactly
        result = find_existing(self.data, "tmc2209-stepper-driver!")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 1)

    def test_part_number_match(self):
        # Match based on part number when exact match fails
        result = find_existing(self.data, "TMC2209-LA stepper driver module")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 1)

        # Another part number match
        result = find_existing(self.data, "ADS1115 breakout board")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 3)

    def test_ambiguous_part_number(self):
        # '18650' matches both '18650 battery holder' and '18650 battery'
        result = find_existing(self.data, "18650 lithium cell")
        self.assertIsNone(result)

    def test_inactive_item_ignored(self):
        # ATMEGA328P microcontroller is inactive, so exact match should return None
        result = find_existing(self.data, "ATMEGA328P microcontroller")
        self.assertIsNone(result)

        # Part number match on inactive item should also return None.
        result = find_existing(self.data, "ATMEGA328P dev board")
        self.assertIsNone(result)

    def test_no_match(self):
        # Completely unknown part
        result = find_existing(self.data, "NE555 timer IC")
        self.assertIsNone(result)

    def test_no_part_number_no_exact_match(self):
        # Generic word match but no exact match and no part numbers
        result = find_existing(self.data, "resistor pack")
        self.assertIsNone(result)

if __name__ == "__main__":
    unittest.main()
