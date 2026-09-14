"""Lead collection orchestration."""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..discovery.geocode import geocode_region, split_bbox
from ..core.models import Lead
from ..discovery.sources import OpenStreetMapSource, tags_for_niche
from ..core.utils import assess_ai_agent_fit, quality_score
from ..enrichment.verify import verify_website
from ..enrichment.website_cache import WebsiteCache

BATCH_SIZE = 20


class LeadPipeline:
    """Coordinate discovery, enrichment, scoring, and append-only storage."""

    def __init__(self, config: dict, guard, quota, niche_map: dict, storage, batch_size: int | None = None):
        self.config = config
        self.guard = guard
        self.quota = quota
        self.niche_map = niche_map
        self.storage = storage
        configured_batch_size = config.get("storage_batch_size", BATCH_SIZE)
        self.batch_size = max(1, int(batch_size if batch_size is not None else configured_batch_size))
        self.website_cache = WebsiteCache(
            self.config.get("website_cache_file", "website_cache.sqlite3"),
            self.config.get("website_cache_ttl_seconds", 604800),
        )

    def close(self) -> None:
        """Release persistent resources after a run."""
        self.website_cache.close()

    def collect_for_query(self, query: dict, progress_cb: Callable[[float, str], None]) -> int:
        country = query.get("country", self.config.get("country", ""))
        region = query.get("region", self.config.get("region", ""))
        niche = query.get("niche", "")
        phone_region = self.config.get("phone_region", "PK")
        minimum_score = self.config.get("minimum_quality_score", 0)
        verification_workers = max(1, int(self.config.get("verification_workers", 4)))

        tags = tags_for_niche(niche, self.niche_map)
        if not tags:
            print(
                f"Skipping '{niche}': not in niche_map.json. "
                'Add it there as {"category": "...", "value": "..."} '
                "(see OSM wiki for tags)."
            )
            return 0

        progress_cb(0.02, f"Geocoding '{region}, {country}'...")
        try:
            bbox = geocode_region(
                country,
                region,
                os.getenv("GEOAPIFY_API_KEY", ""),
                self.guard,
                self.quota,
            )
        except RuntimeError as error:
            print(f"Skipping '{region}, {country}': {error}")
            return 0

        tiles = split_bbox(bbox, max_area_deg2=self.config.get("max_tile_area_deg2", 0.5))
        progress_cb(0.08, f"'{niche}' in '{region}, {country}' -> {len(tiles)} search tile(s)")

        source = OpenStreetMapSource(
            self.guard,
            endpoints=self.config.get("overpass_endpoints"),
            max_results_per_tile=self.config.get("max_results_per_tile"),
        )
        osm_progress = lambda fraction, message: progress_cb(0.08 + 0.22 * fraction, message)
        leads = list(source.collect(niche, tags, tiles, country, region, phone_region, osm_progress))
        progress_cb(0.30, f"{len(leads)} unique businesses found, checking their websites...")

        total = len(leads) or 1
        total_added = 0
        buffer: list[Lead] = []

        def flush() -> None:
            nonlocal total_added
            if not buffer:
                return
            added = self.storage.append_new_leads(buffer)
            total_added += added
            print(
                f"  Saved a batch: {added} new lead(s) written to storage "
                f"(of {len(buffer)} checked in this batch)."
            )
            buffer.clear()

        def verify_and_score(lead: Lead) -> Lead:
            verify_website(lead, self.guard, phone_region, self.website_cache)
            assess_ai_agent_fit(lead)
            return lead

        try:
            completed = 0
            with ThreadPoolExecutor(max_workers=verification_workers) as executor:
                for start in range(0, len(leads), verification_workers):
                    futures = [
                        executor.submit(verify_and_score, lead)
                        for lead in leads[start:start + verification_workers]
                    ]
                    for future in as_completed(futures):
                        lead = future.result()
                        completed += 1
                        if quality_score(lead) >= minimum_score:
                            buffer.append(lead)
                        progress_cb(
                            0.30 + 0.70 * completed / total,
                            f"Verified website {completed}/{len(leads)}",
                        )
                        if len(buffer) >= self.batch_size:
                            flush()
        finally:
            flush()

        return total_added


def collect_for_query(query: dict, config: dict, guard, quota, niche_map: dict, progress_cb, storage) -> int:
    """Compatibility wrapper for callers of the former main.py function."""
    pipeline = LeadPipeline(config, guard, quota, niche_map, storage)
    return pipeline.collect_for_query(query, progress_cb)
