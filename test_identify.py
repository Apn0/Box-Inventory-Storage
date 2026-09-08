import unittest
from identify import find_existing_part, auto_filable, _recoverable
from build import part_numbers as _part_numbers

class TestPartNumbers(unittest.TestCase):
    def test_letters_then_digits(self):
        # Must have at least 2 letters followed by at least 2 digits
        self.assertEqual(_part_numbers("tmc2209"), {"tmc2209"})
        self.assertEqual(_part_numbers("mt3608"), {"mt3608"})
        self.assertEqual(_part_numbers("esp32"), {"esp32"})
        self.assertEqual(_part_numbers("ads1115"), {"ads1115"})
        self.assertEqual(_part_numbers("ch340g"), {"ch340g"})

    def test_bare_digits(self):
        # Must have at least 4 digits
        self.assertEqual(_part_numbers("18650"), {"18650"})
        self.assertEqual(_part_numbers("4000"), {"4000"})
        self.assertEqual(_part_numbers("104"), set()) # too short
        self.assertEqual(_part_numbers("220"), set()) # too short

    def test_invalid_part_numbers(self):
        # Does not match plain words
        self.assertEqual(_part_numbers("module"), set())
        self.assertEqual(_part_numbers("sensor"), set())
        self.assertEqual(_part_numbers("board"), set())
        self.assertEqual(_part_numbers("a1"), set()) # too short letters and digits
        self.assertEqual(_part_numbers("ab1"), set()) # too short digits
        self.assertEqual(_part_numbers("a12"), set()) # too short letters

    def test_extracted_from_name(self):
        self.assertEqual(_part_numbers("TMC2209-LA stepper driver module"), {"tmc2209"})
        self.assertEqual(_part_numbers("ESP32 WROOM 32 dev board"), {"esp32"})
        self.assertEqual(_part_numbers("18650 battery holder"), {"18650"})
        self.assertEqual(_part_numbers("MT3608 DC-DC step-up (boost) converter module"), {"mt3608"})

class TestAutoFilable(unittest.TestCase):
    def setUp(self):
        self.default_plan = {"existing": True}
        self.default_result = {
            "confidence": "high",
            "name": "resistor",
            "note": "10k ohm",
            "quantity": 5
        }

    def test_confidence_not_high(self):
        result = self.default_result.copy()
        result["confidence"] = "medium"
        self.assertEqual(auto_filable(result, self.default_plan), "medium confidence")

        result["confidence"] = "low"
        self.assertEqual(auto_filable(result, self.default_plan), "low confidence")

        result.pop("confidence")
        self.assertEqual(auto_filable(result, self.default_plan), "unknown confidence")

    def test_unsure_name(self):
        result = self.default_result.copy()
        result["name"] = "unidentified object"
        self.assertEqual(auto_filable(result, self.default_plan), "the model could not identify it")

        result["name"] = "not a component"
        self.assertEqual(auto_filable(result, self.default_plan), "the model could not identify it")

    def test_unsure_note(self):
        result = self.default_result.copy()
        result["note"] = "too dark to see"
        self.assertEqual(auto_filable(result, self.default_plan), "the model could not identify it")

        result["note"] = "blurry image"
        self.assertEqual(auto_filable(result, self.default_plan), "the model could not identify it")

    def test_quantity_zero_or_none(self):
        result = self.default_result.copy()
        result["quantity"] = 0
        self.assertEqual(auto_filable(result, self.default_plan), "nothing countable in the photo")

        result["quantity"] = -1
        self.assertEqual(auto_filable(result, self.default_plan), "nothing countable in the photo")

        result["quantity"] = None
        self.assertEqual(auto_filable(result, self.default_plan), "nothing countable in the photo")

        result.pop("quantity")
        self.assertEqual(auto_filable(result, self.default_plan), "nothing countable in the photo")

    def test_not_existing(self):
        plan = {"existing": False}
        self.assertEqual(auto_filable(self.default_result, plan), "new item, requires visual check")

    def test_auto_filable_success(self):
        self.assertIsNone(auto_filable(self.default_result, self.default_plan))

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
        self.active_items = [i for i in self.data["items"] if i["status"] == "active"]

    def test_exact_match(self):
        # Exact string match
        result = find_existing_part(self.active_items, "TMC2209 stepper driver")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 1)

    def test_normalized_exact_match(self):
        # Case insensitive and special characters should still match exactly
        result = find_existing_part(self.active_items, "tmc2209-stepper-driver!")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 1)

    def test_part_number_match(self):
        # Match based on part number when exact match fails
        result = find_existing_part(self.active_items, "TMC2209-LA stepper driver module")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 1)

        # Another part number match
        result = find_existing_part(self.active_items, "ADS1115 breakout board")
        self.assertIsNotNone(result)
        self.assertEqual(result["box"], 3)

    def test_ambiguous_part_number(self):
        # '18650' matches both '18650 battery holder' and '18650 battery'
        result = find_existing_part(self.active_items, "18650 lithium cell")
        self.assertIsNone(result)

    def test_inactive_item_ignored(self):
        # ATMEGA328P microcontroller is inactive, so exact match should return None
        result = find_existing_part(self.active_items, "ATMEGA328P microcontroller")
        self.assertIsNone(result)

        # Part number match on inactive item should also return None.
        result = find_existing_part(self.active_items, "ATMEGA328P dev board")
        self.assertIsNone(result)

    def test_no_match(self):
        # Completely unknown part
        result = find_existing_part(self.active_items, "NE555 timer IC")
        self.assertIsNone(result)

    def test_no_part_number_no_exact_match(self):
        # Generic word match but no exact match and no part numbers
        result = find_existing_part(self.active_items, "resistor pack")
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
        res = self.decide(self.data, self.data["items"], result)
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
        res = self.decide(self.data, self.data["items"], result)
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
        res = self.decide(self.data, self.data["items"], result)
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
        res = self.decide(self.data, self.data["items"], result)
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
        res = self.decide(self.data, self.data["items"], result)
        self.assertTrue(res["existing"])
        self.assertEqual(res["box"], 1)
        self.assertEqual(res["name"], "TMC2209 stepper driver")
        self.assertEqual(res["quantity"], 8) # 5 + 3
        self.assertEqual(res["from"], 5)
        self.assertEqual(res["to"], 8)

class TestRecoverable(unittest.TestCase):
    def test_recoverable_exceptions(self):
        # Should return True for these exceptions
        self.assertTrue(_recoverable(Exception("Your credit balance is too low.")))
        self.assertTrue(_recoverable(Exception("The credits are depleted.")))
        self.assertTrue(_recoverable(Exception("Insufficient_quota error.")))
        self.assertTrue(_recoverable(Exception("Quota exceeded.")))
        self.assertTrue(_recoverable(Exception("Authentication failed.")))
        self.assertTrue(_recoverable(Exception("Permission denied.")))
        self.assertTrue(_recoverable(Exception("Unauthorized access.")))
        self.assertTrue(_recoverable(Exception("Billing issue.")))
        self.assertTrue(_recoverable(Exception("HTTP Error 401: Unauthorized")))
        self.assertTrue(_recoverable(Exception("Error 403 Forbidden")))
        self.assertTrue(_recoverable(Exception("Too Many Requests 429")))

    def test_non_recoverable_exceptions(self):
        # Should return False for these
        self.assertFalse(_recoverable(Exception("SyntaxError: invalid syntax")))
        self.assertFalse(_recoverable(Exception("ValueError: missing value")))
        self.assertFalse(_recoverable(Exception("Network timeout")))
        self.assertFalse(_recoverable(Exception("Unknown error occurred")))
        self.assertFalse(_recoverable(Exception("500 Internal Server Error")))
        self.assertFalse(_recoverable(Exception("404 Not Found")))
        self.assertFalse(_recoverable(Exception("Bad request 400")))

if __name__ == "__main__":
    unittest.main()
