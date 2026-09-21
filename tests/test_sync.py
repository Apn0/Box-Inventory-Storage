import sys
import urllib.request
import urllib.error

# Add root to sys.path so we can import sync
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import sync

def test_sync_download_failure(mocker, capsys):
    # Mock urllib.request.urlopen to raise a URLError (or any exception)
    mocker.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("mock error"))

    # Call main
    result = sync.main()

    # Verify the return code is 1
    assert result == 1

    # Verify standard error outputs
    captured = capsys.readouterr()
    assert "download failed:" in captured.err
    assert "mock error" in captured.err
    assert "(is the sheet still shared as 'anyone with the link'?)" in captured.err

def test_sync_main_success(mocker, tmp_path, capsys):
    mock_raw = tmp_path / "inventory_raw.csv"
    mock_form = tmp_path / "form_responses.csv"
    mocker.patch("sync.RAW", mock_raw)
    mocker.patch("sync.FORM_CSV", mock_form)

    class MockResponse:
        def __init__(self, content):
            self.content = content
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return self.content

    def mock_urlopen(url, *args, **kwargs):
        if url == sync.URL:
            return MockResponse(b"Box,Item\n1,A")
        elif url == sync.FORM_URL:
            return MockResponse(b"Timestamp,Action\n2023,Add")
        raise ValueError(f"Unexpected URL: {url}")

    mocker.patch("urllib.request.urlopen", side_effect=mock_urlopen)
    mock_call = mocker.patch("subprocess.call", return_value=0)

    # Pre-populate RAW to test .bak file creation
    mock_raw.write_bytes(b"Box,Old\n1,Old")

    result = sync.main()

    assert result == 0
    assert mock_raw.read_bytes() == b"Box,Item\n1,A"
    assert mock_form.read_bytes() == b"Timestamp,Action\n2023,Add"

    bak_files = list(tmp_path.glob("inventory_raw.csv.*.bak"))
    assert len(bak_files) == 1
    assert bak_files[0].read_bytes() == b"Box,Old\n1,Old"

    mock_call.assert_called_once_with([sys.executable, str(sync.ROOT / "build.py")])

    captured = capsys.readouterr()
    assert "downloading" in captured.out
    assert "previous CSV kept" in captured.out
    assert "wrote" in captured.out
