import unittest

from leadbot.core.models import Lead, normalize_domain
from leadbot.safety.policy import Guard
from leadbot.discovery.sources import OpenStreetMapSource
from leadbot.enrichment.wikidata import _select_best_qid
from leadbot.core.utils import assess_ai_agent_fit


class AccuracyTests(unittest.TestCase):
    def test_wikidata_requires_strong_match(self):
        results = [{"id": "Q1", "label": "Austin Family Clinic"}]
        self.assertEqual(_select_best_qid("Austin Family Clinic", results), "Q1")
        self.assertIsNone(_select_best_qid("Austin Clinic", [{"id": "Q1", "label": "Austin"}]))

    def test_wikidata_rejects_ambiguous_results(self):
        results = [
            {"id": "Q1", "label": "Main Street Dental"},
            {"id": "Q2", "label": "Main Street Dental"},
        ]
        self.assertIsNone(_select_best_qid("Main Street Dental", results))

    def test_domain_normalization_supports_website_validation(self):
        self.assertEqual(
            normalize_domain("https://www.example.com/contact?source=home"),
            "example.com",
        )

    def test_osm_collection_is_unlimited_by_default(self):
        source = OpenStreetMapSource(Guard(delay=2), endpoints=[])
        source._query_one_tile = lambda category, value, bbox: [
            {"type": "node", "id": index, "tags": {"name": f"Business {index}"}}
            for index in range(3)
        ]
        leads = list(source.collect("restaurant", [{"category": "amenity", "value": "restaurant"}], [(0, 0, 1, 1)], "US", "Austin", "US"))
        self.assertEqual(len(leads), 3)

    def test_osm_collection_honors_explicit_limit(self):
        source = OpenStreetMapSource(Guard(delay=2), endpoints=[], max_results_per_tile=2)
        source._query_one_tile = lambda category, value, bbox: [
            {"type": "node", "id": index, "tags": {"name": f"Business {index}"}}
            for index in range(3)
        ]
        leads = list(source.collect("restaurant", [{"category": "amenity", "value": "restaurant"}], [(0, 0, 1, 1)], "US", "Austin", "US"))
        self.assertEqual(len(leads), 2)

    def test_ai_fit_is_business_specific(self):
        clinic = Lead(name="Care Clinic", niche="clinic", website="https://care.example")
        restaurant = Lead(name="Good Eats", niche="restaurant")
        assess_ai_agent_fit(clinic)
        assess_ai_agent_fit(restaurant)
        self.assertGreaterEqual(clinic.ai_agent_fit_score, 90)
        self.assertEqual(clinic.ai_agent_priority, "high")
        self.assertIn("patient intake", clinic.ai_agent_opportunities)
        self.assertNotEqual(clinic.ai_agent_opportunities, restaurant.ai_agent_opportunities)

    def test_unsuitable_or_unknown_niche_gets_zero_fit(self):
        lead = Lead(name="Fuel Stop", niche="gas_station")
        assess_ai_agent_fit(lead)
        self.assertEqual(lead.ai_agent_fit_score, 0)
        self.assertEqual(lead.ai_agent_priority, "low")
        self.assertEqual(lead.ai_agent_opportunities, "")


if __name__ == "__main__":
    unittest.main()
