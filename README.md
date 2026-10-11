# Box Inventory Storage

A Progressive Web App (PWA) replacement for the "Box Inventory Storage" Google Sheet. It tracks numbered component boxes (1–128) and household boxes (401–438).

## What it is
The app replaces the old spreadsheet with a fast, search-first interface. It features one row per part, categories (sensors, power, drivers, etc.), and a "build check" feature to see which boxes to open for a parts list. The app can be installed as a PWA on your phone or desktop, and it supports photo identification.

## How to use
Visit the GitHub Pages deployment url and tap **Add to Home screen** (or install via your desktop browser). It works offline (falling back to a cached copy) but requires a connection to save changes or identify photos. 
- **Search**: Type anything (name, note, category, or box number).
- **Edit**: Tap the + / - buttons to adjust counts.
- **Photos**: Tap the camera icon to identify parts via the Cloud Run service.

## The Google Sheet is the database (Sheet -> Form data flow)
There is no traditional database. 
- **Write**: Every edit (count change, undo) is a hidden POST to a linked Google Form. It acts as an append-only log. 
- **Read**: The app (via `sync.py`) fetches the `BOX` tab and the `Form responses` tab as CSV directly from Google. The logic merges the logs, resolving collisions by a "newest row wins" strategy. 

## Rebuilding the snapshot
If you make manual changes to the Google Sheet or change the python code, you need to rebuild the static site.
```bash
python sync.py
python build.py
```
This fetches the latest data and builds the static `index.html` alongside `inventory.json`. 

## Deployment
- **Frontend (GitHub Pages)**: The app is deployed as a static site via GitHub Pages directly from the `main` branch (root directory). There is no GitHub Actions build step (Actions minutes are exhausted).
- **Photo ID (Cloud Run)**: The camera button posts to the stateless `box-identify` Cloud Run service. This service fetches the live sheet, runs the resolver, asks Vertex AI to identify the photo, and returns a proposal to the PWA.
