"""
Entry point: `python -m leadbot.main --config config.json`

Pipeline, in order:
  1. For each requested (country, region, niche):
       a. geocode the region to a bbox (Nominatim, else Geoapify)
       b. split the bbox into tiles if it's large (a whole state/country)
       c. query OpenStreetMap for that niche's tags, across all tiles
  2. Visit each found business's own website once, to pull real contact
     info and socials (never invented, never from a different business)
  3. Score each lead for lead-quality and AI-agent fit
  4. Append only the genuinely NEW leads to storage (Google Sheet or CSV)
     -- everything already there from a previous run is left untouched.

PROGRESS REPORTING:
Every meaningful step prints a line like "PROGRESS 45 Verifying website
12/80" to stdout. leadbot/ui.py reads these lines LIVE to drive a real
progress bar. Running this file directly from a terminal, these lines
are simply visible as part of the normal log.
"""

import argparse
import json
import os

from dotenv import load_dotenv

from .geocode import geocode_region, split_bbox
from .policy import Guard, QuotaTracker
from .sources import OpenStreetMapSource, load_niche_map, tags_for_niche
from .storage import get_storage
from .utils import assess_ai_agent_fit, quality_score
from .verify import verify_website


def report(progress: int, message: str):
    """The ONE place that emits a progress update. progress is 0-100."""
    print(f"PROGRESS {max(0, min(100, int(progress)))} {message}", flush=True)


def collect_for_query(query: dict, config: dict, guard: Guard, quota: QuotaTracker,
                       niche_map: dict, progress_cb) -> list:
    """
    progress_cb(fraction, message) is called with fraction going from 0.0
    to 1.0 as THIS query moves through geocoding -> OSM query -> website
    verification. The caller (main()) scales that 0-1 fraction into the
    overall run's 0-100 progress bar.
    """
    country = query.get("country", config.get("country", ""))
    region = query.get("region", config.get("region", ""))
    niche = query.get("niche", "")
    phone_region = config.get("phone_region", "PK")

    tags = tags_for_niche(niche, niche_map)
    if not tags:
        print(f"Skipping '{niche}': not in niche_map.json. "
              f"Add it there as {{\"category\": \"...\", \"value\": \"...\"}} (see OSM wiki for tags).")
        return []

    progress_cb(0.02, f"Geocoding '{region}, {country}'...")
    try:
        bbox = geocode_region(country, region, os.getenv("GEOAPIFY_API_KEY", ""), guard, quota)
    except RuntimeError as e:
        print(f"Skipping '{region}, {country}': {e}")
        return []

    tiles = split_bbox(bbox, max_area_deg2=config.get("max_tile_area_deg2", 0.5))
    progress_cb(0.08, f"'{niche}' in '{region}, {country}' -> {len(tiles)} search tile(s)")

    source = OpenStreetMapSource(guard, endpoints=config.get("overpass_endpoints"))
    leads = list(source.collect(niche, tags, tiles, country, region, phone_region))
    progress_cb(0.30, f"{len(leads)} unique businesses found, checking their websites...")

    verified = []
    total = len(leads) or 1
    for i, lead in enumerate(leads):
        verify_website(lead, guard, phone_region)
        assess_ai_agent_fit(lead)
        verified.append(lead)
        progress_cb(0.30 + 0.70 * (i + 1) / total, f"Verified website {i + 1}/{len(leads)}")

    minimum = config.get("minimum_quality_score", 0)
    kept = [l for l in verified if quality_score(l) >= minimum]
    print(f"  {len(kept)} leads kept after the minimum-quality filter ({minimum})")
    return kept


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="LeadBot: free, compliant local-business lead collector")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()

    report(1, "Starting up...")
    config = json.load(open(args.config, encoding="utf-8"))
    guard = Guard(delay=config.get("delay_seconds", 3))
    quota = QuotaTracker(config.get("quota_state_file", "quota_state.json"))
    niche_map = load_niche_map()

    queries = config.get("queries", [])
    if not queries:
        raise SystemExit(
            "config.json has no 'queries'. Add at least one: "
            '{"country": "United States", "region": "Texas", "niche": "restaurant"}'
        )

    total_queries = len(queries)
    all_leads = []
    for qi, query in enumerate(queries):

        def progress_cb(fraction, message, qi=qi):
            overall = 5 + 90 * (qi + fraction) / total_queries
            report(overall, message)

        all_leads.extend(collect_for_query(query, config, guard, quota, niche_map, progress_cb))

    report(96, "Writing new leads to storage...")
    storage = get_storage(config)
    added = storage.append_new_leads(all_leads)
    report(100, f"Done. {added} new lead(s) added out of {len(all_leads)} found this run.")


if __name__ == "__main__":
    main()