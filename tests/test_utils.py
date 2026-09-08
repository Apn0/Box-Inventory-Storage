import pytest
from utils import slug

def test_slug_happy_path():
    assert slug("Hello World") == "hello world"
    assert slug("ESP32 Board") == "esp32 board"

def test_slug_mixed_cases():
    assert slug("HeLlO wOrLd") == "hello world"
    assert slug("ReSiStOr") == "resistor"

def test_slug_non_alphanumeric():
    assert slug("Hello-World") == "hello world"
    assert slug("C++") == "c"
    assert slug("100% Pure") == "100 pure"
    assert slug("Wait, what?!") == "wait what"
    assert slug("  Spaces  Around  ") == "spaces around"

def test_slug_unicode_combining():
    assert slug("Café") == "cafe"
    assert slug("naïve") == "naive"
    assert slug("Jalapeño") == "jalapeno"
    assert slug("façade") == "facade"
    assert slug("über") == "uber"

def test_slug_empty_and_spaces():
    assert slug("") == ""
    assert slug("   ") == ""
    assert slug("\n\t") == ""

def test_slug_only_symbols():
    assert slug("!@#$%^&*()") == ""
    assert slug("---") == ""

def test_slug_multiple_spaces_reduced():
    assert slug("Hello   World") == "hello world"
    assert slug("A_B--C") == "a b c"
