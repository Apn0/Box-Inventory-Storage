import urllib.parse
import pathlib

path = "/data/photos/C:\\Windows\\System32\\cmd.exe"
name = pathlib.PurePosixPath(urllib.parse.unquote(path)).name
print(f"Name from path: {name}")

# On a real windows system `pathlib.Path` is `pathlib.WindowsPath`
folder = pathlib.PureWindowsPath("C:/app/data/photos")
target = folder / name
print(f"Target on Windows: {target}")

# Using replace("\\", "/") would make it safe.
name_safe = pathlib.PurePosixPath(urllib.parse.unquote(path).replace("\\", "/")).name
print(f"Safe Name: {name_safe}")
target_safe = folder / name_safe
print(f"Safe Target on Windows: {target_safe}")
