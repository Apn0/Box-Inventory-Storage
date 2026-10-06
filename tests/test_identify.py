import pytest
from identify import context_for_prompt, decide

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

def test_decide_exact_match_by_name():
    active = [
        {"name": "Resistor 10k", "box": 5, "countType": "exact", "qty": 10}
    ]
    result = {
        "name": "Resistor 10k",
        "quantity": "5",
        "matches_existing": "",
        "category": "passives"
    }

    decision = decide({}, active, result, {}, {})

    assert decision["box"] == 5
    assert decision["name"] == "Resistor 10k"
    assert decision["quantity"] == 15
    assert decision["existing"] is True
    assert decision["from"] == 10
    assert decision["to"] == 15

def test_decide_exact_match_by_matches_existing():
    active = [
        {"name": "Capacitor 100nF", "box": 3, "countType": "exact", "qty": 20}
    ]
    result = {
        "name": "Capacitor 0.1uF",
        "quantity": "10",
        "matches_existing": "Capacitor 100nF",
        "category": "passives"
    }

    decision = decide({}, active, result, {}, {})

    assert decision["box"] == 3
    assert decision["name"] == "Capacitor 100nF"
    assert decision["quantity"] == 30
    assert decision["existing"] is True
    assert decision["from"] == 20
    assert decision["to"] == 30

def test_decide_bulk_match():
    active = [
        {"name": "M3 screws", "box": 1, "countType": "bulk", "qty": "many"}
    ]
    result = {
        "name": "M3 screws",
        "quantity": "50",
        "matches_existing": "",
        "category": "hardware"
    }

    decision = decide({}, active, result, {}, {})

    assert decision["box"] == 1
    assert decision["name"] == "M3 screws"
    assert decision["quantity"] == "many"
    assert decision["existing"] is True
    assert decision["from"] is None
    assert decision["to"] is None

def test_decide_no_match():
    active = [
        {"name": "Resistor 10k", "box": 5, "countType": "exact", "qty": 10}
    ]
    result = {
        "name": "LED Red",
        "quantity": "5",
        "matches_existing": "",
        "category": "semiconductors"
    }

    data = {"freeBoxes": [{"box": 10, "reason": "empty"}]}
    per_box = {5: 1}
    category_boxes = {"semiconductors": set()}

    decision = decide(data, active, result, per_box, category_boxes)

    assert decision["box"] == 10
    assert decision["name"] == "LED Red"
    assert decision["quantity"] == 5
    assert decision["existing"] is False
    assert decision["from"] is None
    assert decision["to"] == 5

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
