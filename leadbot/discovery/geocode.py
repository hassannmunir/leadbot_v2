"""
Turn "Texas, United States" into a bounding box, and if that box is too big
for a single Overpass query, cut it into smaller tiles.

v2.1 fix: Nominatim is now tried FIRST for named regions (city/state/
country), because it reliably returns the actual administrative boundary's
bounding box. Geoapify's free-tier geocode search sometimes returns only a
lat/lon point (no bbox) for a state-sized region -- using a small fallback
box around that point is exactly what produced a tiny, wrong search area
(0.3 x 0.3 degrees for the whole state of Texas). Geoapify is now only a
backup, and its own point-only fallback is bigger and clearly logged as
approximate, never silently substituted for a real state boundary.
"""

from __future__ import annotations

import requests

from ..safety.policy import Guard, QuotaTracker, retry_request

Bbox = tuple  # (south, west, north, east) -- always in this order throughout the project


def _geocode_nominatim(country: str, region: str, guard: Guard) -> Bbox | None:
    """Free, no API key, and reliably returns a real administrative bounding
    box for named places (cities, states, countries) -- tried first."""
    response = retry_request(lambda: (
        guard.wait("nominatim.openstreetmap.org"),
        requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{region}, {country}", "format": "json", "limit": 1},
            headers={"User-Agent": guard.user_agent},
            timeout=20,
        ),
    )[1])
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


def _geocode_geoapify(country: str, region: str, api_key: str, guard: Guard, quota: QuotaTracker) -> Bbox | None:
    if not api_key:
        return None
    if not quota.can_use("geoapify", daily_limit=3000, buffer=50):
        print("Geoapify: daily free-tier budget reached for today, skipping.")
        return None

    response = retry_request(lambda: (
        guard.wait("api.geoapify.com"),
        requests.get(
            "https://api.geoapify.com/v1/geocode/search",
            params={"text": f"{region}, {country}", "limit": 1, "apiKey": api_key},
            headers={"User-Agent": guard.user_agent},
            timeout=20,
        ),
    )[1])
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

    # No proper bbox from Geoapify -- only usable as a last resort, and
    # clearly flagged as approximate (a state/country should never end up
    # here; this is meant for small towns Nominatim also couldn't resolve).
    lat, lon = props.get("lat"), props.get("lon")
    if lat is None or lon is None:
        return None
    print(f"WARNING: Geoapify gave only a point for '{region}, {country}', no boundary. "
          f"Using an approximate ~0.6deg box around it -- results may miss areas outside it.")
    return (lat - 0.3, lon - 0.3, lat + 0.3, lon + 0.3)


def geocode_region(country: str, region: str, geoapify_key: str, guard: Guard, quota: QuotaTracker) -> Bbox:
    """
    Try Nominatim first (reliable real boundaries for named regions),
    then Geoapify as backup. Raises RuntimeError only if both fail.
    """
    bbox = _geocode_nominatim(country, region, guard)
    if bbox:
        return bbox
    bbox = _geocode_geoapify(country, region, geoapify_key, guard, quota)
    if bbox:
        return bbox
    raise RuntimeError(
        f"Could not find '{region}, {country}' with either Nominatim or Geoapify. "
        "Check the spelling, or try a more specific region name."
    )


def split_bbox(bbox: Bbox, max_area_deg2: float = 0.5) -> list[Bbox]:
    """
    Cut a bounding box into a grid of tiles so each tile's area stays under
    `max_area_deg2` square degrees. A city-sized bbox is usually already
    under the threshold (no-op); a state/country-sized bbox gets tiled so
    Overpass queries stay fast and complete instead of timing out.
    """
    south, west, north, east = bbox
    area = (north - south) * (east - west)
    if area <= max_area_deg2:
        return [bbox]

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