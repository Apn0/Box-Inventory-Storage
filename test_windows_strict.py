import urllib.parse
import pathlib

def secure_check(path, prefix, folder):
    name = urllib.parse.unquote(path)[len(prefix):]
    # In safe_name:
    # stem = pathlib.PurePosixPath(raw.replace("\\", "/")).name
    name = pathlib.PurePosixPath(name.replace("\\", "/")).name
    target = folder / name

    print(f"Target: {target}")
    print(f"Is relative to folder? {target.is_relative_to(folder)}")

folder = pathlib.Path("C:/app/data/photos")
prefix = "/data/photos/"

print("Test 1: Normal file")
secure_check("/data/photos/photo.jpg", prefix, folder)

print("\nTest 2: Path traversal with /")
secure_check("/data/photos/../../etc/passwd", prefix, folder)

print("\nTest 3: Windows absolute path")
secure_check("/data/photos/C:\\Windows\\System32\\cmd.exe", prefix, folder)

print("\nTest 4: Windows Path Traversal")
secure_check("/data/photos/..\\..\\Windows\\System32\\cmd.exe", prefix, folder)
