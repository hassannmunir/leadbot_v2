"""Configuration loading and runtime dependency construction."""

from __future__ import annotations

import json
from pathlib import Path

from ..safety.policy import Guard, QuotaTracker
from ..discovery.sources import load_niche_map
from ..storage.storage import get_storage


def load_config(path: str | Path) -> dict:
    """Load a JSON configuration file with a clear file boundary."""
    config_path = Path(path)
    with config_path.open(encoding="utf-8") as config_file:
        return json.load(config_file)


def validate_queries(config: dict) -> list[dict]:
    """Return configured queries or raise a useful configuration error."""
    queries = config.get("queries", [])
    if not queries:
        raise SystemExit(
            "config.json has no 'queries'. Add at least one: "
            '{"country": "United States", "region": "Texas", "niche": "restaurant"}'
        )
    return queries


def build_runtime(config: dict) -> tuple[Guard, QuotaTracker, dict, object]:
    """Build the shared services used by one collection run."""
    guard = Guard(
        delay=config.get("delay_seconds", 3),
        robots_ttl_seconds=config.get("robots_cache_ttl_seconds", 86400),
        requests_per_minute=config.get("requests_per_minute", 1000),
        rate_limit_safety_ratio=config.get("rate_limit_safety_ratio", 0.9),
    )
    quota = QuotaTracker(config.get("quota_state_file", "quota_state.json"))
    niche_map = load_niche_map()
    storage = get_storage(config)
    return guard, quota, niche_map, storage
