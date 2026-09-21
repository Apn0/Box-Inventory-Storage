import pytest
import identify
import os
import pathlib

@pytest.fixture(autouse=True)
def setup_env_mock(monkeypatch, tmp_path):
    # Reset globals
    identify._env_cache = None
    identify._env_mtime = 0.0

    # Delete possible env variables so os.environ test doesn't flake
    monkeypatch.delenv("ANY_KEY", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.delenv("OTHER_KEY", raising=False)
    monkeypatch.delenv("MISSING_KEY", raising=False)
    monkeypatch.delenv("EMPTY_KEY", raising=False)
    monkeypatch.delenv("PADDED_KEY", raising=False)
    monkeypatch.delenv("MY_KEY", raising=False)
    monkeypatch.delenv("KEY", raising=False)

    # Mock ENV path
    env_file = tmp_path / ".env"
    monkeypatch.setattr(identify, "ENV", env_file)

    yield env_file

def test_read_key_from_env(setup_env_mock, monkeypatch):
    monkeypatch.setenv("API_KEY", "env_value")
    # Should read from env even if .env doesn't exist or has another value
    setup_env_mock.write_text("API_KEY=file_value")
    assert identify.read_key("API_KEY") == "env_value"

def test_read_key_no_file(setup_env_mock):

    # Ensure None is returned when the file does not exist
    assert identify.read_key("ANY_KEY") is None

def test_read_key_with_file(setup_env_mock):
    setup_env_mock.write_text("API_KEY=12345\nOTHER_KEY=abc")
    assert identify.read_key("API_KEY") == "12345"
    assert identify.read_key("OTHER_KEY") == "abc"
    assert identify.read_key("MISSING_KEY") is None

def test_read_key_empty_value(setup_env_mock):
    setup_env_mock.write_text("EMPTY_KEY=\n")
    assert identify.read_key("EMPTY_KEY") is None

def test_read_key_whitespace(setup_env_mock):
    setup_env_mock.write_text("  PADDED_KEY  =  val \n")
    assert identify.read_key("PADDED_KEY") == "val"

def test_read_key_cache_update(setup_env_mock):
    # Write initial data
    setup_env_mock.write_text("MY_KEY=initial")
    assert identify.read_key("MY_KEY") == "initial"

    # Update data but ensure st_mtime increases (simulate time passing)
    import time
    time.sleep(0.01) # Small delay to ensure mtime increases
    setup_env_mock.write_text("MY_KEY=updated")

    # We might need to manually update the mtime if it's too fast
    current_time = setup_env_mock.stat().st_mtime
    os.utime(setup_env_mock, (current_time + 1.0, current_time + 1.0))

    assert identify.read_key("MY_KEY") == "updated"

def test_read_key_cache_no_update(setup_env_mock, monkeypatch):
    setup_env_mock.write_text("MY_KEY=cached")
    assert identify.read_key("MY_KEY") == "cached"

    # Mock the read_text to raise an exception by replacing the method on the class
    original_read_text = pathlib.Path.read_text
    def mock_read_text(*args, **kwargs):
        raise RuntimeError("Should not be called because it's cached")

    monkeypatch.setattr(pathlib.Path, "read_text", mock_read_text)

    assert identify.read_key("MY_KEY") == "cached"

def test_read_key_ignores_lines_without_equals(setup_env_mock):
    setup_env_mock.write_text("JUST_SOME_TEXT\nAPI_KEY=val\n")
    assert identify.read_key("API_KEY") == "val"

def test_read_key_multiple_equals(setup_env_mock):
    setup_env_mock.write_text("KEY=val1=val2\n")
    assert identify.read_key("KEY") == "val1=val2"
