"""
Enrich a Lead by fetching ITS OWN website (never a third-party page) and
pulling out a public email, phone, and social links, if present.

WHY THIS FILE EXISTS:
This isolates "touch a business's own website" from everything else, so
the one part of the pipeline that talks to arbitrary third-party servers
has its own careful retry/backoff and robots.txt handling (via Guard,
see policy.py for the robots.txt fail-open fix).

If a website can't be reached (blocked, gone, timed out) the lead is NOT
thrown away -- it's kept with website_status set to explain why, since a
business with a broken website is still a real business (and arguably a
better prospect for "we can rebuild your web presence").
"""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup

from .models import Lead
from .policy import Guard, retry_request
from .utils import extract_emails, extract_social_links, PHONE_RE, normalize_phone, normalize_url


def verify_website(lead: Lead, guard: Guard, phone_region: str = "PK") -> Lead:
    if not lead.website:
        lead.website_status = "no_website_found"
        lead.notes = lead.notes or "No public website URL discovered for this business."
        return lead

    url = normalize_url(lead.website)
    if not guard.allowed(url):
        lead.website_status = "robots_denied"
        lead.notes = "Website's robots.txt explicitly disallows automated access."
        return lead

    host = url.split("/")[2] if "://" in url else url
    response = retry_request(
        lambda: requests.get(url, headers={"User-Agent": guard.user_agent}, timeout=15),
        max_attempts=3,
    )

    if response is None:
        lead.website_status = "unreachable"
        lead.notes = "Website did not respond after retries."
        return lead

    if response.status_code in (403, 404, 410, 429):
        lead.website_status = str(response.status_code)
        lead.notes = f"Website unavailable: HTTP {response.status_code} (kept as a potential rebuild prospect)"
        return lead

    if response.status_code != 200:
        lead.website_status = str(response.status_code)
        lead.notes = f"Website returned HTTP {response.status_code}"
        return lead

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    emails = extract_emails(response.text)
    phones = list(dict.fromkeys(PHONE_RE.findall(text)))

    lead.website_status = "200"
    lead.email = emails[0] if emails else lead.email
    lead.phone = normalize_phone(phones[0], phone_region) if phones else lead.phone
    lead.social_links = extract_social_links(response.text) or lead.social_links
    lead.notes = (
        "Contact details and/or social links found on the business's own website"
        if (emails or phones or lead.social_links)
        else "Website reachable but no public contact details found on the page"
    )
    return lead
