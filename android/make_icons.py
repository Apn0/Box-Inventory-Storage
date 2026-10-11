#!/usr/bin/env python3
"""Generate the launcher PNGs, so no binary art has to live in the repo by hand.

    python make_icons.py

Same glyph as the web app's icon: an accent square with a box outline.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from server import png  # noqa: E402  - reuse the one PNG writer

DENSITIES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
RES = pathlib.Path(__file__).resolve().parent / "app" / "src" / "main" / "res"

for name, size in DENSITIES.items():
    out = RES / f"mipmap-{name}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ic_launcher.png").write_bytes(png(size))
    print(f"  mipmap-{name}/ic_launcher.png  ({size}px)")
