import pathlib
import urllib.parse
import os

folder = pathlib.Path("/app/data/photos")
folder.mkdir(parents=True, exist_ok=True)

# create a symlink inside the folder pointing to /etc/passwd
symlink_target = folder / "passwd_link"
if not symlink_target.exists():
    symlink_target.symlink_to("/etc/passwd")

# The server logic
path = "/data/photos/passwd_link"
name = pathlib.PurePosixPath(urllib.parse.unquote(path)).name
print(f"Extracted name: {name}")

target = folder / name
print(f"Target path: {target}")

try:
    print(f"Original check: {folder.resolve() in target.resolve().parents}")
except Exception as e:
    print(f"Original check error: {e}")

try:
    print(f"Safe check: {target.resolve().is_relative_to(folder.resolve())}")
except Exception as e:
    print(f"Safe check error: {e}")
