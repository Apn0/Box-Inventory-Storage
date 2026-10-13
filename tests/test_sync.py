import sys
import urllib.request
import urllib.error

# Add root to sys.path so we can import sync
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import sync
from unittest.mock import MagicMock
import pytest

def test_sync_download_failure(mocker, capsys):
    # Mock urllib.request.urlopen to raise a URLError (or any exception)
    mocker.patch("sync.urlopen", side_effect=urllib.error.URLError("mock error"))

    # Call main
    result = sync.main()

    # Verify the return code is 1
    assert result == 1

    # Verify standard error outputs
    captured = capsys.readouterr()
    assert "download failed:" in captured.err
    assert "mock error" in captured.err
    assert "(is the sheet still shared as 'anyone with the link'?)" in captured.err

def test_sync_invalid_content(mocker, capsys, tmp_path):
    # Mock RAW so we don't modify actual files
    mocker.patch("sync.RAW", tmp_path / "raw.csv")

    mock_resp = MagicMock()
    mock_resp.read.return_value = b"Not Bx\nSome content"
    mocker.patch("sync.urlopen", return_value=MagicMock(__enter__=MagicMock(return_value=mock_resp)))

    result = sync.main()

    assert result == 1
    out, err = capsys.readouterr()
    assert "that does not look like the inventory sheet" in err

def test_sync_success_with_form_failure(mocker, capsys, tmp_path):
    mocker.patch("sync.RAW", tmp_path / "raw.csv")
    mocker.patch("sync.FORM_CSV", tmp_path / "form.csv")
    (tmp_path / "raw.csv").write_text("Old content")

    def mock_urlopen(url, timeout=60):
        if "gid=788564724" in url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"Box\nLine 2"
            return MagicMock(__enter__=MagicMock(return_value=mock_resp))
        else:
            raise OSError("mock os error")

    mocker.patch("sync.urlopen", side_effect=mock_urlopen)
    mocker.patch("subprocess.call", return_value=0)

    result = sync.main()
    assert result == 0
    out, err = capsys.readouterr()
    assert "form tab skipped: mock os error" in out

def test_sync_main_offline_unmerged_preservation(mocker, capsys, tmp_path):
    mocker.patch("sync.RAW", tmp_path / "raw.csv")
    mocker.patch("sync.FORM_CSV", tmp_path / "form.csv")

    (tmp_path / "raw.csv").write_text("Box,ID,Name\n1,p1,Resistor\nOffline,p2,Capacitor")

    def mock_urlopen(url, timeout=60):
        if "gid=788564724" in url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"Box,ID,Name\n1,p1,Resistor"
            return MagicMock(__enter__=MagicMock(return_value=mock_resp))
        else:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"Timestamp,Col2\nVal1,Val2"
            return MagicMock(__enter__=MagicMock(return_value=mock_resp))

    mocker.patch("urllib.request.urlopen", side_effect=mock_urlopen)
    mocker.patch("subprocess.call", return_value=0)

    result = sync.main()
    assert result == 0

    out, err = capsys.readouterr()
    assert "WARNING: preserved 1 unmerged offline rows" in out

    offline_file = tmp_path / "offline_unmerged.csv"
    assert offline_file.exists()
    assert "Offline,p2,Capacitor" in offline_file.read_text(encoding="utf-8")

def test_sync_main_success(mocker, capsys, tmp_path):
    mocker.patch("sync.RAW", tmp_path / "raw.csv")
    mocker.patch("sync.FORM_CSV", tmp_path / "form.csv")

    def mock_urlopen(url, timeout=60):
        if "gid=788564724" in url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"Box\nLine 2"
            return MagicMock(__enter__=MagicMock(return_value=mock_resp))
        else:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"Timestamp,Col2\nVal1,Val2"
            return MagicMock(__enter__=MagicMock(return_value=mock_resp))

    mocker.patch("urllib.request.urlopen", side_effect=mock_urlopen)
    mocker.patch("subprocess.call", return_value=0)

    result = sync.main()
    assert result == 0

    out, err = capsys.readouterr()
    assert "wrote " in out

def test_sync_success(mocker, capsys, tmp_path):
    mocker.patch("sync.RAW", tmp_path / "raw.csv")
    mocker.patch("sync.FORM_CSV", tmp_path / "form.csv")

    def mock_urlopen(url, timeout=60):
        if "gid=788564724" in url:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"Box\nLine 2"
            return MagicMock(__enter__=MagicMock(return_value=mock_resp))
        else:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"Timestamp,Col2\nVal1,Val2"
            return MagicMock(__enter__=MagicMock(return_value=mock_resp))

    mocker.patch("sync.urlopen", side_effect=mock_urlopen)
    mocker.patch("subprocess.call", return_value=0)

    result = sync.main()
    assert result == 0
