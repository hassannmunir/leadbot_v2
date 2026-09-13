"""
Entry point: `python -m leadbot.main --config config.json`

Pipeline, in order:
  1. For each requested (country, region, niche):
       a. geocode the region to a bbox (Geoapify, else free Nominatim)
       b. split the bbox into tiles if it's large (a whole state/country)
       c. query OpenStreetMap for that niche's tags, across all tiles
  2. Visit each found business's own website once, to pull real contact
     info and socials (never invented, never from a different business)
  3. Score each lead for lead-quality and AI-agent fit
  4. Append only the genuinely NEW leads to storage (Google Sheet or CSV)
     -- everything already there from a previous run is left untouched.

Every network-touching step already retries and backs off on its own
(see policy.py); this file's job is just to wire the pieces together
and never let one bad query take down the whole run.
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


def collect_for_query(
    query: dict,
    config: dict,
    guard: Guard,
    quota: QuotaTracker,
    niche_map: dict
) -> list:
    country = query.get("country", config.get("country", ""))
    region = query.get("region", config.get("region", ""))
    niche = query.get("niche", "")
    phone_region = config.get("phone_region", "PK")

    tags = tags_for_niche(niche, niche_map)
    if not tags:
        print(
            f"Skipping '{niche}': not in niche_map.json. "
            f"Add it there as {{\"category\": \"...\", \"value\": \"...\"}} "
            f"(see OSM wiki for tags)."
        )
        return []

    try:
        bbox = geocode_region(
            country,
            region,
            os.getenv("GEOAPIFY_API_KEY", ""),
            guard,
            quota
        )
    except RuntimeError as e:
        print(f"Skipping '{region}, {country}': {e}")
        return []

    tiles = split_bbox(
        bbox,
        max_area_deg2=config.get("max_tile_area_deg2", 0.35)
    )

    print(
        f"'{niche}' in '{region}, {country}' -> "
        f"{len(tiles)} search tile(s)"
    )

    source = OpenStreetMapSource(
        guard,
        endpoints=config.get("overpass_endpoints")
    )

    leads = list(
        source.collect(
            niche,
            tags,
            tiles,
            country,
            region,
            phone_region
        )
    )

    print(
        f"  {len(leads)} unique businesses found before website checks"
    )

    verified = []

    for lead in leads:
        verify_website(lead, guard, phone_region)
        assess_ai_agent_fit(lead)
        verified.append(lead)

    # Minimum quality score is intentionally 0 for agent testing.
    # This allows all verified leads to pass through the quality filter.
    minimum = 0

    kept = [
        lead
        for lead in verified
        if quality_score(lead) >= minimum
    ]

    print(
        f"  {len(kept)} leads kept after the minimum-quality filter "
        f"({minimum})"
    )

    return kept


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="LeadBot: free, compliant local-business lead collector"
    )

    parser.add_argument(
        "--config",
        default="config.json"
    )

    args = parser.parse_args()

    config = json.load(
        open(args.config, encoding="utf-8")
    )

    guard = Guard(
        delay=config.get("delay_seconds", 3)
    )

    quota = QuotaTracker(
        config.get(
            "quota_state_file",
            "quota_state.json"
        )
    )

    niche_map = load_niche_map()

    queries = config.get("queries", [])

    if not queries:
        raise SystemExit(
            "config.json has no 'queries'. Add at least one: "
            '{"country": "United States", '
            '"region": "Texas", '
            '"niche": "restaurant"}'
        )

    all_leads = []

    for query in queries:
        all_leads.extend(
            collect_for_query(
                query,
                config,
                guard,
                quota,
                niche_map
            )
        )

    storage = get_storage(config)

    added = storage.append_new_leads(all_leads)

    print(
        f"\nDone. {added} new lead(s) added out of "
        f"{len(all_leads)} found this run "
        f"(the rest were already in storage)."
    )


if __name__ == "__main__":
    main()