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

if __name__ == "__main__":
    unittest.main()
