# Box Inventory - Agent Guide

GitHub: `Apn0/Box-Inventory-Storage`.
Base branch: `main`

## Agent Rules
- Work ONLY in your assigned git worktree (`bis-wt/<area>`) on your specific branch. 
- Never `git switch` in the main repo dir or in other agents' worktrees. Commit often and push to your branch.
- Stay inside your file ownership. If you need a change in someone else's files, ask them.
- There is no direct line to the user. Message the orchestrator for decisions, blockers, and when done.

## Data Contract Quirks
- **Resolution**: Append-log newest-wins resolution per `(box, normalized item name)`. Differing quantities across rows in the same box set a conflict rather than being averaged.
- **`99` and `?`**: In the old spreadsheet, `99` meant "a pile" (many/bulk), not a literal count of 99. `?` means unknown. Never sum or trust `99` as a real number. 
- **`[BOX FULL]`**: Item name `[BOX FULL]` is a row, not a part. Qty `1` = full, `0` = has room. Every resolver must skip it as a part. A full box never receives a Reorganize move or a proposed box.
- **CSV Export**: When exporting CSV, prefix `'` to text starting with `= + - @ tab CR` for formula injection safety. The `data/*.csv` sheet mirrors are deliberately NOT escaped.
- **Golden numbers**: The current data has 253 records / 242 parts / 154 boxes.
- **Categories**: Auto-assigned from part name (15 categories).
- **Containers**: Boxes group in sets of 30.


## Phone: the web app on GitHub Pages
- Arno's choice 2026-11-03: the phone runs the app from `https://apn0.github.io/Box-Inventory-Storage/`
  (home-screen shortcut). Pages builds `main` (root) on every push without Actions minutes, so a
  push to `main` is the release.
- `sw.js` serves its ASSETS cache-first: bump `CACHE_NAME` whenever a cached file changes, or the
  phone keeps running the old app.
- Reorganize -> Walk the shelf writes two rows to the LIVE sheet on every tap. Never tap a part
  while testing in a browser; drive the view and read it.
- How far the box labels go is a per-phone setting on the Labels tab (localStorage
  `boxinv.labelsUpto`, default 90). Walk the shelf locks any part whose new box is past it.

## Phone app (APK)
- The Android project is **not optional scaffolding**: it is the other way onto the phone. The
  last build (v42, 2026-10-11) predates Walk the shelf, and `tools/bundle_single_file.py` does not
  inline `data/reorg_plan.json`, so a rebuilt APK cannot load the plan until the bundler does.
  GitHub Actions cannot build it (account out of minutes, cannot be paid), so build locally:
  `bash tools/build_apk_local.sh` -> signs with `android/app/debug.keystore` (same key as every
  earlier build, so it installs as an update) and publishes to the `latest` release.
- The APK opens the page from `file:///android_asset/`, where a browser refuses ES modules.
  `tools/bundle_single_file.py` inlines snapshot/config/resolve/app into `dist/index.html`;
  the build script calls it. Keep the import chain acyclic or the bundler will refuse.
- Never delete `android/`, the keystore or these scripts: losing the keystore means the phone
  can no longer update the app, only reinstall it.

> Sessions opened inside this repo load NO cross-project memory. Update this file as the app evolves.
