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
  4. Save leads to storage IN BATCHES as they're verified (not all at
     the end) -- see CRASH SAFETY below.

PROGRESS REPORTING:
Every meaningful step prints a line like "PROGRESS 45 Verifying website
12/80" to stdout. leadbot/ui.py reads these lines LIVE to drive a real
progress bar.

CRASH SAFETY:
A state-wide run can take 30-60+ minutes. Leads are written to storage
(Google Sheet / CSV) every BATCH_SIZE verified leads, not just once at
the very end. If the process is interrupted (Ctrl+C) or crashes partway
through, everything verified up to the last batch is already saved --
at most BATCH_SIZE-1 leads' worth of work is ever at risk, never the
whole run.
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

BATCH_SIZE = 20


def report(progress: int, message: str):
    """The ONE place that emits a progress update. progress is 0-100."""
    print(f"PROGRESS {max(0, min(100, int(progress)))} {message}", flush=True)


def collect_for_query(query: dict, config: dict, guard: Guard, quota: QuotaTracker,
                       niche_map: dict, progress_cb, storage) -> int:
    """
    Returns the number of NEW leads actually added to storage for this
    query (leads already present from a previous run don't count).

    progress_cb(fraction, message) is called with fraction going from 0.0
    to 1.0 as THIS query moves through geocoding -> OSM query -> website
    verification. The caller (main()) scales that 0-1 fraction into the
    overall run's 0-100 progress bar.
    """
    country = query.get("country", config.get("country", ""))
    region = query.get("region", config.get("region", ""))
    niche = query.get("niche", "")
    phone_region = config.get("phone_region", "PK")
    minimum = config.get("minimum_quality_score", 0)

    tags = tags_for_niche(niche, niche_map)
    if not tags:
        print(f"Skipping '{niche}': not in niche_map.json. "
              f"Add it there as {{\"category\": \"...\", \"value\": \"...\"}} (see OSM wiki for tags).")
        return 0

    progress_cb(0.02, f"Geocoding '{region}, {country}'...")
    try:
        bbox = geocode_region(country, region, os.getenv("GEOAPIFY_API_KEY", ""), guard, quota)
    except RuntimeError as e:
        print(f"Skipping '{region}, {country}': {e}")
        return 0

    tiles = split_bbox(bbox, max_area_deg2=config.get("max_tile_area_deg2", 0.5))
    progress_cb(0.08, f"'{niche}' in '{region}, {country}' -> {len(tiles)} search tile(s)")

    source = OpenStreetMapSource(
        guard,
        endpoints=config.get("overpass_endpoints"),
        max_results_per_tile=config.get("max_results_per_tile"),
    )
    osm_progress_cb = lambda tile_fraction, message: progress_cb(0.08 + 0.22 * tile_fraction, message)
    leads = list(source.collect(niche, tags, tiles, country, region, phone_region, osm_progress_cb))
    progress_cb(0.30, f"{len(leads)} unique businesses found, checking their websites...")

    total = len(leads) or 1
    total_added = 0
    buffer = []

    def flush():
        nonlocal total_added, buffer
        if buffer:
            added = storage.append_new_leads(buffer)
            total_added += added
            print(f"  Saved a batch: {added} new lead(s) written to storage "
                  f"(of {len(buffer)} checked in this batch).")
            buffer = []

    try:
        for i, lead in enumerate(leads):
            verify_website(lead, guard, phone_region)
            assess_ai_agent_fit(lead)
            if quality_score(lead) >= minimum:
                buffer.append(lead)
            # Verification is the slowest part of the whole run, so it gets
            # the biggest share (0.30 -> 1.00) of this query's progress.
            progress_cb(0.30 + 0.70 * (i + 1) / total, f"Verified website {i + 1}/{len(leads)}")
            if len(buffer) >= BATCH_SIZE:
                flush()
    finally:
        # Runs on normal completion AND on Ctrl+C / an unexpected error --
        # whatever's left in the buffer is saved either way.
        flush()

    return total_added


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
    storage = get_storage(config)

    queries = config.get("queries", [])
    if not queries:
        raise SystemExit(
            "config.json has no 'queries'. Add at least one: "
            '{"country": "United States", "region": "Texas", "niche": "restaurant"}'
        )

    total_queries = len(queries)
    total_added = 0
    try:
        for qi, query in enumerate(queries):

            def progress_cb(fraction, message, qi=qi):
                overall = 5 + 90 * (qi + fraction) / total_queries
                report(overall, message)

            total_added += collect_for_query(query, config, guard, quota, niche_map, progress_cb, storage)
    except KeyboardInterrupt:
        report(100, f"Stopped by user. {total_added} new lead(s) were already saved before stopping.")
        return

    report(100, f"Done. {total_added} new lead(s) added across all queries this run.")


if __name__ == "__main__":
    main()
