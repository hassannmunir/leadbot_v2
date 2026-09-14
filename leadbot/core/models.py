"""
Data model for a single lead (one business record).

WHY THIS FILE EXISTS:
Every part of the pipeline (OSM source, website checker, storage) needs to
agree on what a "lead" looks like and how two leads are compared to detect
duplicates. Keeping that in one place avoids the bug we found in the old
code, where main.py and models.py each computed their own, different,
duplicate-detection key.
"""

from dataclasses import dataclass, asdict, field
from urllib.parse import urlparse
import re


def normalize_domain(website: str) -> str:
    """
    Turn a website URL into a bare domain for comparison, e.g.
    'https://www.acme-clinic.com/contact?x=1' -> 'acme-clinic.com'

    We strip 'www.' because 'acme.com' and 'www.acme.com' are the same
    business, and comparing full URLs would treat them as different.
    """
    if not website:
        return ""
    website = website.strip()
    if "://" not in website:
        website = "https://" + website
    try:
        host = urlparse(website).netloc.lower()
    except ValueError:
        return ""
    host = host.split(":")[0]  # drop a port number if present
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_name(name: str) -> str:
    """Lowercase + strip punctuation, used only as a last-resort dedup key."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


@dataclass
class Lead:
    name: str
    niche: str = ""
    source: str = ""          # e.g. "openstreetmap", "website"
    source_url: str = ""
    website: str = ""
    website_status: str = ""  # "200", "404", "robots_denied", "no_website_found", ...
    ai_agent_fit_score: int = 0
    ai_agent_priority: str = ""
    ai_agent_opportunities: str = ""
    recommended_offer: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    country: str = ""
    region: str = ""
    social_links: str = ""
    notes: str = ""

    def as_dict(self):
        return asdict(self)

    @property
    def dedup_key(self) -> str:
        """
        The ONE key used everywhere to decide "is this the same business?".
        Priority: website domain > email > phone digits > normalized name.
        A website domain is the most reliable signal (two different real
        businesses essentially never share a domain); name alone is the
        weakest, used only when nothing else is available.
        """
        domain = normalize_domain(self.website)
        if domain:
            return f"domain:{domain}"
        if self.email:
            return f"email:{self.email.strip().lower()}"
        phone_digits = re.sub(r"\D", "", self.phone or "")
        if len(phone_digits) >= 7:
            return f"phone:{phone_digits}"
        return f"name:{normalize_name(self.name)}"


LEAD_FIELDS = list(Lead.__dataclass_fields__)
