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
