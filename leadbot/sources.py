"""
Business discovery via OpenStreetMap's Overpass API.

WHY THIS FILE EXISTS:
This replaces the old OpenStreetMapSource, which had two query paths: one
by bbox (correct), and one by area-name text match that used `out center;`
instead of `out center tags;` -- silently dropping every business's `name`
tag, so `if not name: continue` threw the results away. That path is gone.
Here there is only ONE path: every query always has a bbox (main.py gets
it from geocode.py first), and tags are always requested.

Large regions (a whole state) are handled by geocode.split_bbox() before
this file ever sees them -- sources.py just loops over whatever list of
bboxes it's given and merges results, de-duplicated by OSM's own
(type, id) pair (a stable id Overpass provides, more reliable than
comparing names).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .models import Lead
from .policy import Guard, retry_request
from .utils import extract_emails, normalize_phone, normalize_url

DEFAULT_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

_NICHE_MAP_PATH = Path(__file__).parent / "niche_map.json"


def load_niche_map() -> dict:
    return json.loads(_NICHE_MAP_PATH.read_text(encoding="utf-8"))


def tags_for_niche(niche: str, niche_map: dict) -> list[dict]:
    """Look up which OSM (category, value) tag pairs correspond to a plain-English niche."""
    return niche_map.get(niche.strip().lower(), [])


class OpenStreetMapSource:
    def __init__(self, guard: Guard, endpoints=None, max_results_per_tile=200, max_attempts=3):
        self.guard = guard
        self.endpoints = endpoints or DEFAULT_ENDPOINTS
        self.max_results_per_tile = max_results_per_tile
        self.max_attempts = max_attempts

    def _query_one_tile(self, category: str, value: str, bbox) -> list[dict]:
        south, west, north, east = bbox
        query = (
            f'[out:json][timeout:30];'
            f'nwr["{category}"="{value}"]({south},{west},{north},{east});'
            f'out center tags;'  # <-- the fix: tags are ALWAYS requested
        )
        for endpoint in self.endpoints:
            host = endpoint.split("/")[2]
            response = retry_request(
                lambda: (self.guard.wait(host), requests.post(
                    endpoint,
                    data=query,
                    headers={"User-Agent": self.guard.user_agent, "Accept": "application/json"},
                    timeout=40,
                ))[1],
                max_attempts=self.max_attempts,
            )
            if response is not None and response.status_code == 200:
                try:
                    return response.json().get("elements", [])
                except ValueError:
                    continue  # bad JSON from this mirror, try the next one
            time.sleep(2)  # brief pause before trying the next mirror
        return []  # every mirror failed for this tile -- caller just gets fewer results, never crashes

    def collect(self, niche: str, tags: list[dict], bboxes: list, country: str, region: str, phone_region: str):
        """
        Query every (category, value) tag for `niche`, across every bbox
        tile, and yield de-duplicated Lead objects.
        """
        seen_osm_ids = set()
        for tag in tags:
            for bbox in bboxes:
                elements = self._query_one_tile(tag["category"], tag["value"], bbox)
                print(f"  OSM tile {bbox}: {len(elements)} raw results for {tag['category']}={tag['value']}")
                for element in elements[: self.max_results_per_tile]:
                    osm_id = (element.get("type"), element.get("id"))
                    if osm_id in seen_osm_ids:
                        continue
                    seen_osm_ids.add(osm_id)

                    tags_dict = element.get("tags", {})
                    name = tags_dict.get("name", "")
                    if not name:
                        continue  # a real record with genuinely no name tag -- nothing to sell to

                    address = " ".join(filter(None, [
                        tags_dict.get("addr:housenumber"),
                        tags_dict.get("addr:street"),
                        tags_dict.get("addr:city"),
                    ])) or tags_dict.get("addr:city", "")
                    emails = extract_emails(tags_dict.get("email", tags_dict.get("contact:email", "")))
                    website = normalize_url(tags_dict.get("website", tags_dict.get("contact:website", "")))
                    phone = normalize_phone(
                        tags_dict.get("phone", tags_dict.get("contact:phone", "")), phone_region
                    )

                    yield Lead(
                        name=name,
                        niche=niche,
                        source="openstreetmap",
                        source_url=f"https://www.openstreetmap.org/{element.get('type')}/{element.get('id')}",
                        website=website,
                        email=emails[0] if emails else "",
                        phone=phone,
                        location=address,
                        country=country,
                        region=region,
                    )
