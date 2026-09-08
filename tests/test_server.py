import pytest
import datetime
import socket
from unittest.mock import patch, MagicMock
from server import safe_name, port_in_use

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

def test_port_in_use_free():
    with patch("server.socket.socket") as mock_socket_cls:
        mock_instance = MagicMock()
        mock_socket_cls.return_value.__enter__.return_value = mock_instance
        mock_instance.connect_ex.return_value = 1  # non-zero means not in use

        assert port_in_use(8080) is None

def test_port_in_use_ipv4():
    with patch("server.socket.socket") as mock_socket_cls:
        mock_instance = MagicMock()
        mock_socket_cls.return_value.__enter__.return_value = mock_instance

        def connect_ex_side_effect(address):
            if address == ("127.0.0.1", 8080):
                return 0
            return 1

        mock_instance.connect_ex.side_effect = connect_ex_side_effect

        assert port_in_use(8080) == "127.0.0.1"

def test_port_in_use_ipv6():
    with patch("server.socket.socket") as mock_socket_cls:
        mock_instance = MagicMock()
        mock_socket_cls.return_value.__enter__.return_value = mock_instance

        def connect_ex_side_effect(address):
            if address == ("::1", 8080):
                return 0
            return 1

        mock_instance.connect_ex.side_effect = connect_ex_side_effect

        assert port_in_use(8080) == "::1"

def test_port_in_use_oserror():
    with patch("server.socket.socket") as mock_socket_cls:
        def side_effect(family, type):
            if family == socket.AF_INET:
                raise OSError("simulated")
            mock_sock = MagicMock()
            mock_sock.__enter__.return_value = mock_sock
            mock_sock.connect_ex.return_value = 0
            return mock_sock

        mock_socket_cls.side_effect = side_effect

        assert port_in_use(8080) == "::1"
