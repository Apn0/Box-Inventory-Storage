import pytest
import datetime
import json
from unittest.mock import patch, MagicMock
from server import safe_name, Handler, BOX_GID, FORM_GID

@pytest.fixture
def mock_datetime():
    with patch('server.datetime') as mock_dt:
        mock_dt.datetime.now.return_value = datetime.datetime(2023, 10, 24, 15, 30, 45, 123456)
        yield mock_dt

def test_safe_name_basic(mock_datetime):
    assert safe_name("photo.jpg") == "20231024-153045-123_photo.jpg"
    assert safe_name("image.png") == "20231024-153045-123_image.png"
    assert safe_name("picture.HEIC") == "20231024-153045-123_picture.heic"

def test_safe_name_path_sanitization(mock_datetime):
    assert safe_name("folder/file.jpg") == "20231024-153045-123_file.jpg"
    assert safe_name("C:\\Users\\Bob\\photo.png") == "20231024-153045-123_photo.png"
    assert safe_name("../../etc/passwd.jpg") == "20231024-153045-123_passwd.jpg"

def test_safe_name_special_characters(mock_datetime):
    assert safe_name("my photo!.jpg") == "20231024-153045-123_my_photo_.jpg"
    assert safe_name("file_with-dashes.and.dots.jpg") == "20231024-153045-123_file_with-dashes.and.dots.jpg"
    assert safe_name("😀emoji.png") == "20231024-153045-123__emoji.png"

def test_safe_name_unallowed_extensions(mock_datetime):
    # Unallowed extensions default to .jpg
    assert safe_name("document.pdf") == "20231024-153045-123_document.jpg"
    assert safe_name("script.py") == "20231024-153045-123_script.jpg"
    assert safe_name("noextension") == "20231024-153045-123_noextension.jpg"

def test_safe_name_length_truncation(mock_datetime):
    long_name = "a" * 100 + ".jpg"
    expected = "20231024-153045-123_" + "a" * 60 + ".jpg"
    assert safe_name(long_name) == expected

def test_safe_name_empty_or_invalid_stem(mock_datetime):
    assert safe_name("!!!.jpg") == "20231024-153045-123__.jpg"
    assert safe_name(".jpg") == "20231024-153045-123_.jpg.jpg"
    assert safe_name("") == "20231024-153045-123_photo.jpg"

def test_proxy_ssrf_allowlist():
    handler = Handler.__new__(Handler)

    responses = []
    def mock_json(code, data):
        responses.append((code, data))
        return

    def mock_send(resp):
        responses.append((resp.code, resp.body))
        return

    handler._json = mock_json
    handler._send = mock_send

    # Test unallowed GID
    handler.path = "/proxy?gid=123456789"
    handler.do_GET()
    assert responses[-1][0] == 403
    assert responses[-1][1] == {"error": "gid not allowed"}

    # Test allowed GID (BOX_GID)
    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b"box_csv_data"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        handler.path = f"/proxy?gid={BOX_GID}"
        handler.do_GET()

        assert responses[-1][0] == 200
        assert responses[-1][1] == b"box_csv_data"

    # Test allowed GID (FORM_GID)
    with patch('urllib.request.urlopen') as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = b"form_csv_data"
        mock_urlopen.return_value.__enter__.return_value = mock_response

        handler.path = f"/proxy?gid={FORM_GID}"
        handler.do_GET()

        assert responses[-1][0] == 200
        assert responses[-1][1] == b"form_csv_data"

    # Test invalid GID string
    handler.path = "/proxy?gid=invalid"
    handler.do_GET()
    assert responses[-1][0] == 403
    assert responses[-1][1] == {"error": "gid not allowed"}
