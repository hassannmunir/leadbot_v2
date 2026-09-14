import unittest

import pandas as pd

from leadbot.core.scoring import LeadScorer


class LeadScorerTests(unittest.TestCase):
    def setUp(self):
        self.scorer = LeadScorer()

    def test_case_a_clinic_active_full_contact(self):
        result = self.scorer.score_lead({
            "name": "Care Clinic",
            "niche": "clinic",
            "website_status": "200",
            "phone": "+15551234567",
            "email": "hello@care.example",
            "location": "123 Main Street",
            "source_url": "https://www.openstreetmap.org/node/1",
        })
        self.assertGreaterEqual(result["ai_agent_fit_score"], 85)
        self.assertEqual(result["ai_agent_priority"], "High (AI Agent)")
        self.assertEqual(result["recommended_offer"], "AI Agent Integration")

    def test_case_b_restaurant_broken_website_phone(self):
        result = self.scorer.score_lead({
            "name": "Good Eats",
            "niche": "restaurant",
            "website_status": "404",
            "phone": "+15551234567",
            "location": "123 Main Street",
            "source_url": "https://www.openstreetmap.org/node/2",
        })
        self.assertGreaterEqual(result["ai_agent_fit_score"], 65)
        self.assertLessEqual(result["ai_agent_fit_score"], 75)
        self.assertEqual(result["ai_agent_priority"], "High (Web + Agent)")
        self.assertEqual(result["recommended_offer"], "Website Rebuild + AI Agent")

    def test_case_c_active_website_without_contact_is_capped(self):
        result = self.scorer.score_lead({
            "name": "No Contact Clinic",
            "niche": "clinic",
            "website_status": "200",
            "location": "123 Main Street",
            "source_url": "https://www.openstreetmap.org/node/3",
        })
        self.assertLessEqual(result["ai_agent_fit_score"], 25)
        self.assertEqual(result["ai_agent_priority"], "Low / Disqualified")
        self.assertEqual(result["recommended_offer"], "Enrichment Required")

    def test_case_d_clinic_without_website_phone_recovered(self):
        result = self.scorer.score_lead({
            "name": "Phone Clinic",
            "niche": "clinic",
            "website_status": "no_website_found",
            "phone": "+15551234567",
            "location": "123 Main Street",
            "source_url": "https://www.openstreetmap.org/node/4",
        })
        self.assertGreaterEqual(result["ai_agent_fit_score"], 45)
        self.assertLessEqual(result["ai_agent_fit_score"], 60)
        self.assertIn(result["ai_agent_priority"], {"Medium", "High (Web + Agent)"})
        self.assertEqual(result["recommended_offer"], "Full Web Build")

    def test_dataframe_scoring(self):
        frame = pd.DataFrame([{
            "niche": "clinic",
            "website_status": "200",
            "phone": "+15551234567",
            "email": "hello@clinic.example",
            "location": "123 Main Street",
            "source_url": "osm://1",
        }])
        result = self.scorer.score_dataframe(frame)
        self.assertEqual(result.loc[0, "ai_agent_priority"], "High (AI Agent)")
        self.assertEqual(result.loc[0, "recommended_offer"], "AI Agent Integration")


if __name__ == "__main__":
    unittest.main()
