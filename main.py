"""Cloud Run service: photo -> identified part.

Stateless on purpose — every request re-fetches the live Google Sheet, runs it
through the same resolver logic as build.py, asks Vertex AI to identify the
photo, and returns a proposal. It never writes anything: the phone confirms
the count and appends to the sheet itself via the Form, exactly like a typed
entry. This means the box-inventory app needs no PC running to identify a
photo — only to build/deploy this service.

Auth to Vertex is the Cloud Run service's own identity (Application Default
Credentials), granted roles/aiplatform.user on deft-melody-503207-k8 at
deploy time — no key, no gcloud login needed at request time.
"""
from __future__ import annotations

import os
import base64
import hmac
import json
import logging
import mimetypes
import pathlib
import threading
import urllib.error
import urllib.request

import google.auth
import google.auth.transport.requests
import google.auth.exceptions
from flask import Flask, jsonify, request
from concurrent.futures import ThreadPoolExecutor

from inventory_core.resolver import (
    CATEGORY_LABELS, categorise, find_full_boxes, part_numbers,
    parse_raw_rows, build_items
)
from utils import slug

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024

ROOT = pathlib.Path(__file__).resolve().parent
config_file = ROOT / "config.json"
if config_file.exists():
    try:
        _cfg = json.loads(config_file.read_text(encoding="utf-8"))
        SHEET_ID = _cfg.get("sheet_id", "1ZVVkmA7tI_kqIUi5O-6cw5Az_qfGmKhydgy2QrFWFDQ")
        BOX_GID = int(_cfg.get("box_gid", 788564724))
        FORM_GID = int(_cfg.get("form_gid", 677102738))
    except Exception:
        SHEET_ID = "1ZVVkmA7tI_kqIUi5O-6cw5Az_qfGmKhydgy2QrFWFDQ"
        BOX_GID = 788564724
        FORM_GID = 677102738
else:
    SHEET_ID = "1ZVVkmA7tI_kqIUi5O-6cw5Az_qfGmKhydgy2QrFWFDQ"
    BOX_GID = 788564724
    FORM_GID = 677102738

BOX_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={BOX_GID}"
FORM_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={FORM_GID}"

VERTEX_PROJECT = "deft-melody-503207-k8"
VERTEX_LOCATION = "us-central1"
VERTEX_MODEL = "gemini-2.5-flash"

MAX_BOX_ITEMS = 6           # keep in step with identify.py / the app's reorganise cap

SUPPORTED = {"image/jpeg", "image/png", "image/gif", "image/webp"}

SYSTEM = (
    "You identify loose electronic components and hardware from photos, for a "
    "hobbyist's parts inventory. Name parts the way a supplier would: chip or "
    "module designation first, then what it is. Say what you can actually see — "
    "if the marking is unreadable, describe the part generically and set "
    "confidence to low rather than guessing a part number."
)

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


def _fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8-sig", errors="replace")


def resolve_items() -> list[dict]:
    with ThreadPoolExecutor(max_workers=2) as executor:
        raw_text, form_text = list(executor.map(_fetch, [BOX_CSV_URL, FORM_CSV_URL]))

    raw_rows = parse_raw_rows(raw_text, form_text)
    items = build_items(raw_rows)
    full = set(find_full_boxes(raw_rows, items))
    for i in items:
        i["boxFull"] = i["box"] in full
    return items


def find_existing_part(active: list[dict], name: str) -> dict | None:
    """Tolerates how the vision model words a name — see identify.py for why."""
    key = slug(name)
    for item in active:
        if slug(item["name"]) == key:
            return item

    wanted = part_numbers(name)
    if not wanted:
        return None

    hit = None
    for item in active:
        if not wanted.isdisjoint(slug(item["name"]).split()):
            if hit is not None:
                return None
            hit = item
    return hit


def propose_box(active: list[dict], category: str) -> int:
    per_box: dict[int, int] = {}
    same_cat = set()
    full = set()

    for i in active:
        box = i["box"]
        per_box[box] = per_box.get(box, 0) + 1

        if i.get("boxFull"):
            full.add(box)

        if box < 400:
            if i["category"] == category:
                same_cat.add(box)

    for b in sorted(same_cat - full):     # a box marked full takes nothing more
        if per_box.get(b, 0) < MAX_BOX_ITEMS:
            return b

    b = 1
    while b in per_box and b < 400:
        b += 1
    return b


_vertex_creds = None
_vertex_lock = threading.Lock()
def vertex_token() -> str:
    global _vertex_creds
    with _vertex_lock:
        if _vertex_creds is None or not _vertex_creds.valid:
            if _vertex_creds is None:
                _vertex_creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            _vertex_creds.refresh(google.auth.transport.requests.Request())
        return _vertex_creds.token


def call_vertex(b64: str, media: str, prompt: str, token: str) -> dict:
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
        with urllib.request.urlopen(req, timeout=60) as r:
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


@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    if origin and (
        origin in ["https://apn0.github.io", "http://localhost", "http://127.0.0.1"]
        or origin.startswith((
            "http://localhost:", "http://127.0.0.1:", "http://192.168.", "http://10.", "http://172."
        ))
    ):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Filename"
        response.headers["Access-Control-Max-Age"] = "86400"
    return response


@app.route("/", methods=["GET"])
def health():
    return "ok"


@app.route("/identify", methods=["POST", "OPTIONS"])
def identify():
    if request.method == "OPTIONS":
        return "", 204

    expected_key = os.environ.get("API_KEY")
    auth_header = request.headers.get("Authorization", "")
    if not expected_key or not auth_header.startswith("Bearer ") \
            or not hmac.compare_digest(auth_header[7:], expected_key):
        # We read and discard the body so gunicorn does not drop the connection
        # with an unread body, which would result in a 502/503 for the client.
        _ = request.get_data()
        return jsonify(error="unauthorized"), 401

    body = request.get_data()
    media = (request.headers.get("Content-Type") or "").split(";")[0].strip()
    if media not in SUPPORTED:
        media = mimetypes.guess_type(request.headers.get("X-Filename", ""))[0] or "image/jpeg"
    if not body:
        return jsonify(error="no image"), 400
    b64 = base64.standard_b64encode(body).decode("ascii")

    try:
        items = resolve_items()
    except (urllib.error.URLError, ValueError) as exc:
        logging.error("could not read the sheet: %s", exc)
        return jsonify(error="could not read the sheet"), 502

    cats = ", ".join(f"{k} ({v})" for k, v in CATEGORY_LABELS.items())
    active = [i for i in items if i["status"] == "active"]
    names = sorted({i["name"] for i in active})
    context = (f"Category keys you must choose from: {cats}.\n\n"
              f"Parts already in the inventory (reuse the exact name if it is the same part):\n"
              + "\n".join(f"- {n}" for n in names))
    prompt = f"Identify this part.\n\n{context}"

    try:
        result = call_vertex(b64, media, prompt, vertex_token())
    except (google.auth.exceptions.GoogleAuthError, urllib.error.URLError, RuntimeError, ValueError) as exc:
        logging.error("identification failed: %s", exc)
        return jsonify(error="identification failed"), 502

    seen = max(0, int(result.get("quantity") or 0))

    existing = find_existing_part(active, result["name"]) or (
        find_existing_part(active, result["matches_existing"]) if result.get("matches_existing") else None)

    if existing:
        recorded = existing["qty"] if existing["countType"] == "exact" else ("many" if existing["countType"] == "bulk" else None)
        return jsonify(name=result["name"], recordedName=existing["name"], box=existing["box"],
                       recorded=recorded, seen=seen, isNew=False,
                       boxFull=bool(existing.get("boxFull")),
                       confidence=result.get("confidence"), note=result.get("note", ""))

    box = propose_box(active, result.get("category", "misc"))
    return jsonify(name=result["name"], recordedName=result["name"], box=box,
                   recorded=None, seen=seen, isNew=True,
                   confidence=result.get("confidence"), note=result.get("note", ""))
