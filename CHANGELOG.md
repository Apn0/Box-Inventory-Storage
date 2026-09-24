# Changelog

Started by the sync sweep on 2026-09-24. Earlier history is in `git log main`.

## [2026-09-24] - Weekly Sync Sweep
- Merged branches: none. `main` matches `origin/main` at 7866188; working tree
  clean. The clone at `C:\Odido\merge_workspace\Box-Inventory-Storage` is at
  the same commit.
- Window: 127 commits since the previous sweep (2026-09-16), 59 non-merge and
  68 merges.
- Features and fixes: search keeps numbers, so "3-pin" finds 3-pin parts
  (7866188); a box can be marked physically full (8d0f294); the CSV export
  escapes spreadsheet formulas (81a7359); the photo service returns a clean 401
  on a wrong key (3e0724a); local APK build script, because the Actions
  allowance is exhausted (e73e26e).
- Security: path traversal in the media handler fixed (ea926fe, 2f2d05a). The
  photo service's `API_KEY` now comes from the environment (4bc68fe).
- Performance: `find_free_boxes`, `find_existing_part`, cached PNG generation.
- Removed one-off scripts: `benchmark_categorise.py`, `benchmark_identify.py`,
  `symlink_test.py`, `test_is_relative_to.py`, `test_windows_strict.py`,
  `test_windows_strict2.py`, `test_windows_vuln.py`. No doc referenced them.
- Tests: `build_items`, `group_rows`, `resolve_item` (with an id-generation fix,
  af5a494), `context_for_prompt`, `find_free_boxes`, `inbox_list`, `read_key`,
  `sync.py`. The suite was not run by this sweep.
- Docs: README "The Android app" said the APK is built by GitHub Actions on every
  push; it now points at `bash tools/build_apk_local.sh`, matching `CLAUDE.md`.
- Hygiene: `.env` was not gitignored and there was no `.env.example` although
  `main.py` reads `API_KEY`. Added both. No `.env` is tracked.
