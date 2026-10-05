import unittest
import tempfile
import json
from pathlib import Path
from unittest.mock import patch
from identify import find_existing_part, auto_filable, propose_box, part_numbers, _recoverable, context_for_prompt, save_pending, load_pending

class TestPartNumbers(unittest.TestCase):
    def test_letters_then_digits(self):
        # Must have at least 2 letters followed by at least 2 digits
        self.assertEqual(part_numbers("tmc2209"), {"tmc2209"})
        self.assertEqual(part_numbers("mt3608"), {"mt3608"})
        self.assertEqual(part_numbers("esp32"), {"esp32"})
        self.assertEqual(part_numbers("ads1115"), {"ads1115"})
        self.assertEqual(part_numbers("ch340g"), {"ch340g"})

    def test_bare_digits(self):
        # Must have at least 4 digits
        self.assertEqual(part_numbers("18650"), {"18650"})
        self.assertEqual(part_numbers("4000"), {"4000"})
        self.assertEqual(part_numbers("104"), set()) # too short
        self.assertEqual(part_numbers("220"), set()) # too short

    def test_invalidpart_numbers(self):
        # Does not match plain words
        self.assertEqual(part_numbers("module"), set())
        self.assertEqual(part_numbers("sensor"), set())
        self.assertEqual(part_numbers("board"), set())
        self.assertEqual(part_numbers("a1"), set()) # too short letters and digits
        self.assertEqual(part_numbers("ab1"), set()) # too short digits
        self.assertEqual(part_numbers("a12"), set()) # too short letters

    def test_extracted_from_name(self):
        self.assertEqual(part_numbers("TMC2209-LA stepper driver module"), {"tmc2209"})
        self.assertEqual(part_numbers("ESP32 WROOM 32 dev board"), {"esp32"})
        self.assertEqual(part_numbers("18650 battery holder"), {"18650"})
        self.assertEqual(part_numbers("MT3608 DC-DC step-up (boost) converter module"), {"mt3608"})

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
        import collections
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
        self.active = [i for i in self.data["items"] if i["status"] == "active"]
        self.per_box = {}
        self.category_boxes = collections.defaultdict(set)
        for i in self.active:
            b = i["box"]
            self.per_box[b] = self.per_box.get(b, 0) + 1
            if b < 400:
                self.category_boxes[i.get("category")].add(b)

    def test_appended_row_exact(self):
        result = {
            "name": "TMC2209 stepper driver",
            "quantity": 2,
            "category": "ic",
            "matches_existing": ""
        }
        res = self.decide(self.data, self.active, result, self.per_box, self.category_boxes)
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
        res = self.decide(self.data, self.active, result, self.per_box, self.category_boxes)
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
        res = self.decide(self.data, self.active, result, self.per_box, self.category_boxes)
        self.assertFalse(res["existing"])
        self.assertEqual(res["box"], 1) # propose_box picks box 1 due to same category
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
        res = self.decide(self.data, self.active, result, self.per_box, self.category_boxes)
        self.assertFalse(res["existing"])
        self.assertEqual(res["box"], 2) # propose_box picks first free box
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
        res = self.decide(self.data, self.active, result, self.per_box, self.category_boxes)
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


class TestContextForPrompt(unittest.TestCase):
    def test_typical_case(self):
        data = {
            "meta": {
                "categoryLabels": {
                    "ic": "Integrated Circuits",
                    "resistor": "Resistors"
                }
            }
        }
        active = [
            {"name": "TMC2209 stepper driver"},
            {"name": "10k resistor"}
        ]
        result = context_for_prompt(data, active)

        self.assertIn("Category keys you must choose from: ic (Integrated Circuits), resistor (Resistors).", result)
        self.assertIn("- 10k resistor", result)
        self.assertIn("- TMC2209 stepper driver", result)
        # Checking sort order
        expected_parts = "- 10k resistor\n- TMC2209 stepper driver"
        self.assertIn(expected_parts, result)

    def test_duplicates_deduplicated_and_sorted(self):
        data = {
            "meta": {
                "categoryLabels": {
                    "misc": "Miscellaneous"
                }
            }
        }
        active = [
            {"name": "Z-diode"},
            {"name": "Z-diode"},
            {"name": "A-diode"},
            {"name": "A-diode"}
        ]
        result = context_for_prompt(data, active)

        expected_parts = "- A-diode\n- Z-diode"
        self.assertIn(expected_parts, result)
        self.assertEqual(result.count("A-diode"), 1)
        self.assertEqual(result.count("Z-diode"), 1)

    def test_empty_active_list(self):
        data = {
            "meta": {
                "categoryLabels": {
                    "misc": "Miscellaneous"
                }
            }
        }
        active = []
        result = context_for_prompt(data, active)

        self.assertIn("Category keys you must choose from: misc (Miscellaneous).", result)
        self.assertTrue(result.endswith("Parts already in the inventory (reuse the exact name if it is the same part):\n"))

    def test_empty_categories(self):
        data = {
            "meta": {
                "categoryLabels": {}
            }
        }
        active = [
            {"name": "Part A"}
        ]
        result = context_for_prompt(data, active)

        self.assertIn("Category keys you must choose from: .", result)
        self.assertIn("- Part A", result)

    def test_missing_category_labels(self):
        # Even if categoryLabels is missing, we simulate what would happen
        # assuming the caller provided the correct dictionary structure, but
        # let's assume the dictionary is malformed (key error should raise)
        data = {
            "meta": {}
        }
        active = [
            {"name": "Part A"}
        ]
        with self.assertRaises(KeyError):
            context_for_prompt(data, active)

    def test_special_characters_in_names(self):
        data = {
            "meta": {
                "categoryLabels": {
                    "ic": "Integrated Circuits"
                }
            }
        }
        active = [
            {"name": "IC-123!@#"},
            {"name": "µController"}
        ]
        result = context_for_prompt(data, active)

        self.assertIn("- IC-123!@#", result)
        self.assertIn("- µController", result)
        expected_parts = "- IC-123!@#\n- µController"
        self.assertIn(expected_parts, result)

class TestContextForPromptAdditional(unittest.TestCase):
    def test_unicode_category_labels(self):
        data = {
            "meta": {
                "categoryLabels": {
                    "μcu": "Microcontrollers 🚀",
                    "led": "LEDs & Lights ✨"
                }
            }
        }
        active = [
            {"name": "ESP32 🧠"}
        ]
        result = context_for_prompt(data, active)
        self.assertIn("μcu (Microcontrollers 🚀)", result)
        self.assertIn("led (LEDs & Lights ✨)", result)
        self.assertIn("- ESP32 🧠", result)

    def test_missing_name_in_active(self):
        data = {
            "meta": {
                "categoryLabels": {
                    "misc": "Misc"
                }
            }
        }
        active = [
            {"not_name": "Something"}
        ]
        with self.assertRaises(KeyError):
            context_for_prompt(data, active)

class TestPendingState(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name) / "pending.json"

        # Reset the global cache before each test to ensure a clean state
        import identify
        identify._pending_cache = None

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_save_and_load_pending(self):
        entries = [{"box": "1", "name": "Resistor", "qty": "10", "note": ""}]

        with patch("identify.PENDING", self.temp_path):
            save_pending(entries)

            # Verify file was written
            self.assertTrue(self.temp_path.exists())
            written_data = json.loads(self.temp_path.read_text(encoding="utf-8"))
            self.assertEqual(written_data, entries)

            # Clear cache to force a disk read
            import identify
            identify._pending_cache = None

            loaded_entries = load_pending()
            self.assertEqual(loaded_entries, entries)

            # Verify cache is populated
            self.assertEqual(identify._pending_cache, entries)

            # Verify cache is used (delete file, should still return cached data)
            self.temp_path.unlink()
            cached_entries = load_pending()
            self.assertEqual(cached_entries, entries)

    def test_load_pending_empty(self):
        with patch("identify.PENDING", self.temp_path):
            # File does not exist yet
            self.assertFalse(self.temp_path.exists())
            loaded_entries = load_pending()
            self.assertEqual(loaded_entries, [])

    def test_load_pending_corrupt(self):
        with patch("identify.PENDING", self.temp_path):
            self.temp_path.parent.mkdir(parents=True, exist_ok=True)
            self.temp_path.write_text("{ corrupt json", encoding="utf-8")

            loaded_entries = load_pending()
            self.assertEqual(loaded_entries, [])

if __name__ == "__main__":
    unittest.main()
