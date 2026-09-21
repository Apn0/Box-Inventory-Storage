import pathlib
import urllib.parse
import os

# Set up test environment
base_dir = pathlib.Path("/tmp/test_server_vuln")
base_dir.mkdir(parents=True, exist_ok=True)

photos_dir = base_dir / "data/photos"
photos_dir.mkdir(parents=True, exist_ok=True)

secret_file = base_dir / "secret.txt"
secret_file.write_text("I am a secret")

symlink_dir = base_dir / "symlink_dir"
if not symlink_dir.exists():
    symlink_dir.symlink_to(base_dir, target_is_directory=True)

# Now what if a file in photos_dir is a symlink to outside?
malicious_symlink = photos_dir / "foo.jpg"
if not malicious_symlink.exists():
    malicious_symlink.symlink_to(secret_file)

folder = photos_dir
target = malicious_symlink

print(f"Target is symlink? {target.is_symlink()}")
print(f"Target resolve(): {target.resolve()}")
print(f"Folder resolve(): {folder.resolve()}")
print(f"Is target relative to folder? {folder.resolve() in target.resolve().parents}")

# Now what if an attacker accesses a path where part of the path is a symlink?
# No, they are accessing "/data/photos/{name}". `name` is the last component of the URL.
path = "/data/photos/foo.jpg"
name = pathlib.PurePosixPath(urllib.parse.unquote(path)).name
target = folder / name
print(f"Accessing via path: {target.resolve()}")
print(f"Allowed? {target.is_file() and folder.resolve() in target.resolve().parents}")
