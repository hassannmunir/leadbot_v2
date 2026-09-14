import unittest

from leadbot.core.utils import extract_social_links
from leadbot.enrichment.wikidata import _build_social_url


class SocialLinkTests(unittest.TestCase):
    def test_extracts_known_and_additional_public_social_profiles(self):
        html = """
        <a href="https://instagram.com/business">Instagram</a>
        <a href="https://threads.net/@business">Threads</a>
        <a href="https://t.me/business">Telegram</a>
        <a href="https://social.example/profile/business" rel="me">Profile</a>
        """
        links = extract_social_links(html).split(" | ")
        self.assertEqual(len(links), 4)
        self.assertIn("https://threads.net/@business", links)
        self.assertIn("https://social.example/profile/business", links)

    def test_ignores_share_and_login_links(self):
        html = """
        <a href="https://facebook.com/sharer/sharer.php?u=https://business.example">Share</a>
        <a href="https://instagram.com/accounts/login">Login</a>
        <a href="https://business.example/contact">Contact</a>
        """
        self.assertEqual(extract_social_links(html), "")

    def test_preserves_handles_without_inventing_urls(self):
        self.assertEqual(_build_social_url("instagram", "@business"), "instagram:@business")
        self.assertEqual(_build_social_url("facebook", "business-page"), "facebook:@business-page")
        self.assertEqual(
            _build_social_url("instagram", "https://instagram.com/business"),
            "https://instagram.com/business",
        )


if __name__ == "__main__":
    unittest.main()
