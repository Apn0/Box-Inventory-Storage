# Data Reconciliation Report

## 1. Pending Discrepancies
The live Google Sheet (specifically `form_responses.csv`) contains user findings from 04/10/2026 and 05/10/2026 that were missing from `inventory_raw.csv` and `walkthrough_worklist.md`. These findings are:
- **Box 52**: Added "Like about the 10 mm nut and it's circular nut" with quantity `many`.
- **Boxes 3, 30, 48, 49, 50, 51, 58**: "Flexible shaft coupling" (and similar names) was set to quantity `0` (marked gone) and these boxes were marked as `[BOX FULL]`.
- **Box 55**: "Flexible shaft coupling" was added with quantity `2`.
- **Box 78**: Marked as `[BOX FULL]`.

## 2. Issues (Newest-Wins Conflicts)
The following items have conflicting quantities in the data history without a `(photo-counted)` note to verify them as deliberate recounts. I am marking them as **needs user check**, as we cannot confidently guess physical reality:
- **Box 1**: Tap bits (M2 + M2.5) — logged as `3` on 17/02, then `2` on 25/02. *(needs user check)*
- **Box 43**: MT3608 DC-DC step-up (boost) converter module — logged as `1`, then `4`, then `1`. *(needs user check)*
- **Box 84**: Laser diode module — logged as `1` in Box 84, `0` in Box 115, then `9` in Box 84. *(needs user check)*

No Google Form writes were made to forcefully resolve these; they require a physical audit.

## 3. Golden Numbers Drift
The golden numbers (253 records / 242 parts / 154 boxes) were checked against the current snapshot.
- **Records**: 262 (Drift: +9). Explanation: The user created 8 new "shaft coupling" parts across different boxes, plus 1 new item in box 52.
- **Active Parts**: 244 (Drift: +2). Explanation: The 7 shaft couplings set to `0` are correctly resolved as "gone". The two new active parts are the consolidated coupling in box 55 and the new item in box 52.
- **Active Boxes**: 156 (Drift: +2). Explanation: Boxes 52 and 55, which previously had no active parts, now contain the new active items. The boxes where the couplings were removed (3, 30, etc.) still contain other active parts, so they remain active boxes.

## 4. Junk Data Cleanup
Instructed W1-Hygiene to untrack and delete:
- `data/inventory_raw.xlsx` (duplicate)
- `data/inventory_raw.csv.*.bak` (local backup)
- `data/ignored/*.jpg` (~7 MB of useless test photos)

## 5. Local Snapshot Refresh
Ran `sync.py` to refresh `inventory_raw.csv` and `form_responses.csv` from the live Google Sheet, and successfully rebuilt `data/inventory.json` and `index.html`.
