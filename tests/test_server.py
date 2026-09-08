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

from server import Handler, BOX_GID, FORM_GID
from unittest.mock import MagicMock
import json

def test_proxy_invalid_gid(mocker):
    handler = Handler.__new__(Handler)
    handler.path = "/proxy?gid=12345"
    handler._json = MagicMock(return_value="mocked_json_response")

    result = handler.do_GET()

    handler._json.assert_called_once_with(403, {"error": "forbidden gid"})
    assert result == "mocked_json_response"

def test_proxy_valid_box_gid(mocker):
    handler = Handler.__new__(Handler)
    handler.path = f"/proxy?gid={BOX_GID}"
    handler._send = MagicMock(return_value="mocked_send_response")

    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_response = MagicMock()
    mock_response.read.return_value = b"csv data"
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = handler.do_GET()

    mock_urlopen.assert_called_once()
    assert mock_urlopen.call_args[0][0].endswith(f"gid={BOX_GID}")
    handler._send.assert_called_once()
    assert result == "mocked_send_response"

def test_proxy_valid_form_gid(mocker):
    handler = Handler.__new__(Handler)
    handler.path = f"/proxy?gid={FORM_GID}"
    handler._send = MagicMock(return_value="mocked_send_response")

    mock_urlopen = mocker.patch("urllib.request.urlopen")
    mock_response = MagicMock()
    mock_response.read.return_value = b"csv data"
    mock_urlopen.return_value.__enter__.return_value = mock_response

    result = handler.do_GET()

    mock_urlopen.assert_called_once()
    assert mock_urlopen.call_args[0][0].endswith(f"gid={FORM_GID}")
    handler._send.assert_called_once()
    assert result == "mocked_send_response"
