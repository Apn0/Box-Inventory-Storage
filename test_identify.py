import unittest
from identify import find_existing, suggest_box

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
        active = [i for i in self.data["items"] if i["status"] == "active"]
        result = find_existing(active, "TMC2209 stepper driver")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 1)

    def test_normalized_exact_match(self):
        # Case insensitive and special characters should still match exactly
        active = [i for i in self.data["items"] if i["status"] == "active"]
        result = find_existing(active, "tmc2209-stepper-driver!")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 1)

    def test_part_number_match(self):
        # Match based on part number when exact match fails
        active = [i for i in self.data["items"] if i["status"] == "active"]
        result = find_existing(active, "TMC2209-LA stepper driver module")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 1)

        # Another part number match
        active = [i for i in self.data["items"] if i["status"] == "active"]
        result = find_existing(active, "ADS1115 breakout board")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 3)

    def test_ambiguous_part_number(self):
        # '18650' matches both '18650 battery holder' and '18650 battery'
        active = [i for i in self.data["items"] if i["status"] == "active"]
        result = find_existing(active, "18650 lithium cell")
        self.assertIsNone(result)

    def test_inactive_item_ignored(self):
        # ATMEGA328P microcontroller is inactive, so exact match should return None
        active = [i for i in self.data["items"] if i["status"] == "active"]
        result = find_existing(active, "ATMEGA328P microcontroller")
        self.assertIsNone(result)

        # Part number match on inactive item should also return None.
        active = [i for i in self.data["items"] if i["status"] == "active"]
        result = find_existing(active, "ATMEGA328P dev board")
        self.assertIsNone(result)

    def test_no_match(self):
        # Completely unknown part
        active = [i for i in self.data["items"] if i["status"] == "active"]
        result = find_existing(active, "NE555 timer IC")
        self.assertIsNone(result)

    def test_no_part_number_no_exact_match(self):
        # Generic word match but no exact match and no part numbers
        active = [i for i in self.data["items"] if i["status"] == "active"]
        result = find_existing(active, "resistor pack")
        self.assertIsNone(result)


class TestSuggestBox(unittest.TestCase):
    def test_existing_box_with_room(self):
        # A box of the same category with < MAX_BOX_ITEMS (6)
        data = {"freeBoxes": [{"box": 100, "reason": "empty"}]}
        active = [
            {"box": 1, "category": "resistor"},
            {"box": 2, "category": "capacitor"},
            {"box": 2, "category": "capacitor"},
        ]

        box, why = suggest_box(data, active, "capacitor")
        self.assertEqual(box, 2)
        self.assertIn("already holds capacitor", why)

    def test_existing_box_but_full(self):
        # A box of the same category with exactly MAX_BOX_ITEMS (6)
        data = {"freeBoxes": [{"box": 100, "reason": "empty"}]}
        active = [
            {"box": 2, "category": "capacitor"} for _ in range(6)
        ]

        box, why = suggest_box(data, active, "capacitor")
        # Should fallback to free box 100
        self.assertEqual(box, 100)
        self.assertIn("box 100 is free", why)

    def test_no_existing_box_use_free_box(self):
        data = {"freeBoxes": [{"box": 42, "reason": "empty"}]}
        active = [
            {"box": 1, "category": "resistor"}
        ]

        box, why = suggest_box(data, active, "capacitor")
        self.assertEqual(box, 42)
        self.assertIn("box 42 is free", why)

    def test_no_existing_box_no_free_box(self):
        # Fallback to max + 1
        data = {"freeBoxes": []}
        active = [
            {"box": 10, "category": "resistor"}
        ]

        box, why = suggest_box(data, active, "capacitor")
        self.assertEqual(box, 11)
        self.assertIn("is a new number", why)

    def test_ignore_box_numbers_over_400(self):
        # Boxes >= 400 should not be suggested as existing, free, or used to calculate next
        data = {"freeBoxes": [{"box": 401, "reason": "empty"}]}
        active = [
            {"box": 400, "category": "capacitor"}, # existing but >= 400
            {"box": 10, "category": "resistor"},
        ]

        box, why = suggest_box(data, active, "capacitor")
        # Should ignore the existing box 400, and free box 401, so picks max + 1 = 11
        self.assertEqual(box, 11)
        self.assertIn("is a new number", why)

if __name__ == "__main__":
    unittest.main()
