import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from leadbot.app.pipeline import LeadPipeline
from leadbot.core.models import Lead
from leadbot.enrichment.verify import verify_website
from leadbot.enrichment.website_cache import WebsiteCache
from leadbot.safety.policy import Guard
from leadbot.enrichment import wikidata


class OptimizationTests(unittest.TestCase):
    def test_website_cache_reuses_result(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = WebsiteCache(str(Path(directory) / "cache.sqlite3"))
            original = Lead(
                name="Cached Business",
                website="https://cached.example",
                website_status="200",
                email="hello@cached.example",
                phone="+15551234567",
                social_links="https://instagram.com/cached",
            )
            cache.save(original)
            restored = Lead(name="Cached Business", website="https://cached.example")
            self.assertTrue(cache.load(restored))
            self.assertEqual(restored.email, original.email)
            self.assertEqual(restored.website_status, "200")
            cache.close()

    def test_wikidata_skips_when_two_contact_channels_exist(self):
        lead = Lead(name="Complete Enough", niche="clinic", email="a@example.com", phone="+15551234567")
        guard = Guard(delay=2)
        original_search = wikidata._search_qid
        try:
            wikidata._search_qid = Mock(side_effect=AssertionError("Wikidata should be skipped"))
            wikidata.enrich_from_wikidata(lead, guard)
        finally:
            wikidata._search_qid = original_search

    def test_pipeline_uses_configured_batch_size(self):
        pipeline = LeadPipeline(
            {"storage_batch_size": 50},
            guard=Mock(),
            quota=Mock(),
            niche_map={},
            storage=Mock(),
        )
        self.assertEqual(pipeline.batch_size, 50)
        pipeline.close()


if __name__ == "__main__":
    unittest.main()
