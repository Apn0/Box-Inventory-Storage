import unittest
from build import slug

class TestSlug(unittest.TestCase):
    def test_slug_basic(self):
        self.assertEqual(slug("hello"), "hello")
        self.assertEqual(slug("HelloWorld"), "helloworld")
        self.assertEqual(slug("Hello World"), "hello world")
        self.assertEqual(slug("abc 123"), "abc 123")

    def test_slug_accents(self):
        self.assertEqual(slug("Café"), "cafe")
        self.assertEqual(slug("naïve"), "naive")
        self.assertEqual(slug("jalapeño"), "jalapeno")
        self.assertEqual(slug("München"), "munchen")

    def test_slug_punctuation(self):
        self.assertEqual(slug("hello, world!"), "hello world")
        self.assertEqual(slug("a--b"), "a b")
        self.assertEqual(slug("123 !@# ABC"), "123 abc")
        self.assertEqual(slug("test_file.txt"), "test file txt")
        self.assertEqual(slug("C++"), "c")

    def test_slug_whitespace(self):
        self.assertEqual(slug("  hello  "), "hello")
        self.assertEqual(slug("hello   world"), "hello world")
        self.assertEqual(slug("  A \n B \t C "), "a b c")

    def test_slug_empty_and_special(self):
        self.assertEqual(slug(""), "")
        self.assertEqual(slug("!!!"), "")
        self.assertEqual(slug("   "), "")
        self.assertEqual(slug("½"), "1 2")

if __name__ == "__main__":
    unittest.main()
