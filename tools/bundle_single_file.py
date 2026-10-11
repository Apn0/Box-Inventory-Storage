#!/usr/bin/env python3
"""Bundle the app into ONE self-contained index.html (dist/index.html).

The page is served as ES modules on purpose, but a module cannot be loaded over
file:// — the browser refuses it as a cross-origin request. The APK opens the
page from file:///android_asset/, so the phone build needs everything inlined in
a single classic <script>. Imports here form a plain chain with no cycles
(snapshot -> config -> resolve -> app), so inlining in that order is enough:
drop the import lines, strip the `export ` keyword, concatenate.

Run:  python tools/bundle_single_file.py      ->  dist/index.html
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "index.html"
OUT = ROOT / "dist" / "index.html"
# dependency order, not alphabetical
MODULES = [ROOT / "data" / "snapshot.js",
           ROOT / "src" / "js" / "config.js",
           ROOT / "src" / "js" / "resolve.js",
           ROOT / "src" / "js" / "app.js"]
MODULE_TAG = re.compile(r'<script type="module"[^>]*src="[^"]*"[^>]*>\s*</script>')
IMPORT_LINE = re.compile(r'^\s*import\s[^;]*?;\s*$', re.M)
EXPORT_KW = re.compile(r'^export\s+(?=(const|let|var|function|async|class)\b)', re.M)


def strip_module(src: str) -> str:
    src = IMPORT_LINE.sub("", src)
    src = EXPORT_KW.sub("", src)
    leftover = re.search(r'^\s*(export|import)\s', src, re.M)
    if leftover:
        raise SystemExit(f"bundler cannot handle: {src[leftover.start():][:80]!r}")
    return src


def main() -> int:
    page = PAGE.read_text(encoding="utf-8")
    if not MODULE_TAG.search(page):
        print("index.html has no module <script> to replace", file=sys.stderr)
        return 1

    # config.json is fetched at runtime and falls back to DEFAULT_CONFIG in
    # config.js, which is what the file:// build ends up using. Keeping the
    # fetch costs one failed request; inlining it would duplicate the ids.
    bundle = "\n".join(f"/* ---- {m.relative_to(ROOT).as_posix()} ---- */\n"
                       + strip_module(m.read_text(encoding="utf-8"))
                       for m in MODULES)
    out = MODULE_TAG.sub(lambda _m: f"<script>\n{bundle}\n</script>", page, count=1)

    # a service worker cannot register from file:// either; it only logs noise
    out = out.replace("if ('serviceWorker' in navigator) {",
                      "if ('serviceWorker' in navigator && location.protocol !== 'file:') {")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(out, encoding="utf-8")
    print(f"wrote {OUT}  ({len(out) / 1024:.0f} KB, {len(MODULES)} modules inlined)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
