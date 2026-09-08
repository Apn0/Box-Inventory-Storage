import pathlib
import urllib.parse
import os

# Suppose we are on Windows, and pathlib.Path behaves like PureWindowsPath
folder = pathlib.PureWindowsPath("C:/app/data/photos")
path = "/data/photos/C:%5cWindows%5cSystem32%5ccmd.exe"

# server.py logic
name = pathlib.PurePosixPath(urllib.parse.unquote(path)).name
print(f"Extracted name: {name}")

target = folder / name
print(f"Target path: {target}")

# The check
# For PureWindowsPath, we can't call resolve().parents.
# But we can check parents
print(f"Is folder in target.parents? {folder in target.parents}")
