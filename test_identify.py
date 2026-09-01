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


class TestDecide(unittest.TestCase):
    def setUp(self):
        from identify import decide
        self.decide = decide
        self.data = {
            "items": [
                {"name": "TMC2209 stepper driver", "status": "active", "box": 1, "countType": "exact", "qty": 5, "category": "ic"},
                {"name": "18650 battery holder", "status": "active", "box": 4, "countType": "bulk", "qty": "many", "category": "misc"},
                {"name": "Inactive Item", "status": "inactive", "box": 5, "countType": "exact", "qty": 2, "category": "misc"},
            ],
            "freeBoxes": [
                {"box": 2, "reason": "empty"},
                {"box": 3, "reason": "empty"}
            ]
        }

    def test_appended_row_exact(self):
        result = {
            "name": "TMC2209 stepper driver",
            "quantity": 2,
            "category": "ic",
            "matches_existing": ""
        }
        res = self.decide(self.data, result)
        self.assertTrue(res["existing"])
        self.assertEqual(res["box"], 1)
        self.assertEqual(res["name"], "TMC2209 stepper driver")
        self.assertEqual(res["quantity"], 7)  # 5 + 2
        self.assertEqual(res["from"], 5)
        self.assertEqual(res["to"], 7)
        self.assertIn("already in box 1", res["why"])

    def test_appended_row_bulk(self):
        result = {
            "name": "18650 battery holder",
            "quantity": 10,
            "category": "misc",
            "matches_existing": ""
        }
        res = self.decide(self.data, result)
        self.assertTrue(res["existing"])
        self.assertEqual(res["box"], 4)
        self.assertEqual(res["name"], "18650 battery holder")
        self.assertEqual(res["quantity"], "many")
        self.assertIsNone(res["from"])
        self.assertIsNone(res["to"])
        self.assertIn("already in box 4", res["why"])

    def test_new_row_same_category_existing_box(self):
        # Category "ic" already in box 1, which has room (<6 items)
        result = {
            "name": "New IC",
            "quantity": 3,
            "category": "ic",
            "matches_existing": ""
        }
        res = self.decide(self.data, result)
        self.assertFalse(res["existing"])
        self.assertEqual(res["box"], 1) # suggest_box picks box 1 due to same category
        self.assertEqual(res["name"], "New IC")
        self.assertEqual(res["quantity"], 3)
        self.assertIsNone(res["from"])
        self.assertEqual(res["to"], 3)
        self.assertIn("already holds ic parts and has room", res["why"])

    def test_new_row_free_box(self):
        result = {
            "name": "New Resistor",
            "quantity": 100,
            "category": "resistor",
            "matches_existing": ""
        }
        res = self.decide(self.data, result)
        self.assertFalse(res["existing"])
        self.assertEqual(res["box"], 2) # suggest_box picks first free box
        self.assertEqual(res["name"], "New Resistor")
        self.assertEqual(res["quantity"], 100)
        self.assertIsNone(res["from"])
        self.assertEqual(res["to"], 100)
        self.assertIn("box 2 is free", res["why"])

    def test_matches_existing(self):
        result = {
            "name": "Different name for TMC",
            "quantity": 3,
            "category": "ic",
            "matches_existing": "TMC2209 stepper driver"
        }
        res = self.decide(self.data, result)
        self.assertTrue(res["existing"])
        self.assertEqual(res["box"], 1)
        self.assertEqual(res["name"], "TMC2209 stepper driver")
        self.assertEqual(res["quantity"], 8) # 5 + 3
        self.assertEqual(res["from"], 5)
        self.assertEqual(res["to"], 8)

if __name__ == "__main__":
    unittest.main()
