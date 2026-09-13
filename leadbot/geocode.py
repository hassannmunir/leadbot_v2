"""
Turn "Texas, United States" into a bounding box, and if that box is too big
for a single Overpass query, cut it into smaller tiles.

WHY THIS FILE EXISTS:
The old code had exactly one geocoding path (Geoapify) that RAISED an
exception if the API key was missing, and a second, buggy OSM query path
that skipped geocoding entirely (searching by area name text-match) --
that second path is the one with the "tags go missing" bug we found. This
file removes that fork entirely: geocoding always happens first via one
of two free methods, so sources.py only ever has to deal with a bbox.

Bugs fixed vs the old code:
- No hard requirement for a Geoapify key anymore. If it's missing (or
  fails/hits its rate limit), we fall back to Nominatim, OpenStreetMap's
  own free geocoder (no key needed at all).
- A state-sized bbox handed straight to Overpass used to time out /
  silently return nothing. `split_bbox` below cuts a large box into a
  grid of smaller tiles so each Overpass call stays fast and complete.
"""

from __future__ import annotations

import requests

from .policy import Guard, QuotaTracker, retry_request

Bbox = tuple  # (south, west, north, east) -- always in this order throughout the project


def _geocode_geoapify(country: str, region: str, api_key: str, guard: Guard, quota: QuotaTracker) -> Bbox | None:
    if not api_key:
        return None
    if not quota.can_use("geoapify", daily_limit=3000, buffer=50):
        print("Geoapify: daily free-tier budget reached for today, skipping.")
        return None

    guard.wait("api.geoapify.com")
    response = retry_request(lambda: requests.get(
        "https://api.geoapify.com/v1/geocode/search",
        params={"text": f"{region}, {country}", "limit": 1, "apiKey": api_key},
        headers={"User-Agent": guard.user_agent},
        timeout=20,
    ))
    quota.record_use("geoapify")
    if response is None or response.status_code != 200:
        return None

    features = response.json().get("features", [])
    if not features:
        return None
    props = features[0].get("properties", {})
    bbox = props.get("bbox")
    if bbox and len(bbox) == 4:
        west, south, east, north = bbox
        return (float(south), float(west), float(north), float(east))
    lat, lon = props.get("lat"), props.get("lon")
    if lat is None or lon is None:
        return None
    return (lat - 0.15, lon - 0.15, lat + 0.15, lon + 0.15)


def _geocode_nominatim(country: str, region: str, guard: Guard) -> Bbox | None:
    """Free, no API key. Nominatim's usage policy asks for max ~1 request/second
    and a real User-Agent -- Guard.wait() already enforces spacing."""
    guard.wait("nominatim.openstreetmap.org")
    response = retry_request(lambda: requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": f"{region}, {country}", "format": "json", "limit": 1},
        headers={"User-Agent": guard.user_agent},
        timeout=20,
    ))
    if response is None or response.status_code != 200:
        return None
    results = response.json()
    if not results:
        return None
    box = results[0].get("boundingbox")  # [south, north, west, east] as strings
    if not box or len(box) != 4:
        return None
    south, north, west, east = (float(x) for x in box)
    return (south, west, north, east)


def geocode_region(country: str, region: str, geoapify_key: str, guard: Guard, quota: QuotaTracker) -> Bbox:
    """
    Try Geoapify first (better accuracy) if a key is configured and its
    daily budget isn't exhausted, otherwise fall back to Nominatim (free,
    always available). Raises RuntimeError only if BOTH fail.
    """
    bbox = _geocode_geoapify(country, region, geoapify_key, guard, quota)
    if bbox:
        return bbox
    bbox = _geocode_nominatim(country, region, guard)
    if bbox:
        return bbox
    raise RuntimeError(
        f"Could not find '{region}, {country}' with either Geoapify or Nominatim. "
        "Check the spelling, or try a more specific region name."
    )


def split_bbox(bbox: Bbox, max_area_deg2: float = 0.35) -> list[Bbox]:
    """
    Cut a bounding box into a grid of tiles so each tile's area stays under
    `max_area_deg2` square degrees. A whole US state is often 5-15 deg2;
    0.35 deg2 is roughly a large-metro-area-sized tile, small enough that
    a single Overpass query for one niche reliably finishes before its
    timeout.

    A city-sized bbox is usually already under the threshold, so this is a
    no-op (returns [bbox]) for normal city searches -- it only kicks in
    for state/country-sized regions.
    """
    south, west, north, east = bbox
    area = (north - south) * (east - west)
    if area <= max_area_deg2:
        return [bbox]

    # Aim for roughly-square tiles: split each side by sqrt of the ratio.
    import math
    splits_per_side = max(1, math.ceil(math.sqrt(area / max_area_deg2)))
    lat_step = (north - south) / splits_per_side
    lon_step = (east - west) / splits_per_side

    tiles = []
    for i in range(splits_per_side):
        for j in range(splits_per_side):
            tile_south = south + i * lat_step
            tile_north = south + (i + 1) * lat_step
            tile_west = west + j * lon_step
            tile_east = west + (j + 1) * lon_step
            tiles.append((tile_south, tile_west, tile_north, tile_east))
    return tiles
