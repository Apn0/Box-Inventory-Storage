# Box Inventory

A replacement for the "Box Inventory Storage" Google Sheet — the numbered
component boxes (1–128) and household boxes (401–438).

**Open `index.html`.** No install, no server, no internet. Works from a USB
stick, works on the phone if you copy the one file across.

---

## Why not just keep the sheet

The sheet is an *append log*: every time a box was audited, its rows were
written again. That is fine as a record and useless as an answer to "how many
do I have". Measured on the 263-row export:

| Problem in the sheet | Count |
|---|---|
| `99` used to mean "a pile", not ninety-nine | 53 rows (20%) |
| Same box+item logged twice or more | 8 groups — **3 with a different number each time** |
| Rows left at qty 0 after the part was moved out | 13 |
| Boxes that are empty or never used, so invisible as free slots | 12 |
| The same part living in two different boxes | 7 |
| Rows with any note at all | 47 of 263 |
| Category, so you can ask "show me every sensor" | none |

263 raw rows collapse to **253 records — 242 parts you actually have across
154 boxes**.

## What this does instead

- **One row per part.** Newest sheet row wins per box+item. The 3 cases where
  the number genuinely changed are not silently guessed — they are flagged
  **ambiguous** and listed under *Issues* so you can count them once and be done.
- **`99` is gone.** A pile is `many` / *bulk*; a real count is a real count;
  unknown is `?`. Nothing pretends to be a quantity it isn't.
- **Categories** — 15 of them, auto-assigned from the part name (sensors,
  power, drivers, motors, fasteners, …). Filter with one tap.
- **Search that means it.** Type anything; matches on name, note, category and
  box number.
- **Boxes view** — every box as a grid, grouped into the physical containers of
  30. Free slots are dashed green so you can reuse a number instead of buying
  another box.
- **Build check** — paste a parts list, get back *which boxes to open* and
  what you're missing. Quantity-aware: asking for 2 limit switches points at
  the bulk pile in box 21, not the single odd one.
- **Printable labels** — one per non-empty box.
- **Editing** — change a count, move a part, add a part. Edits are stored in
  the browser and never touch the base data.
- **Export CSV** in the sheet's exact columns, so you can paste it straight
  back over the Google Sheet.

## Reorganising

The **Reorganise** tab plans real box moves at three effort levels and applies them.
Measured on the current data (cap 6 items/box):

| Level | Moves | Boxes freed | Result |
|---|---|---|---|
| 1. Merge duplicates | 7 | 7 | 154 → 147 boxes |
| 2. Consolidate singles | 40 | 40 | 154 → 114 boxes, one-item boxes 116 → 51 |
| 3. Regroup by type | 111 | 64 | 154 → 90 boxes, categories spread over 4.0 → 2.9 containers |

Level 3 converges in two applications (111 → 5 → 0 moves, 154 → 87 boxes) — all 242
parts are preserved. Bulk piles are never merged into a shared box. Boxes 10, 11 and
12 already hold more than the cap; the plan does not empty them, it just won't add.

## The Android app

Built by GitHub Actions — nothing Android has to be installed on the PC. Every
push to `android/**` rebuilds it, and the APK is published to the rolling
[**latest**](https://github.com/Apn0/Box-Inventory-Storage/releases/tag/latest)
release. Open that link on the phone (signed into GitHub, the repo is private),
download, install — Android will ask you to allow installing from that browser.

The shell is a WebView pointing at `server.py`. On first run, menu → **Server
address**:

- **at home** → `http://192.168.1.140:8781`
- **away** → the PC's NordVPN **Meshnet** address, same port

The one thing this shell adds over a browser tab is the file chooser: a WebView
ignores `<input type="file">` entirely unless the host app implements
`onShowFileChooser`, so the camera button would silently do nothing without it.
It honours the page's `capture` attribute — tap goes straight to the camera,
long-press opens the gallery.

No CAMERA permission is requested: photos are taken by the phone's own camera app
into a MediaStore URI, which also avoids a FileProvider and keeps full resolution.
`minSdk` is 29 for the same reason — below that, MediaStore would need
`WRITE_EXTERNAL_STORAGE`.

Rebuild manually with `gh workflow run android.yml`.

## On the phone — `server.py`

```powershell
cd V:\_Claude\box-inventory; python server.py
```

It prints the addresses to use. On the phone, on the same WiFi, open
`http://192.168.1.140:8781` → Chrome menu → **Add to Home screen**. That gives an
icon in the app drawer that opens fullscreen with no browser bar — for this job it
is what an APK would have been, without an Android SDK.

A round camera button sits bottom-right (only when served — never on `file://`):

- **tap** → camera opens straight away, shoot the part
- **long-press** → pick shots you already took from the gallery, several at once

Photos upload to the PC immediately and land in `data/inbox/`. The badge on the
button shows how many are waiting. Nothing needs the vision API to *arrive* — they
queue until you identify them, so snapping works even with the keys empty.

**Two things can stop the phone reaching the PC:**

1. **Windows Firewall.** Allow the port once, from an admin PowerShell:
   ```powershell
   New-NetFirewallRule -DisplayName "Box Inventory" -Direction Inbound -Protocol TCP -LocalPort 8781 -Profile Private -Action Allow
   ```
   This exposes the app to your local network — anyone on your WiFi can read the
   inventory and post photos. There is no login. Keep it to `-Profile Private`.
2. **VPN.** NordVPN was active on this machine; a VPN routes the phone's traffic
   away from your LAN. Disconnect it, or exclude the local network.

If the port is taken, `server.py` now says so and stops instead of half-binding —
use `--port 8782`.

## Entering parts without a photo

Three buttons, bottom right. For a part you can name, **⌨️ is the fast one** —
it matches against the inventory already in the page, so there is no vision
call, no wait and no cost, and it works with every API account empty.

- **tap ⌨️** — type or dictate a name, pick the match, set the count
- **hold ⌨️** — voice mode

Voice mode is a fixed question tree run on the phone: part → any attributes that
apply to its category (soldered? heat sink?) → box → count → logged → "anything
else?". No model, no API call. **It ends when you say "stop", not on a timer** —
long silences are expected while you walk to a container.

Speech is on-device: Android's own recognizer in the APK, Chrome's in the
browser. A plain WebView does not implement the Web Speech API at all, which is
what `SpeechBridge.java` exists for — without it the microphone does nothing
inside the app, however well it works in Chrome.

Part numbers arrive as words in pieces, so they are normalized before matching.
These all resolve to the right box: `tmc twenty two zero nine`,
`t m c twenty two zero nine`, `one eight six five zero`,
`a d s one one one five`, `mt three six zero eight`, `hx seven one one`.

Everything is en-US: page language, recognizer, speech synthesis, spelling.

## Photo intake — `identify.py`

```powershell
cd V:\_Claude\box-inventory; python identify.py "C:\path\to\photo.jpg"
```

Identifies the part, proposes a box (an existing box of the same category with room,
else the lowest free number), asks before writing, then appends to the CSV and
rebuilds. `--dry-run` identifies without writing; `--yes` skips the prompts.

The API key is read from `Desktop\.env` at run time and is **never** written into
`index.html` — the app stays offline and key-free.

Providers are tried in order, skipping any account that is out of credit:
**Vertex → Claude → Gemini → OpenAI**. Force one with `--provider`.

Vertex is first on purpose: it bills the Free Trial credits on the separate
Google account (`peterfrissen123@gmail.com`, project `deft-melody-503207-k8`,
billing `01EC6B-1704CE-DFD319` — €259 left as of 2026-08-15) instead of a personal
API key, and it authenticates through `gcloud`, so no key for it sits in `.env`.
If the token expires: `gcloud auth login peterfrissen123@gmail.com`.

The Anthropic and Google API keys in `.env` are both out of credit.

**A part you already own increments, it does not overwrite.** Rows resolve
newest-wins per box+item, so appending the delta would have replaced a count of 5
with 1. When the photo matches an existing part, the appended row carries the new
total and its Note is marked `(photo-counted)` — which also tells `build.py` the
change was deliberate, so it is not flagged as an ambiguous quantity.

Matching does not rely on the model naming a part the same way twice — it does
not. The same board came back as "TMC2209 stepper driver" from one provider and
"TMC2209-LA stepper driver module" from another. So an exact name match is tried
first, then the **part number** (`tmc2209`, `mt3608`, `18650`): distinctive enough
to identify a board, where "module" or "sensor" is not. If the part number appears
in more than one box the match is refused rather than guessed.

## Files

```
index.html              the app — self-contained, this is the thing to open
data/inventory_raw.csv  verbatim export of the Google Sheet (never edited)
data/inventory_raw.xlsx same, original formatting
data/inventory.json     the normalised data build.py produces
data/photos/            photos filed by identify.py, named <box>_<part>
data/inbox/             photos sent from the phone, waiting to be identified
src/app.template.html   app source; build.py injects the data into it
build.py                CSV -> JSON -> index.html
sync.py                 re-download the sheet, then build
server.py               serves the app to the phone + receives photos (stdlib only)
identify.py             photo -> part -> box (needs a funded vision API key)
```

## Re-syncing after you change the Google Sheet

```powershell
cd V:\_Claude\box-inventory; python build.py
```

That rebuilds `data/inventory.json` and `index.html` from
`data/inventory_raw.csv`. To pull a fresh copy of the sheet first:

```powershell
cd V:\_Claude\box-inventory; python sync.py
```

`sync.py` downloads the sheet over the raw CSV and then runs the build.

> Windows PowerShell 5.1 has no `&&` — use `;` between commands.

Local edits made in the app survive a rebuild — they are keyed by box+item and
layered on top. Export the CSV when you want them back in the sheet.

## Rules the code enforces

- **Resolution**: newest row per `(box, normalised item name)`. Differing
  quantities across rows set `conflict: true` rather than being averaged,
  summed, or quietly dropped.
- **Containers**: boxes group in sets of `CONTAINER_SIZE` (30). Boxes under 400
  and the 400-series are separate physical sets, numbered independently —
  `1…5` and `H1…H2`. `build.py: container_of()` and
  `app.template.html: containerOf()` must stay identical.
- **Matching** (search ranking and Build check) is whole-word or prefix, never
  raw substring — substring matching made `TOF` match `cu`**`tof`**`fs`.
