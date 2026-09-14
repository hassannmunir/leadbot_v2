"""
Enrich a Lead by fetching ITS OWN website and then -- if gaps remain --
querying Wikidata's official structured API.

ENRICHMENT ORDER (each step only fills gaps the previous left empty):
  1. OSM tags       -- sources.py already populated phone/email/socials/website
                       before this file is called. Never overwritten here.
  2. Website fetch  -- fetch the business's own website, extract contact info.
  3. Wikidata       -- if website missing OR contact info still incomplete,
                       query Wikidata's SPARQL API (no CAPTCHA, no scraping).

WHY NOT GOOGLE:
  Google search scraping triggers CAPTCHAs under continuous production load.
  Wikidata is an official structured API -- same data quality, zero CAPTCHA risk.

If a website can't be reached the lead is NOT thrown away -- a broken website
is still a real business and often a better prospect for "rebuild your web
presence" outreach.
"""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from ..core.models import Lead
from ..safety.policy import Guard, retry_request
from ..core.utils import extract_emails, extract_social_links, PHONE_RE, normalize_phone, normalize_url
from .wikidata import enrich_from_wikidata
from .website_cache import WebsiteCache


def verify_website(
    lead: Lead,
    guard: Guard,
    phone_region: str = "PK",
    website_cache: WebsiteCache | None = None,
) -> Lead:

    # ------------------------------------------------------------------
    # CASE 1: No website in OSM -- go straight to Wikidata for everything
    # ------------------------------------------------------------------
    if not lead.website:
        lead.website_status = "no_website_found"

        # Wikidata may give us website + socials + phone + email
        enrich_from_wikidata(lead, guard)

        has_something = bool(lead.phone or lead.email or lead.social_links or lead.website)
        lead.notes = (
            "No OSM website. Contact info recovered via Wikidata."
            if has_something
            else "No website found. OSM tags and Wikidata both returned no contact info."
        )

        # If Wikidata gave us a website, fall through and fetch it
        if not lead.website:
            return lead
        # else: fall through to fetch the Wikidata-supplied website below

    # ------------------------------------------------------------------
    # CASE 2: We have a website URL (from OSM or Wikidata) -- fetch it
    # ------------------------------------------------------------------
    url = normalize_url(lead.website)

    if website_cache and website_cache.load(lead):
        enrich_from_wikidata(lead, guard)
        website_cache.save(lead)
        return lead

    if not guard.allowed(url):
        lead.website_status = "robots_denied"
        lead.notes = "Website robots.txt disallows access. Trying Wikidata for contact info."
        if website_cache:
            website_cache.save(lead)
        enrich_from_wikidata(lead, guard)
        return lead

    # Keep a full pacing interval between robots.txt and page requests, and
    # reserve a rate-limit slot for every retry attempt.
    response = retry_request(
        lambda: (
            guard.wait(urlparse(url).netloc),
            requests.get(url, headers={"User-Agent": guard.user_agent}, timeout=15),
        )[1],
        max_attempts=3,
    )

    if response is None:
        lead.website_status = "unreachable"
        lead.notes = "Website did not respond after retries. Trying Wikidata for contact info."
        if website_cache:
            website_cache.save(lead)
        enrich_from_wikidata(lead, guard)
        return lead

    if response.status_code in (403, 404, 410, 429):
        lead.website_status = str(response.status_code)
        lead.notes = (
            f"Website unavailable: HTTP {response.status_code} "
            f"(kept as rebuild prospect). Trying Wikidata for contact info."
        )
        if website_cache:
            website_cache.save(lead)
        enrich_from_wikidata(lead, guard)
        return lead

    if response.status_code != 200:
        lead.website_status = str(response.status_code)
        lead.notes = f"Website returned HTTP {response.status_code}."
        if website_cache:
            website_cache.save(lead)
        enrich_from_wikidata(lead, guard)
        return lead

    # ------------------------------------------------------------------
    # Successful website fetch -- extract from page, fill gaps only
    # ------------------------------------------------------------------
    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    emails = extract_emails(response.text)
    phones = list(dict.fromkeys(PHONE_RE.findall(text)))
    page_socials = extract_social_links(response.text)

    lead.website_status = "200"

    # Only fill fields that OSM left empty
    if not lead.email and emails:
        lead.email = emails[0]
    if not lead.phone and phones:
        lead.phone = normalize_phone(phones[0], phone_region)
    if not lead.social_links and page_socials:
        lead.social_links = page_socials

    # Step 3: Wikidata fills whatever is still missing after website fetch
    enrich_from_wikidata(lead, guard)

    has_contact = bool(lead.email or lead.phone or lead.social_links)
    lead.notes = (
        "Contact details and/or social links found (OSM + website + Wikidata)."
        if has_contact
        else "Website reachable but no public contact details found on page or Wikidata."
    )
    if website_cache:
        website_cache.save(lead)
    return lead