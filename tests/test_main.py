import base64
import pytest
from main import app
import os

@pytest.fixture
def client():
    app.config['TESTING'] = True
    os.environ['API_KEY'] = 'test-key'
    with app.test_client() as client:
        yield client

def test_health(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.data == b"ok"

def test_identify_missing_image(client):
    response = client.post("/identify", data=b"",
                           headers={"Authorization": "Bearer test-key"})
    assert response.status_code == 400
    assert b"no image" in response.data

def test_identify_too_large(client):
    # The limit is 25MB. We'll generate a payload slightly larger than that.
    # To keep the test fast and avoid allocating a huge string in memory, we can just use
    # a mocked request or simulate large data.
    # But since it's a test, let's just make a string > 25MB.
    # Actually, we don't need to pass a 25MB string if we can just test the config.
    assert app.config['MAX_CONTENT_LENGTH'] == 25 * 1024 * 1024

    # Let's see what happens if we pass 26MB of 'a's
    large_data = b"a" * (25 * 1024 * 1024 + 100)
    response = client.post("/identify", data=large_data)
    assert response.status_code == 413


def test_identify_rejects_bad_key_with_401(client):
    # Must stay a clean 401 even with a photo attached: the phone only
    # re-asks for the key on a 401.
    response = client.post("/identify", data=b"x" * 50000,
                           headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_parse_form_csv_malformed_date():
    from main import _parse_form_csv

    # A CSV row with a malformed date should catch the ValueError in parse_date
    # and default the 'date' field to None
    csv_data = "Timestamp,Box,Item,Qty,Note\nbad_date 10:00:00,1,Resistor,10,\n"

    result = _parse_form_csv(csv_data)

    assert len(result) == 1
    assert result[0]["name"] == "Resistor"
    assert result[0]["date"] is None
    assert result[0]["time"] == "10:00:00"


def test_group_and_resolve_basic():
    from main import _group_and_resolve
    from datetime import date

    raw_rows = [
        {"box": 1, "name": "Resistor 10k", "qty_txt": "10", "note": "Test", "date": date(2023, 1, 1), "time": "12:00:00", "src": 0, "line": 2},
        {"box": 2, "name": "Capacitor 100nF", "qty_txt": "0", "note": "Empty", "date": date(2023, 1, 2), "time": "12:00:00", "src": 0, "line": 3},
    ]

    items, full_newest = _group_and_resolve(raw_rows)

    assert len(items) == 2

    item1 = next(i for i in items if i["name"] == "Resistor 10k")
    assert item1["box"] == 1
    assert item1["qty"] == 10
    assert item1["countType"] == "exact"
    assert item1["status"] == "active"
    assert item1["note"] == "Test"

    item2 = next(i for i in items if i["name"] == "Capacitor 100nF")
    assert item2["box"] == 2
    assert item2["qty"] == 0
    assert item2["countType"] == "exact"
    assert item2["status"] == "gone"


def test_group_and_resolve_conflicts():
    from main import _group_and_resolve
    from datetime import date

    raw_rows = [
        {"box": 1, "name": "Resistor", "qty_txt": "10", "note": "Old", "date": date(2023, 1, 1), "time": "10:00:00", "src": 0, "line": 2},
        {"box": 1, "name": "Resistor", "qty_txt": "20", "note": "New", "date": date(2023, 1, 2), "time": "10:00:00", "src": 0, "line": 3},
        {"box": 1, "name": "Resistor", "qty_txt": "30", "note": "Newest", "date": date(2023, 1, 2), "time": "12:00:00", "src": 0, "line": 4},
        # Ties in date/time are resolved by src, then line
        {"box": 2, "name": "Capacitor", "qty_txt": "5", "note": "Src0", "date": date(2023, 1, 1), "time": "10:00:00", "src": 0, "line": 2},
        {"box": 2, "name": "Capacitor", "qty_txt": "15", "note": "Src1", "date": date(2023, 1, 1), "time": "10:00:00", "src": 1, "line": 2},
    ]

    items, full_newest = _group_and_resolve(raw_rows)

    assert len(items) == 2

    resistor = next(i for i in items if i["name"] == "Resistor")
    assert resistor["qty"] == 30
    assert resistor["note"] == "Newest"

    capacitor = next(i for i in items if i["name"] == "Capacitor")
    assert capacitor["qty"] == 15
    assert capacitor["note"] == "Src1"


def test_group_and_resolve_qty_types():
    from main import _group_and_resolve, BULK_SENTINEL
    from datetime import date

    raw_rows = [
        {"box": 1, "name": "Resistor", "qty_txt": "", "note": "Unknown qty", "date": date(2023, 1, 1), "time": "10:00:00", "src": 0, "line": 2},
        {"box": 2, "name": "Capacitor", "qty_txt": str(BULK_SENTINEL), "note": "Bulk qty", "date": date(2023, 1, 1), "time": "10:00:00", "src": 0, "line": 3},
    ]

    items, full_newest = _group_and_resolve(raw_rows)

    assert len(items) == 2

    resistor = next(i for i in items if i["name"] == "Resistor")
    assert resistor["qty"] is None
    assert resistor["countType"] == "unknown"
    assert resistor["status"] == "active"

    capacitor = next(i for i in items if i["name"] == "Capacitor")
    assert capacitor["qty"] is None
    assert capacitor["countType"] == "bulk"
    assert capacitor["status"] == "active"


def test_group_and_resolve_note_inheritance():
    from main import _group_and_resolve
    from datetime import date

    raw_rows = [
        {"box": 1, "name": "Resistor", "qty_txt": "10", "note": "Original note", "date": date(2023, 1, 1), "time": "10:00:00", "src": 0, "line": 2},
        {"box": 1, "name": "Resistor", "qty_txt": "20", "note": "", "date": date(2023, 1, 2), "time": "10:00:00", "src": 0, "line": 3},
    ]

    items, full_newest = _group_and_resolve(raw_rows)

    assert len(items) == 1

    resistor = items[0]
    assert resistor["qty"] == 20
    assert resistor["note"] == "Original note"


def test_group_and_resolve_edge_cases():
    from main import _group_and_resolve
    from build import BOX_FULL_ITEM
    from utils import slug
    from datetime import date

    raw_rows = [
        # Empty name should be skipped by `if not latest["name"]:`
        {"box": 1, "name": "", "qty_txt": "10", "note": "", "date": date(2023, 1, 1), "time": "10:00:00", "src": 0, "line": 2},
        # BOX_FULL_ITEM should be added to full_newest, not items
        {"box": 2, "name": BOX_FULL_ITEM, "qty_txt": "1", "note": "Full", "date": date(2023, 1, 1), "time": "10:00:00", "src": 0, "line": 4},
        # Another box full to ensure we get the latest
        {"box": 2, "name": BOX_FULL_ITEM, "qty_txt": "1", "note": "Still Full", "date": date(2023, 1, 2), "time": "10:00:00", "src": 0, "line": 5},
    ]

    items, full_newest = _group_and_resolve(raw_rows)

    assert len(items) == 0
    assert len(full_newest) == 1

    assert 2 in full_newest
    assert full_newest[2]["note"] == "Still Full"
