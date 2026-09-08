import pytest
import datetime
from unittest.mock import patch
from server import safe_name, port_in_use
import socket

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

@patch('server.socket.socket')
def test_port_in_use_ipv4(mock_socket):
    mock_s = mock_socket.return_value.__enter__.return_value
    mock_s.connect_ex.return_value = 0

    assert port_in_use(8080) == "127.0.0.1"
    mock_socket.assert_called_once_with(socket.AF_INET, socket.SOCK_STREAM)
    mock_s.connect_ex.assert_called_once_with(("127.0.0.1", 8080))

@patch('server.socket.socket')
def test_port_in_use_ipv6(mock_socket):
    mock_s = mock_socket.return_value.__enter__.return_value
    mock_s.connect_ex.side_effect = [111, 0]

    assert port_in_use(8080) == "::1"
    assert mock_socket.call_count == 2
    mock_socket.assert_called_with(socket.AF_INET6, socket.SOCK_STREAM)

@patch('server.socket.socket')
def test_port_in_use_not_in_use(mock_socket):
    mock_s = mock_socket.return_value.__enter__.return_value
    mock_s.connect_ex.side_effect = [111, 111]

    assert port_in_use(8080) is None
    assert mock_socket.call_count == 2

@patch('server.socket.socket')
def test_port_in_use_oserror_first(mock_socket):
    from unittest.mock import MagicMock
    mock_s_success = MagicMock()
    mock_s_success.__enter__.return_value.connect_ex.return_value = 0

    mock_socket.side_effect = [OSError("Socket error"), mock_s_success]

    assert port_in_use(8080) == "::1"
    assert mock_socket.call_count == 2

@patch('server.socket.socket')
def test_port_in_use_oserror_both(mock_socket):
    mock_socket.side_effect = OSError("Socket error")
    assert port_in_use(8080) is None
