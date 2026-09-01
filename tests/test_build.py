import pytest
from build import parse_date

def test_parse_date_happy_paths():
    assert parse_date("01/12/2023") == "2023-12-01"
    assert parse_date("2023-12-01") == "2023-12-01"
    assert parse_date("01-12-2023") == "2023-12-01"

def test_parse_date_empty_inputs():
    assert parse_date(None) is None
    assert parse_date("") is None
    assert parse_date("   ") is None

def test_parse_date_error_paths():
    with pytest.raises(ValueError, match="unparseable date: 'not a date'"):
        parse_date("not a date")

    with pytest.raises(ValueError, match="unparseable date: '2023/12/01'"):
        parse_date("2023/12/01")

    with pytest.raises(ValueError, match="unparseable date: '32/01/2023'"):
        parse_date("32/01/2023")

    with pytest.raises(ValueError, match="unparseable date: '2023-13-01'"):
        parse_date("2023-13-01")
import unittest
from build import categorise, DEFAULT_CATEGORY

    with pytest.raises(ValueError, match="unparseable date: '12/31/2023'"):
        parse_date("12/31/2023")

    with pytest.raises(ValueError, match="unparseable date: '01.12.2023'"):
        parse_date("01.12.2023")

    with pytest.raises(ValueError, match="unparseable date: '20231201'"):
        parse_date("20231201")

    with pytest.raises(ValueError, match="unparseable date: '01/12/23'"):
        parse_date("01/12/23")

from build import find_free_boxes, container_of

def test_find_free_boxes_empty():
    assert find_free_boxes([]) == []

def test_find_free_boxes_no_free():
    items = [
        {"box": 1, "status": "active"},
        {"box": 2, "status": "active"},
        {"box": 3, "status": "active"}
    ]
    assert find_free_boxes(items) == []

def test_find_free_boxes_with_gaps():
    items = [
        {"box": 1, "status": "active"},
        {"box": 3, "status": "active"}
    ]
    free = find_free_boxes(items)
    assert len(free) == 1
    assert free[0] == {"box": 2, "container": container_of(2), "reason": "never used"}

def test_find_free_boxes_emptied():
    items = [
        {"box": 1, "status": "active"},
        {"box": 2, "status": "gone"},
        {"box": 3, "status": "active"}
    ]
    free = find_free_boxes(items)
    assert len(free) == 1
    assert free[0] == {"box": 2, "container": container_of(2), "reason": "emptied"}

def test_find_free_boxes_high_range():
    items = [
        {"box": 400, "status": "active"},
        {"box": 402, "status": "active"}
    ]
    free = find_free_boxes(items)
    assert len(free) == 1
    assert free[0] == {"box": 401, "container": container_of(401), "reason": "never used"}

def test_find_free_boxes_mixed_ranges():
    items = [
        {"box": 1, "status": "active"},
        {"box": 3, "status": "active"},
        {"box": 400, "status": "gone"},
        {"box": 402, "status": "active"}
    ]
    free = find_free_boxes(items)
    assert len(free) == 3

    # Asserting correct values and order
    assert free[0] == {"box": 2, "container": container_of(2), "reason": "never used"}
    assert free[1] == {"box": 400, "container": container_of(400), "reason": "emptied"}
    assert free[2] == {"box": 401, "container": container_of(401), "reason": "never used"}
