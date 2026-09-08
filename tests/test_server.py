import pytest
import datetime
from unittest.mock import patch
from server import safe_name
from server import port_in_use

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

# Note: The actual server.py implementation is more robust than the simplified snippet in the task description.
# It tests both IPv4 ("127.0.0.1") and IPv6 ("::1") and returns the address string, not a formatted string.
def test_port_in_use_ipv4():
    with patch('socket.socket') as mock_sock_cls:
        mock_sock = mock_sock_cls.return_value.__enter__.return_value
        mock_sock.connect_ex.return_value = 0 # 0 means success

        assert port_in_use(8080) == "127.0.0.1"

        # Verify it was called with IPv4 first
        mock_sock.connect_ex.assert_called_once_with(("127.0.0.1", 8080))

def test_port_in_use_ipv6():
    with patch('socket.socket') as mock_sock_cls:
        mock_sock = mock_sock_cls.return_value.__enter__.return_value
        # First call for IPv4 fails (returns 1), second call for IPv6 succeeds (returns 0)
        mock_sock.connect_ex.side_effect = [1, 0]

        assert port_in_use(8080) == "::1"

        # Verify both were called
        assert mock_sock.connect_ex.call_count == 2

def test_port_in_use_none():
    with patch('socket.socket') as mock_sock_cls:
        mock_sock = mock_sock_cls.return_value.__enter__.return_value
        # Both calls fail
        mock_sock.connect_ex.side_effect = [1, 1]

        assert port_in_use(8080) is None

def test_port_in_use_oserror():
    with patch('socket.socket') as mock_sock_cls:
        mock_sock = mock_sock_cls.return_value.__enter__.return_value
        # First call raises OSError, second call fails normally
        mock_sock.connect_ex.side_effect = [OSError("Network down"), 1]

        assert port_in_use(8080) is None

def test_port_in_use_oserror_success():
    with patch('socket.socket') as mock_sock_cls:
        mock_sock = mock_sock_cls.return_value.__enter__.return_value
        # First call raises OSError, second call succeeds
        mock_sock.connect_ex.side_effect = [OSError("Network down"), 0]

        assert port_in_use(8080) == "::1"
