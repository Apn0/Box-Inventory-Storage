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

> Sessions opened inside this repo load NO cross-project memory. Update this file as the app evolves.
