# Box Inventory

Replaces a hand-kept spreadsheet for tracking storage boxes. GitHub:
`Apn0/Box-Inventory-Storage`.

**Important data-migration quirk:** in the old spreadsheet, a quantity of `99`
meant "a pile" (unknown/uncounted amount), not a literal count of 99 — never
sum or trust `99` as a real number when reconciling against the old sheet.

**"Box is physically full" is a row, not a part.** Item name `[BOX FULL]`,
Qty `1` = full, `0` = has room again; newest row wins like any count, and a box
with no active parts is never full. Every resolver must skip it as a part:
`build.py` (`BOX_FULL_ITEM`, `find_full_boxes`), `main.py`, and `resolveSheet()`
in `src/app.template.html`. A full box never receives a Reorganize move or a
proposed box; parts in it stay put when consolidating. Tests:
`tests/test_box_full.py`.

**CSV export** prefixes `'` to text starting with `= + - @ tab CR` (formula
injection). The `data/*.csv` sheet mirrors are deliberately NOT escaped.

> Sessions opened inside this repo load NO cross-project memory. Update this
> file as the app evolves.
