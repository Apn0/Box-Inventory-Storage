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
import typing
import dataclasses
import datetime
import glob
import io
import json
import logging
import mimetypes
import pathlib
import re
import shutil
import subprocess
import sys

from build import part_numbers
from utils import slug

ROOT = pathlib.Path(__file__).resolve().parent
RAW = ROOT / "data" / "inventory_raw.csv"
INVENTORY = ROOT / "data" / "inventory.json"
PHOTOS = ROOT / "data" / "photos"
INBOX = (ROOT / "data" / "inbox").resolve()
# Identified but not confident enough to file unattended. Kept separate from the
# inbox so a server restart does not pay to identify them all over again.
REVIEW = (ROOT / "data" / "review").resolve()
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


# Written into the Note of every row this script appends. build.py reads it to
# tell a deliberate recount from the sheet's unexplained restatements, so filing
# a photo does not raise a false "ambiguous quantity" every time.
COUNTED_MARK = "photo-counted"

OPENAI_MODEL = "gpt-4o"
GEMINI_MODEL = "gemini-2.5-flash"

# Vertex AI on the separate Google account that holds the credits. Auth comes
# from gcloud, so no key for it lives in .env.
VERTEX_ACCOUNT = "peterfrissen123@gmail.com"
VERTEX_PROJECT = "deft-melody-503207-k8"
VERTEX_LOCATION = "us-central1"
VERTEX_MODEL = "gemini-2.5-flash"
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


_env_cache = None
_env_mtime = 0.0

import os
def read_key(name: str) -> str | None:
    global _env_cache, _env_mtime
    if name in os.environ:
        return os.environ[name]
    if not ENV.exists():
        return None

    mtime = ENV.stat().st_mtime
    if _env_cache is None or mtime > _env_mtime:
        _env_cache = {}
        for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if "=" in line:
                k, v = line.split("=", 1)
                _env_cache[k.strip()] = v.strip() or None
        _env_mtime = mtime

    return _env_cache.get(name)


_inventory_cache = None

def load_inventory() -> dict:
    global _inventory_cache
    if _inventory_cache is not None:
        return _inventory_cache

    if not INVENTORY.exists():
        sys.exit(f"missing {INVENTORY} — run build.py first")

    _inventory_cache = json.loads(INVENTORY.read_text(encoding="utf-8"))
    return _inventory_cache


def context_for_prompt(data: dict, active: list[dict]) -> str:
    """A compact view of what already exists, so the model reuses naming and spots duplicates."""
    cats = ", ".join(f"{k} ({v})" for k, v in data["meta"]["categoryLabels"].items())
    names = sorted({i["name"] for i in active})
    return (
        f"Category keys you must choose from: {cats}.\n\n"
        f"Parts already in the inventory (reuse the exact name if it is the same part):\n"
        + "\n".join(f"- {n}" for n in names)
    )




def find_existing_part(active: list[dict], name: str) -> dict | None:
    """The active record for this part, tolerating how the model words it.

    Vision models do not name a part identically twice — the same board came
    back as "TMC2209 stepper driver" and "TMC2209-LA stepper driver module".
    Exact matching alone therefore files a second row for a part already on
    record, and the inventory drifts apart one photo at a time.
    """
    key = slug(name)
    wanted = part_numbers(name)

    hit = None
    ambiguous = False

    for item in active:
        item_name = item["name"]

        if slug(item_name) == key:                        # exact wins
            return item

        if wanted and not ambiguous:                      # then the part number
            if not wanted.isdisjoint(part_numbers(item_name)):
                if hit is not None:
                    # Several boxes carry this part number — too ambiguous to pick one.
                    ambiguous = True
                else:
                    hit = item

    if ambiguous or not wanted:
        return None

    return hit


def propose_box(data: dict, active: list[dict], category: str) -> tuple[int, str]:
    """An existing box of this category with room, else the lowest free number."""
    per_box = {}
    same_cat = set()

    for i in active:
        b = i["box"]
        per_box[b] = per_box.get(b, 0) + 1
        if b < 400 and i.get("category") == category:
            same_cat.add(b)

    for b in sorted(same_cat):
        if per_box[b] < MAX_BOX_ITEMS:
            return b, f"box {b} already holds {category} parts and has room"

    free = [f["box"] for f in data["freeBoxes"] if f["box"] < 400]
    if free:
        return free[0], f"box {free[0]} is free ({[f for f in data['freeBoxes'] if f['box'] == free[0]][0]['reason']})"

    nxt = max((b for b in per_box if b < 400), default=0) + 1
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


def vertex_token() -> str | None:
    """Access token for the credit-holding account, straight from gcloud."""
    try:
        out = subprocess.run(
            ["gcloud", "auth", "print-access-token", f"--account={VERTEX_ACCOUNT}"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    token = out.stdout.strip()
    return token or None


def _vertex(b64: str, media: str, prompt: str, token: str) -> dict:
    """Preferred backend: bills the Vertex credits, not a personal API key."""
    import urllib.error
    import urllib.request

    url = (f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1/projects/"
           f"{VERTEX_PROJECT}/locations/{VERTEX_LOCATION}/publishers/google/"
           f"models/{VERTEX_MODEL}:generateContent")

    body = json.dumps({
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [
            {"inlineData": {"mimeType": media, "data": b64}},
            {"text": prompt},
        ]}],
        "generationConfig": {"responseMimeType": "application/json",
                             "responseSchema": GEMINI_SCHEMA},
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"vertex {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc

    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"vertex returned no candidate: {json.dumps(payload)[:300]}")
    parts = candidates[0].get("content", {}).get("parts") or []
    text = next((p["text"] for p in parts if "text" in p), None)
    if not text:
        raise RuntimeError(f"vertex returned no text: {json.dumps(candidates[0])[:300]}")
    return json.loads(text)


def _openai(b64: str, media: str, prompt: str, key: str) -> dict:
    """Second fallback. Same job, same JSON shape."""
    import urllib.error
    import urllib.request

    body = json.dumps({
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:{media};base64,{b64}"}},
            ]},
        ],
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "part", "strict": True, "schema": SCHEMA}},
        "max_tokens": 900,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"openai {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}") from exc

    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"openai returned no choice: {json.dumps(payload)[:300]}")
    return json.loads(choices[0]["message"]["content"])


@dataclasses.dataclass
class IdentifyConfig:
    client: typing.Any
    context: str
    provider: str
    gemini_key: str | None
    openai_key: str | None = None


def identify(path: pathlib.Path, config: IdentifyConfig) -> dict | None:
    media = SUPPORTED.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
    if media not in SUPPORTED.values():
        print(f"  skipped — {path.suffix} is not a supported image type")
        return None

    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    prompt = f"Identify this part.\n\n{config.context}"

    if config.provider == "gemini":
        return _gemini(data, media, prompt, config.gemini_key)
    if config.provider == "openai":
        return _openai(data, media, prompt, config.openai_key)
    if config.provider == "vertex":
        return _vertex(data, media, prompt, vertex_token())

    # provider == "auto": Vertex first — it spends the credits on the separate
    # Google account rather than a personal API key. Then walk the rest, skipping
    # any account that turns out to be unfunded: a key being present in .env and
    # a key being usable are different things.
    chain = [(f"vertex/{VERTEX_MODEL}",
              lambda: _vertex(data, media, prompt, vertex_token()), vertex_token())]
    chain.append(("claude", lambda: _claude(config.client, data, media, prompt), config.client))
    chain.append((GEMINI_MODEL, lambda: _gemini(data, media, prompt, config.gemini_key), config.gemini_key))
    chain.append((OPENAI_MODEL, lambda: _openai(data, media, prompt, config.openai_key), config.openai_key))

    last: Exception | None = None
    for name, call, available in chain:
        if not available:
            continue
        try:
            if last is not None:
                print(f"  trying {name}…")
            return call()
        except Exception as exc:                      # noqa: BLE001
            if not _recoverable(exc):
                raise
            print(f"  {name} unavailable: {_reason(exc)}")
            last = exc
    if last:
        raise last
    raise RuntimeError("no vision API key available")


def _recoverable(exc: Exception) -> bool:
    """True when another provider is worth trying: billing, auth, or quota."""
    text = str(exc).lower()
    return any(s in text for s in (
        "credit balance", "credits are depleted", "insufficient_quota", "quota",
        "authentication", "permission", "unauthorized", "billing",
        " 401", " 403", " 429"))


def _reason(exc: Exception) -> str:
    text = str(exc)
    for probe in ("credit balance is too low", "prepayment credits are depleted",
                  "insufficient_quota", "exceeded your current quota",
                  "invalid_api_key", "Incorrect API key"):
        if probe.lower() in text.lower():
            return probe
    return text[:80]


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


def decide(data: dict, active: list[dict], result: dict) -> dict:
    """Where the identified part goes, and what quantity the appended row carries.

    A part already on record must be written as the NEW TOTAL, never the delta:
    rows resolve newest-wins per (box, item), so appending "1" to a stock of 5
    would silently replace it with 1.
    """
    qty = max(0, int(result["quantity"]))

    existing = find_existing_part(active, result["name"]) or (
        find_existing_part(active, result["matches_existing"]) if result["matches_existing"] else None)

    if existing and existing["countType"] == "exact":
        total = int(existing["qty"]) + qty
        return {"box": existing["box"], "name": existing["name"], "quantity": total,
                "existing": True, "from": existing["qty"], "to": total,
                "why": f"already in box {existing['box']} — count goes {existing['qty']} -> {total}"}
    if existing:
        return {"box": existing["box"], "name": existing["name"], "quantity": "many",
                "existing": True, "from": None, "to": None,
                "why": f"already in box {existing['box']} as a bulk pile — left as 'many'"}

    box, why = propose_box(data, active, result["category"])
    return {"box": box, "name": result["name"], "quantity": qty,
            "existing": False, "from": None, "to": qty, "why": why}


def archive_name(box: int, name: str, suffix: str) -> pathlib.Path:
    """A free filename in the photo archive.

    Never reuse one: the slug is derived from box + part name, so re-filing the
    same part — or a misidentification that lands on an existing name — would
    silently replace an earlier photo. One was lost that way before this.
    """
    PHOTOS.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40]
    target = PHOTOS / f"{box}_{slug}{suffix}"
    n = 2
    while target.exists():
        target = PHOTOS / f"{box}_{slug}_{n}{suffix}"
        n += 1
    return target


def file_one(path: pathlib.Path, result: dict, plan: dict) -> dict:
    """Archive the photo, take it out of the queue, and return the row to append."""
    shutil.copy2(path, archive_name(plan["box"], plan["name"], path.suffix.lower()))
    # Out of the queue, or the next run identifies it all over again. Moved,
    # never deleted — the archived copy above is the keeper.
    if INBOX in path.resolve().parents:
        path.unlink()

    note = result["note"].strip()
    note = f"{note} ({COUNTED_MARK})" if note else f"({COUNTED_MARK})"
    return {"box": plan["box"], "name": plan["name"],
            "quantity": plan["quantity"], "note": note}


# The model saying it cannot tell is a valid answer, and it must not become an
# inventory row. Filing unattended wrote "No identifiable components" and a
# handful of drink-can pull tabs into box 52 before this gate existed.
UNSURE = re.compile(
    r"no identifiable|unidentifi|unclear|cannot (be )?(determine|identify)|"
    r"not (a )?(component|part)|unknown object|nothing (visible|identifiable)|"
    r"blurry|too dark|indistinct", re.I)


def auto_filable(result: dict, plan: dict) -> str | None:
    """Reason to hold a photo back for review, or None when it is safe to file."""
    if result.get("confidence") != "high":
        return f"{result.get('confidence', 'unknown')} confidence"
    if UNSURE.search(result.get("name", "")) or UNSURE.search(result.get("note", "")):
        return "the model could not identify it"
    if int(result.get("quantity") or 0) <= 0:
        return "nothing countable in the photo"
    if not plan["existing"]:
        # A new part means a new row and a new box. Worth ten seconds of your
        # eyes; a wrong one is far more annoying to unpick than to confirm.
        return "new item, requires visual check"
    return None


PENDING = ROOT / "data" / "pending.json"

_pending_cache = None

def load_pending() -> list[dict]:
    global _pending_cache
    if _pending_cache is not None:
        return _pending_cache

    if not PENDING.exists():
        _pending_cache = []
        return _pending_cache
    try:
        _pending_cache = json.loads(PENDING.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _pending_cache = []
    return _pending_cache


def save_pending(entries: list[dict]) -> None:
    global _pending_cache
    _pending_cache = entries
    PENDING.parent.mkdir(parents=True, exist_ok=True)
    PENDING.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


FORM_ACTION = ("https://docs.google.com/forms/d/e/1FAIpQLSfaLSRumcvZL1JtLMCsILnac0PIuKb9k"
               "EePiOvndgu1jlUsIQ/formResponse")
FORM_ENTRIES = {"box": "entry.2127766863", "name": "entry.957000781",
                "qty": "entry.971108864", "note": "entry.1227292805"}
FORM_MIRROR = ROOT / "data" / "form_responses.csv"


def post_to_form(box: int, name: str, qty, note: str) -> bool:
    """Append the row to the Google Sheet via the form — the same write path the
    phone uses, so every count lands in the cloud regardless of which device
    made it. Returns False (rather than raising) when offline."""
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode({
        FORM_ENTRIES["box"]: str(box), FORM_ENTRIES["name"]: name,
        FORM_ENTRIES["qty"]: str(qty), FORM_ENTRIES["note"]: note or "",
    }).encode("utf-8")
    try:
        with urllib.request.urlopen(
                urllib.request.Request(FORM_ACTION, data=data), timeout=20) as r:
            ok = 200 <= r.status < 300
    except Exception:                                  # noqa: BLE001 - offline is normal
        return False
    if ok:
        # Mirror it locally at once: the rebuild that follows must see this row
        # now, not whenever the sheet export next gets fetched.
        FORM_MIRROR.parent.mkdir(parents=True, exist_ok=True)
        new = not FORM_MIRROR.exists()
        with FORM_MIRROR.open("a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\r\n")
            if new:
                w.writerow(["Timestamp", "Box", "Item", "Qty", "Note"])
            w.writerow([datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
                        box, name, qty, note or ""])
    return ok


def commit(entry: dict, qty, box: int | None = None, name: str | None = None) -> dict:
    """Write the count the user confirmed. Their number is the truth, not a sum.

    The row carries the count as an absolute total, which is what the resolver
    wants anyway (newest row wins per box+item) — so a part quietly taken out
    and put back corrects itself instead of drifting.
    """
    data = load_inventory()
    box = int(box if box is not None else entry["box"])
    name = (name or entry["name"]).strip()

    # If the confirmed name matches something already on record, write against
    # that record's spelling and box so a variant name cannot fork the entry.
    active = [i for i in data["items"] if i["status"] == "active"]
    existing = find_existing_part(active, name)
    if existing:
        name, box = existing["name"], existing["box"]

    note = (entry.get("note") or "").strip()
    note = f"{note} ({COUNTED_MARK})" if note else f"({COUNTED_MARK})"

    photo = entry.get("photo")            # typed entries have none
    if photo:
        src = REVIEW / photo
        if src.exists():
            shutil.move(str(src), str(archive_name(box, name, src.suffix.lower())))

    quantity = "many" if qty in (None, "many") else int(qty)
    # The sheet is the database: write there first, exactly like the phone does.
    # Only when offline does the row go to the local CSV instead — sync.py
    # reconciles later, and a duplicate is a harmless restatement.
    if not post_to_form(box, name, quantity, note):
        append_rows([{"box": box, "name": name, "quantity": quantity, "note": note}])
    subprocess.run([sys.executable, str(ROOT / "build.py")], capture_output=True, text=True)
    global _inventory_cache
    _inventory_cache = None
    return {"box": box, "name": name, "quantity": qty}


def _create_config(provider: str, context: str) -> IdentifyConfig:
    client = None
    anthropic_key = read_key("ANTHROPIC_API_KEY")
    if provider in {"auto", "anthropic"} and anthropic_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
        except ImportError:
            logging.warning("anthropic SDK not installed — skipping Claude")

    return IdentifyConfig(
        client=client,
        context=context,
        provider=provider,
        gemini_key=read_key("GOOGLE_API_KEY"),
        openai_key=read_key("OPENAI_API_KEY")
    )


def _process_single_photo(
    path: pathlib.Path, data: dict, active: list[dict], config: IdentifyConfig, unattended: bool
) -> tuple[dict, dict | None]:
    try:
        result = identify(path, config)
    except Exception as exc:                          # noqa: BLE001
        return {"photo": path.name, "ok": False, "error": str(exc)[:200]}, None

    if result is None:
        return {"photo": path.name, "ok": False, "error": "no answer"}, None

    plan = decide(data, active, result)
    outcome = {"photo": path.name, "ok": True,
               "name": plan["name"], "box": plan["box"],
               "confidence": result["confidence"], "note": result["note"],
               "existing": plan["existing"],
               "from": plan["from"], "to": plan["to"],
               "why": plan["why"]}

    row = None
    if unattended:
        # Never write a count unattended. What is actually in the box is
        # something only you can see — you may have taken parts out without
        # logging it, so an increment would quietly drift from reality.
        # The photo becomes a question with the recorded number filled in.
        REVIEW.mkdir(parents=True, exist_ok=True)
        if INBOX in path.resolve().parents:
            shutil.move(str(path), str(REVIEW / path.name))

        existing = find_existing_part(active, result["name"]) or (
            find_existing_part(active, result["matches_existing"])
            if result["matches_existing"] else None)
        outcome.update(
            filed=False,
            recorded=(existing["qty"] if existing and existing["countType"] == "exact"
                      else ("many" if existing else None)),
            recordedName=existing["name"] if existing else None,
            seen=int(result["quantity"] or 0),
            category=result.get("category", "misc"))
    else:
        row = file_one(path, result, plan)
        outcome.update(filed=True)

    return outcome, row


def process(paths, provider: str = "auto", unattended: bool = False) -> list[dict]:
    """Identify and file every photo, no prompting. Used by server.py.

    With unattended=True, only confident matches to parts already on record are
    written; anything else is left in the queue and reported for review.

    Returns one outcome per photo so the caller can report what happened,
    rather than the caller having to scrape stdout.
    """
    data = load_inventory()
    active = [i for i in data["items"] if i["status"] == "active"]
    context = context_for_prompt(data, active)
    config = _create_config(provider, context)

    outcomes, rows = [], []
    for path in paths:
        path = pathlib.Path(path)
        outcome, row = _process_single_photo(path, data, active, config, unattended)
        outcomes.append(outcome)
        if row is not None:
            rows.append(row)

    if rows:
        append_rows(rows)
        subprocess.run([sys.executable, str(ROOT / "build.py")],
                       capture_output=True, text=True)
        global _inventory_cache
        _inventory_cache = None
    return outcomes


CHANGES = ROOT / "data" / "changes.json"
MAX_CHANGES = 200

_changes_cache = None

def load_changes() -> list[dict]:
    global _changes_cache
    if _changes_cache is not None:
        return _changes_cache

    if not CHANGES.exists():
        _changes_cache = []
        return _changes_cache
    try:
        _changes_cache = json.loads(CHANGES.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _changes_cache = []
    return _changes_cache


def record_change(rows: list[dict], lines: list[str]) -> None:
    """Remember exactly what was appended, so it can be taken back off again."""
    global _changes_cache
    log = load_changes()
    log.append({"at": datetime.datetime.now().isoformat(timespec="seconds"),
                "rows": rows, "lines": lines})
    del log[:-MAX_CHANGES]
    _changes_cache = log
    CHANGES.parent.mkdir(parents=True, exist_ok=True)
    CHANGES.write_text(json.dumps(log, indent=2, ensure_ascii=False), encoding="utf-8")


def undo_last() -> dict | None:
    """Remove the most recent append, but only if the file still ends with it.

    Refusing when the tail does not match is the point: the CSV is also edited
    by hand and re-exported from the sheet, and silently deleting somebody
    else's lines would be far worse than declining to undo.
    """
    log = load_changes()
    if not log:
        return None
    last = log[-1]

    text = RAW.read_text(encoding="utf-8-sig")
    tail = "".join(f"{line}\r\n" for line in last["lines"])
    if not text.endswith(tail):
        alt = "".join(f"{line}\n" for line in last["lines"])
        if not text.endswith(alt):
            raise RuntimeError("the file changed since then — undo would remove the wrong lines")
        tail = alt

    shutil.copy2(RAW, RAW.with_suffix(".csv.bak"))
    RAW.write_text(text[:-len(tail)], encoding="utf-8", newline="")
    global _changes_cache
    _changes_cache = log[:-1]
    CHANGES.write_text(json.dumps(_changes_cache, indent=2, ensure_ascii=False), encoding="utf-8")
    subprocess.run([sys.executable, str(ROOT / "build.py")], capture_output=True, text=True)
    global _inventory_cache
    _inventory_cache = None
    return last


def append_rows(rows: list[dict]) -> None:
    shutil.copy2(RAW, RAW.with_suffix(".csv.bak"))

    # The sheet export does not always end with a newline. Appending straight
    # onto it glues the new row to the last one and corrupts both — the date
    # field became "12/05/202613" the first time this ran.
    tail = RAW.read_bytes()[-1:] if RAW.stat().st_size else b"\n"
    if tail not in (b"\n", b"\r"):
        with RAW.open("ab") as fh:
            fh.write(b"\r\n")

    today = datetime.date.today().strftime("%d/%m/%Y")
    written = []
    with RAW.open("a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\r\n")
        for r in rows:
            buf = io.StringIO()
            csv.writer(buf, lineterminator="").writerow(
                [r["box"], r["name"], r["quantity"], r["note"], today])
            written.append(buf.getvalue())
            fh.write(buf.getvalue() + "\r\n")
    record_change(rows, written)
    print(f"\nappended {len(rows)} row(s) to {RAW.name} (previous kept as inventory_raw.csv.bak)")


def parse_args(args_list: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", nargs="+", help="image files or globs")
    ap.add_argument("--yes", action="store_true", help="accept every proposal without asking")
    ap.add_argument("--dry-run", action="store_true", help="identify only, write nothing")
    ap.add_argument("--provider",
                    choices=["auto", "vertex", "anthropic", "gemini", "openai"],
                    default="auto",
                    help="auto (default) tries Vertex first — it spends the credits "
                         "on the separate Google account instead of a personal API "
                         "key — then Claude, Gemini, OpenAI, skipping any that is "
                         "out of credit")
    return ap.parse_args(args_list)


def run(args: argparse.Namespace) -> int:
    paths = [pathlib.Path(p) for pattern in args.images for p in glob.glob(pattern)]
    if not paths:
        sys.exit("no files matched")

    anthropic_key = read_key("ANTHROPIC_API_KEY")
    gemini_key = read_key("GOOGLE_API_KEY")
    openai_key = read_key("OPENAI_API_KEY")

    # Vertex is deliberately absent here: it authenticates through gcloud, so it
    # needs no key in .env at all.
    required = {"anthropic": ("ANTHROPIC_API_KEY", anthropic_key),
                "gemini": ("GOOGLE_API_KEY", gemini_key),
                "openai": ("OPENAI_API_KEY", openai_key)}
    if args.provider == "vertex":
        if not vertex_token():
            sys.exit(f"gcloud has no usable token for {VERTEX_ACCOUNT} — "
                     f"run: gcloud auth login {VERTEX_ACCOUNT}")
    elif args.provider != "auto":
        name, value = required[args.provider]
        if not value:
            sys.exit(f"no {name} in {ENV}")
    elif not any((anthropic_key, gemini_key, openai_key, vertex_token())):
        sys.exit(f"no vision credentials at all (no gcloud token, no key in {ENV})")

    client = None
    if args.provider in {"auto", "anthropic"} and anthropic_key:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=anthropic_key)
        except ImportError:
            if args.provider == "anthropic":
                sys.exit("pip install anthropic")
            print("  anthropic SDK not installed — skipping Claude")

    data = load_inventory()
    active = [i for i in data["items"] if i["status"] == "active"]
    context = context_for_prompt(data, active)
    accepted: list[dict] = []
    config = IdentifyConfig(
        client=client,
        context=context,
        provider=args.provider,
        gemini_key=gemini_key,
        openai_key=openai_key
    )

    for path in paths:
        print(f"\n{path.name}")
        try:
            result = identify(path, config)
        except Exception as exc:                     # noqa: BLE001 - report and continue
            print(f"  failed: {exc}")
            continue
        if result is None:
            continue

        plan = decide(data, active, result)
        print(f"  {result['name']}  x{result['quantity']}  [{result['confidence']} confidence]")
        if result["note"]:
            print(f"  note: {result['note']}")
        print(f"  -> box {plan['box']}  ({plan['why']})")

        if args.dry_run:
            continue
        if not args.yes:
            answer = input("  file it? [Y]es / [n]o / other box number: ").strip().lower()
            if answer in {"n", "no"}:
                continue
            if answer.isdigit():
                plan["box"] = int(answer)

        accepted.append(file_one(path, result, plan))

    if not accepted:
        print("\nnothing filed")
        return 0

    append_rows(accepted)
    return subprocess.call([sys.executable, str(ROOT / "build.py")])


def main() -> int:
    args = parse_args()
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
