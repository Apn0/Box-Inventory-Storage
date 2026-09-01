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

import base64
import csv
import io
import json
import mimetypes
import re
import urllib.error
import urllib.request

import google.auth
import google.auth.transport.requests
from flask import Flask, jsonify, request
from concurrent.futures import ThreadPoolExecutor

from build import CATEGORY_LABELS, categorise, parse_date
from utils import slug

app = Flask(__name__)

SHEET_ID = "1ZVVkmA7tI_kqIUi5O-6cw5Az_qfGmKhydgy2QrFWFDQ"
BOX_GID = 788564724
FORM_GID = 677102738
BOX_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={BOX_GID}"
FORM_CSV_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid={FORM_GID}"

VERTEX_PROJECT = "deft-melody-503207-k8"
VERTEX_LOCATION = "us-central1"
VERTEX_MODEL = "gemini-2.5-flash"

BULK_SENTINEL = 99
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

PART_NUMBER = re.compile(r"^(?:[a-z]{2,}\d{2,}[a-z0-9]*|\d{4,})$")


def _fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode("utf-8-sig", errors="replace")


def resolve_items() -> list[dict]:
    """The same newest-row-wins resolver as build.py, against the live sheet.

    A slimmed-down copy: only the fields identify needs (box/name/qty/status/
    category), not the full app.template.html item shape. If build.py's
    resolver logic changes, mirror it here too.
    """
    with ThreadPoolExecutor(max_workers=2) as executor:
        raw_text, form_text = executor.map(_fetch, [BOX_CSV_URL, FORM_CSV_URL])

    raw_rows = []
    for line_no, row in enumerate(csv.DictReader(io.StringIO(raw_text)), start=2):
        box_txt = (row.get("Box") or "").strip()
        if not box_txt:
            continue
        raw_rows.append({
            "line": line_no, "box": int(box_txt),
            "name": (row.get("Item") or "").strip(),
            "qty_txt": (row.get("Qty") or "").strip(),
            "note": (row.get("Note") or "").strip(),
            "date": parse_date(row.get("UpdatedAt") or ""),
            "time": "00:00:00", "src": 0,
        })

    if form_text.startswith("Timestamp"):
        for line_no, row in enumerate(csv.DictReader(io.StringIO(form_text)), start=2):
            box_txt = (row.get("Box") or "").strip()
            name = (row.get("Item") or "").strip()
            if not box_txt or not name or not box_txt.lstrip("-").isdigit():
                continue
            ts = (row.get("Timestamp") or "").strip()
            date_part, _, time_part = ts.partition(" ")
            try:
                date = parse_date(date_part)
            except ValueError:
                date = None
            raw_rows.append({
                "line": line_no, "box": int(box_txt), "name": name,
                "qty_txt": (row.get("Qty") or "").strip(),
                "note": (row.get("Note") or "").strip(),
                "date": date, "time": time_part or "00:00:01", "src": 1,
            })

    groups: dict[tuple[int, str], list[dict]] = {}
    for row in raw_rows:
        groups.setdefault((row["box"], slug(row["name"])), []).append(row)

    items = []
    for (box, _key), history in groups.items():
        history.sort(key=lambda r: (r["date"] or "", r.get("time", "00:00:00"),
                                    r.get("src", 0), r["line"]))
        latest = history[-1]
        if not latest["name"]:
            continue
        qty_txt = latest["qty_txt"]
        if qty_txt == "":
            count_type, qty = "unknown", None
        elif int(qty_txt) == BULK_SENTINEL:
            count_type, qty = "bulk", None
        else:
            count_type, qty = "exact", int(qty_txt)
        status = "gone" if (count_type == "exact" and qty == 0) else "active"
        note = latest["note"] or next((r["note"] for r in reversed(history) if r["note"]), "")
        items.append({"box": box, "name": latest["name"], "qty": qty,
                      "countType": count_type, "status": status, "note": note,
                      "category": categorise(latest["name"], note)})
    return items


def find_existing(active: list[dict], name: str) -> dict | None:
    """Tolerates how the vision model words a name — see identify.py for why."""
    key = slug(name)
    for item in active:
        if slug(item["name"]) == key:
            return item

    def part_numbers(n: str) -> set[str]:
        return {t for t in slug(n).split() if PART_NUMBER.match(t)}

    wanted = part_numbers(name)
    if wanted:
        hits = [i for i in active if part_numbers(i["name"]) & wanted]
        if len(hits) == 1:
            return hits[0]
    return None


def suggest_box(active: list[dict], category: str) -> int:
    per_box: dict[int, int] = {}
    for i in active:
        per_box[i["box"]] = per_box.get(i["box"], 0) + 1

    same_cat = sorted({i["box"] for i in active if i["category"] == category and i["box"] < 400})
    for b in same_cat:
        if per_box.get(b, 0) < MAX_BOX_ITEMS:
            return b

    used = {i["box"] for i in active if i["box"] < 400}
    b = 1
    while b in used:
        b += 1
    return b


def vertex_token() -> str:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return creds.token


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


@app.route("/", methods=["GET"])
def health():
    return "ok"


@app.route("/identify", methods=["POST"])
def identify():
    media = (request.headers.get("Content-Type") or "").split(";")[0].strip()
    if media not in SUPPORTED:
        media = mimetypes.guess_type(request.headers.get("X-Filename", ""))[0] or "image/jpeg"
    body = request.get_data()
    if not body:
        return jsonify(error="no image"), 400
    b64 = base64.standard_b64encode(body).decode("ascii")

    try:
        items = resolve_items()
    except Exception as exc:                              # noqa: BLE001
        return jsonify(error=f"could not read the sheet: {exc}"), 502

    cats = ", ".join(f"{k} ({v})" for k, v in CATEGORY_LABELS.items())
    names = sorted({i["name"] for i in items if i["status"] == "active"})
    context = (f"Category keys you must choose from: {cats}.\n\n"
              f"Parts already in the inventory (reuse the exact name if it is the same part):\n"
              + "\n".join(f"- {n}" for n in names))
    prompt = f"Identify this part.\n\n{context}"

    try:
        result = call_vertex(b64, media, prompt, vertex_token())
    except Exception as exc:                              # noqa: BLE001
        return jsonify(error=f"identification failed: {exc}"), 502

    seen = max(0, int(result.get("quantity") or 0))

    active = [i for i in items if i["status"] == "active"]

    existing = find_existing(active, result["name"]) or (
        find_existing(active, result["matches_existing"]) if result.get("matches_existing") else None)

    if existing:
        recorded = existing["qty"] if existing["countType"] == "exact" else "many"
        return jsonify(name=result["name"], recordedName=existing["name"], box=existing["box"],
                       recorded=recorded, seen=seen, isNew=False,
                       confidence=result.get("confidence"), note=result.get("note", ""))

    box = suggest_box(active, result.get("category", "misc"))
    return jsonify(name=result["name"], recordedName=result["name"], box=box,
                   recorded=None, seen=seen, isNew=True,
                   confidence=result.get("confidence"), note=result.get("note", ""))
