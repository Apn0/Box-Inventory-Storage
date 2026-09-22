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
