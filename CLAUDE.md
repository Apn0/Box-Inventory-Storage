# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Box Inventory - Agent Guide

GitHub: `Apn0/Box-Inventory-Storage`.
Base branch: `main`

## Agent Rules
- Work ONLY in your assigned git worktree (`bis-wt/<area>`) on your specific branch. 
- Never `git switch` in the main repo dir or in other agents' worktrees. Commit often and push to your branch.
- Stay inside your file ownership. If you need a change in someone else's files, ask them.
- There is no direct line to the user. Message the orchestrator for decisions, blockers, and when done.

## Commands
No npm, no bundler, no linter config. Python 3 + Node >= 22 (built-in `node:test`).

```bash
pip install -r requirements.txt pytest pytest-mock   # pytest/pytest-mock are NOT in requirements.txt
python -m pytest -q                                   # 163 tests. Bare `pytest` fails: repo root not on sys.path
python -m pytest tests/test_build.py::test_parse_date_happy_paths
node --test 'tests/*.js'                              # 44 tests. Quote the glob; `node --test tests/` fails
node --test tests/test_shelf.js
node --test --test-name-pattern='label' 'tests/*.js'

python build.py          # data/inventory_raw.csv + data/form_responses.csv -> data/inventory.json + data/snapshot.js (offline)
python sync.py           # download BOX + Form tabs from the live sheet (keeps .bak), then runs build.py
python -m http.server 8791                            # preview (.claude/launch.json); ES modules need http://, not file://
python tools/bundle_single_file.py                    # -> dist/index.html (single classic <script>, for the APK)
```

- `build.py` stamps today's date into `data/inventory.json` and `data/snapshot.js`: an unchanged sheet still yields a diff. Revert both unless you mean to ship data.
- `tests/test_box_full.py` imports `main`, so Flask + google-auth must be installed even for resolver tests.
- `tools/apply_move.py` needs `aiohttp`, which is not in `requirements.txt`.

## Architecture
**The Google Sheet is the database; a Google Form is the write API.** No server is needed to read or write counts.
- Read: CSV export of two tabs (`config.json`: `sheet_id`, `box_gid`, `form_gid`). BOX tab = hand-edited `Box,Item,Qty,Note,UpdatedAt` (date only). Form responses tab = every row the app wrote (with `Timestamp`).
- Write: `sheetAppend` in `src/js/app.js` submits a hidden `<form>` into an iframe (navigation, so no CORS), then re-fetches the sheet with 1.2/2.5/5 s backoff and treats a grown `meta.rawRows` as proof of the save.
- Nothing is ever deleted. A correction is a new row; a move is two rows from `moveRows`: fill the new box FIRST, then `0` in the old box (a reader that sees only the zero thinks the part is gone).

**Two resolvers that must stay in lockstep:**
- `inventory_core/resolver.py`: used by `build.py`, `main.py`, `identify.py`, `server.py`, `tools/*`. `build.py` re-exports its symbols for backward compatibility (`identify.py` and tests import from `build`).
- `src/js/resolve.js` (`resolveSheet`): runs in the browser against the live sheet.
- Category regex lists are duplicated in both files: same order, first match wins. Change one -> change the other.
- Parity check: `tests/fixtures/resolver_cases.json`, consumed by `tests/test_resolve.js`.
- Form rows carry a time of day, so an app write beats a same-day BOX-tab edit; form rows are deliberate recounts and never raise the ambiguity flag.

**Frontend** (`index.html` -> `src/js/app.js`; import chain `snapshot -> config -> resolve -> app`, must stay acyclic for the bundler):
- Boot: `data/snapshot.js` (baked) = instant first paint -> live sheet via `resolveSheet` -> fallback `data/inventory.json` -> keep snapshot.
- `data/reorg_plan.json` (`generated`, `rules`, `boxes`) is fetched at runtime and drives Reorganize / Walk the shelf / Labels.
- localStorage: `boxinv.v1` (overlay), `boxinv.labelsUpto`, `boxinv.server`.
- Testable logic lives in exported pure functions in `app.js` (`isRunningLow`, `moveRows`, `shelfRows`, `labelBoxes`, `labelsToWrite`, `parseLabelsUpto`); Node tests stub the DOM with `tests/mock_globals.js`. New logic you want tested: export it pure, import `./mock_globals.js` first.
- Adding a module/asset: add it to `ASSETS` in `sw.js` AND to `MODULES` (dependency order) in `tools/bundle_single_file.py`, and bump `CACHE_NAME` (currently `box-inventory-v4`).
- `sw.js` strategy: `inventory.json`/`config.json` network-first; everything else cache-first with background refresh; `docs.google.com`, `run.app` and the `server.py` endpoints bypass the cache.

**Optional backends** (photo identification only):
- `main.py`: Cloud Run service `box-identify` (Flask, `Procfile` -> gunicorn). Stateless: live sheet -> resolver -> Vertex Gemini -> proposal. Never writes; the phone confirms and appends via the Form. Requires `Authorization: Bearer $API_KEY` (`.env.example`). App default endpoint is in `app.js` (`identify_endpoint` in config overrides it). No deploy script in the repo.
- `server.py`: PC server, `python server.py` binds `127.0.0.1:8781` by default (`--host`/`--port`; the docstring's 8777 is stale). Photo queue `data/inbox/` -> `data/review/` -> `data/photos/` via `/upload`, `/inbox`, `/confirm`, `/dismiss`; plus `/proxy` (sheet CSV), `/quickadd`, `/undo`, `/identify`.
- `identify.py`: CLI photo -> part -> box. Vertex token via `gcloud auth print-access-token`; other keys from `~/Desktop/.env`. Windows-PC oriented.

**`tools/` (docstrings in Dutch):**
- `apply_move.py N --dry-run|--yes` and `post_rows.py rows.json --dry-run|--yes` POST to the LIVE sheet. Always `--dry-run` first; `--yes` only on Arno's instruction.
- `container_sheet.py N` / `container_page.py N` generate `data/REORG_CONTAINER_N.md` / `.html` worksheets from `reorg_plan.json` + the live sheet.

## Data Contract Quirks
- **Resolution**: Append-log newest-wins resolution per `(box, normalized item name)`. Differing quantities across rows in the same box set a conflict rather than being averaged.
- **`99` and `?`**: In the old spreadsheet, `99` meant "a pile" (many/bulk), not a literal count of 99. `?` means unknown. Never sum or trust `99` as a real number. The app writes `many` for bulk.
- **`[BOX FULL]`**: Item name `[BOX FULL]` is a row, not a part. Qty `1` = full, `0` = has room. Every resolver must skip it as a part. A full box never receives a Reorganize move or a proposed box.
- **CSV Export**: When exporting CSV, prefix `'` to text starting with `= + - @ tab CR` for formula injection safety (`toCSV` in `app.js`). The `data/*.csv` sheet mirrors are deliberately NOT escaped.
- **Golden numbers**: Baseline 253 records / 242 parts / 154 boxes. The committed snapshot (`meta.generated` 2026-10-11) holds 263 records / 245 active parts / 156 boxes; the drift is explained in `data/RECONCILIATION.md`. Counts grow with the sheet: explain drift, do not "fix" it.
- **Categories**: Auto-assigned from part name + note (14 regex rules + `misc` = 15 labels).
- **Containers**: Boxes group in sets of 30 (`container_of`): 1-30 = container 1; 400+ are household boxes, containers `H1`, `H2`, ...


## Phone: the web app on GitHub Pages
- Arno's choice 2026-11-03: the phone runs the app from `https://apn0.github.io/Box-Inventory-Storage/`
  (home-screen shortcut). Pages builds `main` (root) on every push without Actions minutes, so a
  push to `main` is the release.
- `sw.js` serves its ASSETS cache-first: bump `CACHE_NAME` whenever a cached file changes, or the
  phone keeps running the old app.
- Reorganize -> Walk the shelf writes two rows to the LIVE sheet on every tap. Never tap a part
  while testing in a browser; drive the view and read it. The same holds for any +/- or save in a
  local preview: `http.server` on localhost still writes to the live sheet.
- How far the box labels go is a per-phone setting on the Labels tab (localStorage
  `boxinv.labelsUpto`, default 90). Walk the shelf locks any part whose new box is past it.

## Phone app (APK)
- The Android project is **not optional scaffolding**: it is the other way onto the phone. The
  last build (v42, 2026-10-11) predates Walk the shelf, and `tools/bundle_single_file.py` does not
  inline `data/reorg_plan.json`, so a rebuilt APK cannot load the plan until the bundler does.
  GitHub Actions cannot build it (account out of minutes, cannot be paid), so build locally:
  `bash tools/build_apk_local.sh` -> signs with `android/app/debug.keystore` (same key as every
  earlier build, so it installs as an update) and publishes to the `latest` release.
- `build_apk_local.sh` is hard-wired to Arno's Windows PC (`C:/Users/arnod/AndroidSdk`, `aapt2.exe`,
  JDK 17, Gradle 8.11.1, `gh`): it does not run in a Linux cloud container.
- The APK opens the page from `file:///android_asset/`, where a browser refuses ES modules.
  `tools/bundle_single_file.py` inlines snapshot/config/resolve/app into `dist/index.html`;
  the build script calls it. Keep the import chain acyclic or the bundler will refuse.
- Never delete `android/`, the keystore or these scripts: losing the keystore means the phone
  can no longer update the app, only reinstall it.

> Sessions opened inside this repo load NO cross-project memory. Update this file as the app evolves.
