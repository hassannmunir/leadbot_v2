import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from leadbot.core.models import Lead
from leadbot.enrichment import wikidata
from leadbot.safety.policy import Guard
from leadbot.storage.storage import CSVStorage


class PerformanceTests(unittest.TestCase):
    def test_rate_limiter_reserves_ten_percent_safety_margin(self):
        guard = Guard(delay=2, requests_per_minute=1000, rate_limit_safety_ratio=0.9)
        self.assertEqual(guard.rate_limiter.safe_limit, 900)

    @patch("leadbot.safety.policy.requests.get")
    def test_robots_decision_is_cached(self, get_request):
        response = Mock(status_code=404, text="")
        get_request.return_value = response
        guard = Guard(delay=2, robots_ttl_seconds=3600)

        self.assertTrue(guard.allowed("https://example.com/contact"))
        self.assertTrue(guard.allowed("https://example.com/about"))
        self.assertEqual(get_request.call_count, 1)

    def test_wikidata_lookup_is_cached(self):
        cache_key = "performance-cache-business|test region|"
        with wikidata._CACHE_LOCK:
            wikidata._LOOKUP_CACHE.pop(cache_key, None)

        with patch.object(wikidata, "_search_qid", return_value="Q123") as search, \
             patch.object(wikidata, "_is_organisation", return_value=True) as organisation, \
             patch.object(wikidata, "_fetch_properties", return_value={"phone": "+15551234567"}) as fetch:
            first = wikidata._cached_lookup("Performance Cache Business", "Test Region", "", Guard(delay=2))
            second = wikidata._cached_lookup("Performance Cache Business", "Test Region", "", Guard(delay=2))

        self.assertEqual(first, second)
        search.assert_called_once()
        organisation.assert_called_once()
        fetch.assert_called_once()

    def test_storage_loads_existing_keys_once_within_ttl(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = CSVStorage(str(Path(directory) / "leads"), cache_ttl_seconds=300)
            with patch.object(storage, "_load_keys", wraps=storage._load_keys) as load_keys:
                first = storage.load_existing_keys()
                second = storage.load_existing_keys()

            self.assertEqual(first, second)
            self.assertEqual(load_keys.call_count, 2)


if __name__ == "__main__":
    unittest.main()
