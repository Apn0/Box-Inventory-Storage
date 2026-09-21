import pytest
from identify import context_for_prompt

def test_context_for_prompt_standard_input():
    data = {
        "meta": {
            "categoryLabels": {
                "cat1": "Category 1",
                "cat2": "Category 2"
            }
        }
    }
    active = [
        {"name": "Item B"},
        {"name": "Item A"}
    ]

    result = context_for_prompt(data, active)

    expected = (
        "Category keys you must choose from: cat1 (Category 1), cat2 (Category 2).\n\n"
        "Parts already in the inventory (reuse the exact name if it is the same part):\n"
        "- Item A\n"
        "- Item B"
    )
    assert result == expected

def test_context_for_prompt_empty_input():
    data = {
        "meta": {
            "categoryLabels": {}
        }
    }
    active = []

    result = context_for_prompt(data, active)

    expected = (
        "Category keys you must choose from: .\n\n"
        "Parts already in the inventory (reuse the exact name if it is the same part):\n"
    )
    assert result == expected

def test_context_for_prompt_duplicate_names():
    data = {
        "meta": {
            "categoryLabels": {
                "cat1": "Category 1"
            }
        }
    }
    active = [
        {"name": "Item A"},
        {"name": "Item B"},
        {"name": "Item A"},
        {"name": "Item B"}
    ]

    result = context_for_prompt(data, active)

    expected = (
        "Category keys you must choose from: cat1 (Category 1).\n\n"
        "Parts already in the inventory (reuse the exact name if it is the same part):\n"
        "- Item A\n"
        "- Item B"
    )
    assert result == expected
