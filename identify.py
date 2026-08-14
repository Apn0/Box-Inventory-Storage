#!/usr/bin/env python3
"""
Photo -> part -> box. Point it at photos of components you have not filed yet.

    python identify.py photo1.jpg photo2.jpg
    python identify.py C:\\Users\\arnod\\Desktop\\newparts\\*.jpg

For each photo it identifies the part, picks a box (an existing box of the same
category with room, else a free number), shows you the proposal, and only writes
after you confirm. Writing appends to data/inventory_raw.csv and re-runs build.py.

The API key is read from the user's Desktop\\.env and is never written into
index.html — the app itself stays offline and key-free.
"""
from __future__ import annotations

import argparse
import base64
import collections
import csv
import datetime
import glob
import json
import mimetypes
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
RAW = ROOT / "data" / "inventory_raw.csv"
INVENTORY = ROOT / "data" / "inventory.json"
PHOTOS = ROOT / "data" / "photos"
ENV = pathlib.Path.home() / "Desktop" / ".env"

MODEL = "claude-opus-5"
MAX_BOX_ITEMS = 6           # keep in step with the app's reorganise cap
SUPPORTED = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".gif": "image/gif", ".webp": "image/webp"}

SYSTEM = (
    "You identify loose electronic components and hardware from photos, for a "
    "hobbyist's parts inventory. Name parts the way a supplier would: chip or "
    "module designation first, then what it is. Say what you can actually see — "
    "if the marking is unreadable, describe the part generically and set "
    "confidence to low rather than guessing a part number."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string",
                 "description": "Short part name in the style of the existing inventory, "
                                "e.g. 'MT3608 DC-DC step-up (boost) converter module'."},
        "quantity": {"type": "integer", "description": "How many of this part are visible. 0 if unclear."},
        "category": {"type": "string", "description": "One of the category keys supplied in the prompt."},
        "note": {"type": "string", "description": "Markings, pin labels, size, or colour. Empty string if none."},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "matches_existing": {"type": "string",
                             "description": "Exact name of an existing inventory item if this is the same "
                                            "part you already have, else an empty string."},
    },
    "required": ["name", "quantity", "category", "note", "confidence", "matches_existing"],
    "additionalProperties": False,
}


GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              f"{GEMINI_MODEL}:generateContent")

# Gemini takes the same fields but wants uppercase types and no additionalProperties.
GEMINI_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "name": {"type": "STRING"},
        "quantity": {"type": "INTEGER"},
        "category": {"type": "STRING"},
        "note": {"type": "STRING"},
        "confidence": {"type": "STRING", "enum": ["high", "medium", "low"]},
        "matches_existing": {"type": "STRING"},
    },
    "required": ["name", "quantity", "category", "note", "confidence", "matches_existing"],
    "propertyOrdering": ["name", "quantity", "category", "note", "confidence", "matches_existing"],
}


def read_key(name: str) -> str | None:
    if not ENV.exists():
        return None
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith(f"{name}="):
            return line.split("=", 1)[1].strip() or None
    return None


def load_inventory() -> dict:
    if not INVENTORY.exists():
        sys.exit(f"missing {INVENTORY} — run build.py first")
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def context_for_prompt(data: dict) -> str:
    """A compact view of what already exists, so the model reuses naming and spots duplicates."""
    cats = ", ".join(f"{k} ({v})" for k, v in data["meta"]["categoryLabels"].items())
    names = sorted({i["name"] for i in data["items"] if i["status"] == "active"})
    return (
        f"Category keys you must choose from: {cats}.\n\n"
        f"Parts already in the inventory (reuse the exact name if it is the same part):\n"
        + "\n".join(f"- {n}" for n in names)
    )


def suggest_box(data: dict, category: str) -> tuple[int, str]:
    """An existing box of this category with room, else the lowest free number."""
    active = [i for i in data["items"] if i["status"] == "active"]
    per_box = collections.Counter(i["box"] for i in active)

    same_cat = sorted({i["box"] for i in active
                       if i["category"] == category and i["box"] < 400})
    for b in same_cat:
        if per_box[b] < MAX_BOX_ITEMS:
            return b, f"box {b} already holds {category} parts and has room"

    free = [f["box"] for f in data["freeBoxes"] if f["box"] < 400]
    if free:
        return free[0], f"box {free[0]} is free ({[f for f in data['freeBoxes'] if f['box'] == free[0]][0]['reason']})"

    nxt = max((i["box"] for i in active if i["box"] < 400), default=0) + 1
    return nxt, f"box {nxt} is a new number (no free ones left)"


def _gemini(b64: str, media: str, prompt: str, key: str) -> dict:
    """Fallback backend. Same job, same JSON shape — used when Claude is unavailable."""
    import urllib.error
    import urllib.request

    body = json.dumps({
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [
            {"inline_data": {"mime_type": media, "data": b64}},
            {"text": prompt},
        ]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "responseSchema": GEMINI_SCHEMA},
    }).encode("utf-8")

    req = urllib.request.Request(f"{GEMINI_URL}?key={key}", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"gemini {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc

    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"gemini returned no candidate: {json.dumps(payload)[:300]}")
    parts = candidates[0].get("content", {}).get("parts") or []
    text = next((p["text"] for p in parts if "text" in p), None)
    if not text:
        raise RuntimeError(f"gemini returned no text: {json.dumps(candidates[0])[:300]}")
    return json.loads(text)


def identify(client, path: pathlib.Path, context: str, provider: str,
             gemini_key: str | None) -> dict | None:
    media = SUPPORTED.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
    if media not in SUPPORTED.values():
        print(f"  skipped — {path.suffix} is not a supported image type")
        return None

    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    prompt = f"Identify this part.\n\n{context}"

    if provider == "gemini":
        return _gemini(data, media, prompt, gemini_key)

    try:
        return _claude(client, data, media, prompt)
    except Exception as exc:                          # noqa: BLE001
        # An unfunded or unauthorised Claude account should not kill the run when
        # a second vision key is sitting in the same .env.
        recoverable = any(s in str(exc).lower()
                          for s in ("credit balance", "authentication", "permission"))
        if provider == "auto" and recoverable and gemini_key:
            print(f"  claude unavailable ({str(exc)[:60]}…) — falling back to {GEMINI_MODEL}")
            return _gemini(data, media, prompt, gemini_key)
        raise


def _claude(client, data: str, media: str, prompt: str) -> dict | None:
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
                {"type": "text", "text": prompt},
            ],
        }],
    )

    if response.stop_reason == "refusal":
        print("  the model declined to answer for this image")
        return None

    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        print("  no answer came back")
        return None
    return json.loads(text)


def append_rows(rows: list[dict]) -> None:
    shutil.copy2(RAW, RAW.with_suffix(".csv.bak"))
    today = datetime.date.today().strftime("%d/%m/%Y")
    with RAW.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\r\n")
        for r in rows:
            w.writerow([r["box"], r["name"], r["quantity"], r["note"], today])
    print(f"\nappended {len(rows)} row(s) to {RAW.name} (previous kept as inventory_raw.csv.bak)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", help="image files or globs")
    ap.add_argument("--yes", action="store_true", help="accept every proposal without asking")
    ap.add_argument("--dry-run", action="store_true", help="identify only, write nothing")
    ap.add_argument("--provider", choices=["auto", "anthropic", "gemini"], default="auto",
                    help="auto (default) uses Claude and falls back to Gemini if the "
                         "Anthropic account is out of credit")
    args = ap.parse_args()

    paths = [pathlib.Path(p) for pattern in args.images for p in glob.glob(pattern)]
    if not paths:
        sys.exit("no files matched")

    anthropic_key = read_key("ANTHROPIC_API_KEY")
    gemini_key = read_key("GOOGLE_API_KEY")
    if args.provider in {"auto", "anthropic"} and not anthropic_key:
        if args.provider == "anthropic" or not gemini_key:
            sys.exit(f"no ANTHROPIC_API_KEY in {ENV}")
        args.provider = "gemini"
    if args.provider == "gemini" and not gemini_key:
        sys.exit(f"no GOOGLE_API_KEY in {ENV}")

    client = None
    if args.provider != "gemini":
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)

    data = load_inventory()
    context = context_for_prompt(data)
    accepted: list[dict] = []

    for path in paths:
        print(f"\n{path.name}")
        try:
            result = identify(client, path, context, args.provider, gemini_key)
        except Exception as exc:                     # noqa: BLE001 - report and continue
            print(f"  failed: {exc}")
            continue
        if result is None:
            continue

        box, why = suggest_box(data, result["category"])
        print(f"  {result['name']}  x{result['quantity']}  [{result['confidence']} confidence]")
        if result["note"]:
            print(f"  note: {result['note']}")
        if result["matches_existing"]:
            print(f"  !! you may already have this: {result['matches_existing']}")
        print(f"  -> box {box}  ({why})")

        if args.dry_run:
            continue
        if not args.yes:
            answer = input("  file it? [Y]es / [n]o / other box number: ").strip().lower()
            if answer in {"n", "no"}:
                continue
            if answer.isdigit():
                box = int(answer)

        PHOTOS.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "_", result["name"].lower()).strip("_")[:40]
        shutil.copy2(path, PHOTOS / f"{box}_{slug}{path.suffix.lower()}")

        accepted.append({"box": box, "name": result["name"],
                         "quantity": result["quantity"], "note": result["note"]})

    if not accepted:
        print("\nnothing filed")
        return 0

    append_rows(accepted)
    return subprocess.call([sys.executable, str(ROOT / "build.py")])


if __name__ == "__main__":
    raise SystemExit(main())
