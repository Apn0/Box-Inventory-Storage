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
    assert safe_name("my photo!.jpg") == "20231024-153045-123_my_photo.jpg"
    assert safe_name("file_with-dashes.and.dots.jpg") == "20231024-153045-123_file_with-dashes.and.dots.jpg"
    assert safe_name("😀emoji.png") == "20231024-153045-123_emoji.png"

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
    assert safe_name("!!!.jpg") == "20231024-153045-123_photo.jpg"
    assert safe_name(".jpg") == "20231024-153045-123_jpg.jpg"
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


def test_is_relative_to_symlink_outside_folder(tmp_path):
    import pathlib
    import urllib.parse

    folder = tmp_path / "photos"
    folder.mkdir()

    # create a symlink inside the folder pointing outside
    symlink_target = folder / "passwd_link"
    if not symlink_target.exists():
        # we can't reliably point to /etc/passwd in all environments, so let's point to a file outside the folder
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("secret")
        symlink_target.symlink_to(outside_file)

    path = "/data/photos/passwd_link"
    name = pathlib.PurePosixPath(urllib.parse.unquote(path)).name
    target = folder / name

    # resolve() in parents is what was originally used and might be unsafe with symlinks
    original_check = folder.resolve() in target.resolve().parents

    # is_relative_to() on resolved target checks if the final path is still inside the folder
    safe_check = target.resolve().is_relative_to(folder.resolve())

    assert original_check == False
    assert safe_check == False


def test_handler_symlink_traversal_blocked(mocker, tmp_path):
    import pytest
    from server import Handler
    folder = tmp_path / "photos"
    folder.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("secret_data")
    link = folder / "leak.jpg"
    try:
        link.symlink_to(secret)
    except OSError:
        pytest.skip("Symlink creation not permitted in this environment")

    handler = Handler.__new__(Handler)
    handler.path = "/data/photos/leak.jpg"
    handler._json = mocker.MagicMock()
    handler._send = mocker.MagicMock()

    with patch('server.PHOTOS', folder):
        handler.do_GET()

    handler._json.assert_called_with(404, {"error": "not found"})
    assert not handler._send.called


def test_windows_path_extraction():
    import pathlib
    import urllib.parse

    # Simulate a path coming from a Windows system with backslashes
    path = "/data/photos/C:\\Windows\\System32\\cmd.exe"

    # What happens if we don't replace backslashes (vulnerable on Linux where \ is a valid filename character)
    name_unsafe = pathlib.PurePosixPath(urllib.parse.unquote(path)).name
    assert name_unsafe == "C:\\Windows\\System32\\cmd.exe"

    # What the server actually does to protect against this (safe_name logic)
    # The pure unquote is what was originally done but now replaced backslashes before getting name
    name_safe = pathlib.PurePosixPath(urllib.parse.unquote(path).replace("\\", "/")).name
    assert name_safe == "cmd.exe"


def test_port_in_use_oserror():
    from server import port_in_use
    with patch('server.socket.socket', side_effect=OSError("Mocked OSError")):
        assert port_in_use(1234) is None


def test_symlink_path_access(tmp_path):
    import pathlib
    import urllib.parse

    base_dir = tmp_path / "test_server_vuln"
    base_dir.mkdir(parents=True, exist_ok=True)

    photos_dir = base_dir / "data/photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    secret_file = base_dir / "secret.txt"
    secret_file.write_text("I am a secret")

    # Simulate an attacker trying to access a symlink they somehow placed in the photos dir
    malicious_symlink = photos_dir / "foo.jpg"
    if not malicious_symlink.exists():
        malicious_symlink.symlink_to(secret_file)

    folder = photos_dir
    target = malicious_symlink

    # Original symlink_test.py check logic
    # Server accesses "/data/photos/{name}". name is the last component of the URL.
    path = "/data/photos/foo.jpg"
    name = pathlib.PurePosixPath(urllib.parse.unquote(path)).name
    target = folder / name

    # Should not be allowed since the target resolves outside the folder
    is_allowed = target.is_file() and folder.resolve() in target.resolve().parents
    assert is_allowed == False

def test_review_list(tmp_path, monkeypatch):
    import server
    import time

    # Mock the REVIEW directory
    review_dir = tmp_path / "review"
    monkeypatch.setattr(server, "REVIEW", review_dir)

    # 1. Test empty / non-existent directory
    assert server.review_list() == []

    review_dir.mkdir()
    assert server.review_list() == []

    # 2. Add files of various types and a directory
    file1 = review_dir / "photo1.jpg"
    file1.write_text("dummy data 1")
    time.sleep(0.05) # Ensure different modification times

    file2 = review_dir / "image2.PNG"
    file2.write_text("dummy data 222")
    time.sleep(0.05)

    # File with unallowed extension
    file3 = review_dir / "doc.txt"
    file3.write_text("not a photo")

    # Directory
    subdir = review_dir / "subdir.jpg"
    subdir.mkdir()

    # 3. Test that review_list returns correct files in correct order (newest first)
    result = server.review_list()
    assert len(result) == 2

    # file2 should be first because it's newest
    assert result[0]["name"] == "image2.PNG"
    assert result[0]["size"] == len("dummy data 222")
    assert "at" in result[0]

    assert result[1]["name"] == "photo1.jpg"
    assert result[1]["size"] == len("dummy data 1")
    assert "at" in result[1]

def test_photos_in_not_exists(tmp_path):
    from server import _photos_in
    import pathlib
    non_existent = tmp_path / "does_not_exist"
    assert _photos_in(non_existent) == []

def test_photos_in_empty(tmp_path):
    from server import _photos_in
    empty_folder = tmp_path / "empty"
    empty_folder.mkdir()
    assert _photos_in(empty_folder) == []

def test_photos_in_filtering_and_sorting(tmp_path):
    from server import _photos_in
    import time
    import os

    test_folder = tmp_path / "test_photos"
    test_folder.mkdir()

    # Create valid files
    file1 = test_folder / "img1.jpg"
    file1.write_text("1")

    # We want file2 to be newer than file1
    file2 = test_folder / "img2.PNG"
    file2.write_text("22")

    # file3 is even newer
    file3 = test_folder / "img3.webp"
    file3.write_text("333")

    # Use os.utime to definitively set the modification times
    now = time.time()
    os.utime(file1, (now, now - 10))
    os.utime(file2, (now, now - 5))
    os.utime(file3, (now, now))


    # Create invalid extension
    invalid = test_folder / "document.txt"
    invalid.write_text("text")

    # Create subdirectory
    subdir = test_folder / "subdir.jpg"
    subdir.mkdir()

    results = _photos_in(test_folder)

    # It should skip subdir.jpg and document.txt
    assert len(results) == 3

    # It should be sorted reverse chronologically (newest first)
    assert results[0]["name"] == "img3.webp"
    assert results[0]["size"] == 3
    assert "at" in results[0]

    assert results[1]["name"] == "img2.PNG"
    assert results[1]["size"] == 2

    assert results[2]["name"] == "img1.jpg"
    assert results[2]["size"] == 1
