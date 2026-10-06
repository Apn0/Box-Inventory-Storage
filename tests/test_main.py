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

def test_parse_box_csv_valid():
    from main import _parse_box_csv
    csv_data = "Box,Item,Qty,Note,UpdatedAt\n1,Resistor,10,some note,2023-01-01\n"
    result = _parse_box_csv(csv_data)
    assert len(result) == 1
    assert result[0]["box"] == 1
    assert result[0]["name"] == "Resistor"
    assert result[0]["qty_txt"] == "10"
    assert result[0]["note"] == "some note"

def test_parse_box_csv_missing_box():
    from main import _parse_box_csv
    # Box column present but empty value
    csv_data = "Box,Item,Qty,Note,UpdatedAt\n,Resistor,10,some note,2023-01-01\n"
    result = _parse_box_csv(csv_data)
    assert len(result) == 0

def test_parse_box_csv_missing_box_column():
    from main import _parse_box_csv
    # Box column completely missing
    csv_data = "Item,Qty,Note,UpdatedAt\nResistor,10,some note,2023-01-01\n"
    result = _parse_box_csv(csv_data)
    assert len(result) == 0
