# LeadBot v2

A free, no-billing-required agent that finds real local businesses by
city/state + niche, checks their own website for public contact info,
and accumulates everything into a shared Google Sheet (or local CSV)
without ever overwriting what's already there.

## What changed from v1 (and why)

| Bug in v1 | Fix in v2 |
|---|---|
| UI never geocoded a bbox, so every run hit an OSM query path that used `out center;` instead of `out center tags;` — business names came back empty and got silently dropped | Geocoding always happens first (`geocode.py`); the OSM query (`sources.py`) always requests tags |
| Google Places was wired into the config but explicitly filtered out in `main.py` — never actually ran | Removed entirely (no billing/card, per your call) — OpenStreetMap only |
| State-sized regions sent straight to Overpass → timeouts, silent empty results | `geocode.split_bbox()` tiles large regions into Overpass-sized chunks |
| `robots.txt` fetch failure = treated as "disallowed", so legit small-business sites got skipped | Fails **open** (allowed) on any fetch error — see `policy.py` |
| A single 429 permanently blocked a host for the rest of the run | Exponential backoff + bounded retries instead (`retry_request`) |
| No daily API-quota tracking, only per-request pacing | `QuotaTracker` persists a daily count per provider and stops with a buffer before the real limit |
| Output CSV was overwritten (`"w"` mode) every run | `storage.py` reads what's already there and appends only genuinely new leads, matched by a single consistent `dedup_key` |
| "clinic"/"restaurant" had to be typed as exact raw OSM tags in the UI | `niche_map.json` maps plain-English niches to OSM tags; UI shows a dropdown |
| Wikipedia/DuckDuckGo sources produced irrelevant/fragile results | Removed — OpenStreetMap + each business's own website is the source of truth |

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp config.example.json config.json
cp .env.example .env
```

`GEOAPIFY_API_KEY` in `.env` is optional — leave it blank and LeadBot uses
free Nominatim geocoding automatically. Adding a free Geoapify key (no
card, 3000 req/day) just improves geocoding accuracy.

## Google Sheets setup (free, no credit card)

1. Go to https://console.cloud.google.com, create a project.
2. Enable the **Google Sheets API** and **Google Drive API** for it (search each in the top search bar → Enable).
3. Go to "APIs & Services" → "Credentials" → "Create Credentials" → **Service Account**. Give it any name.
4. Open the service account → "Keys" tab → "Add Key" → JSON. This downloads a `.json` file — save it somewhere safe, e.g. `leadbot-service-account.json`.
5. Create (or open) your Google Sheet. Click **Share**, and share it with the service account's email (looks like `something@your-project.iam.gserviceaccount.com`) as an **Editor**.
6. In `config.json`, set:
   ```json
   "google_sheet_id": "the-long-id-in-the-sheet's-url",
   "google_service_account_file": "leadbot-service-account.json"
   ```
7. All 4 of you open the same Sheet URL — real-time shared, free.

If you skip this setup, LeadBot automatically falls back to writing/appending to a local `leads.csv`.

## Running

Edit `config.json`'s `"queries"` list — each entry is one `{country, region, niche}` search. **Prefer city-level regions over whole states** (see the runtime note below).

```bash
python -m leadbot.main --config config.json
```

Or use the web form:

```bash
python -m leadbot.ui
```
Then open http://127.0.0.1:8080, pick country/region/niche from the dropdown, and click run. It writes `config.json` and runs the same pipeline.

## An honest note on runtime

This is a **free, no-card, respectful-of-rate-limits** tool — that means it is not instant. Overpass (OpenStreetMap's free query engine) needs a few seconds of pacing between requests. A single city query takes well under a minute. A whole US state gets automatically split into many small tiles so it never times out or gets your IP blocked, but that can take 15-30+ minutes for one niche. **For faster, more targeted results, list several major cities in `queries` instead of one state** — see `config.example.json`.

## Adding a niche

Open `leadbot/niche_map.json` and add an entry, e.g.:
```json
"pet_grooming": [{"category": "shop", "value": "pet_grooming"}]
```
Find the right OSM `category`/`value` pair by searching the niche at https://wiki.openstreetmap.org/wiki/Map_features.

## Files

- `models.py` — the `Lead` record and the one dedup key used everywhere
- `policy.py` — rate limiting, robots.txt checking, retry/backoff, daily quota tracker
- `geocode.py` — region name → bounding box (Geoapify or free Nominatim), plus tiling large regions
- `sources.py` — OpenStreetMap/Overpass business search
- `verify.py` — visits each lead's own website for real contact info/socials
- `storage.py` — Google Sheets or CSV, append-only-new-leads
- `main.py` — wires the above together
- `ui.py` — local web form

## Boundaries (unchanged from v1's intent)

This tool only uses OpenStreetMap's own public data and each business's
own public website — no login walls, no CAPTCHA bypass, no proxy
rotation, no scraping of private/personal social profiles. Review each
platform's terms and any applicable email/telemarketing law before
outreach.
