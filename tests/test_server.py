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

def test_handler_path_sanitization(mocker):
    from server import Handler
    import pathlib

    handler = Handler.__new__(Handler)
    handler.path = "/data/photos/C:\\Windows\\System32\\cmd.exe"
    handler._json = mocker.MagicMock()
    handler._send = mocker.MagicMock()

    with patch('server.PHOTOS', pathlib.Path('/app/data/photos')):
        handler.do_GET()

    # It should not try to serve C:\Windows\System32\cmd.exe, but rather a file inside PHOTOS called cmd.exe
    # Since it likely does not exist, it will return 404
    handler._json.assert_called_with(404, {"error": "not found"})

def test_handler_path_sanitization_traversal(mocker):
    from server import Handler
    import pathlib

    handler = Handler.__new__(Handler)
    handler.path = "/data/photos/../%2E%2E/%2E%2E/etc/passwd"
    handler._json = mocker.MagicMock()
    handler._send = mocker.MagicMock()

    with patch('server.PHOTOS', pathlib.Path('/app/data/photos')):
        handler.do_GET()

    # The file passwd should be queried inside PHOTOS, not at /etc/passwd
    # Because it is queried inside PHOTOS, it is not found
    handler._json.assert_called_with(404, {"error": "not found"})
