"""Shared helpers: URL/phone normalization, email/social extraction, scoring."""

from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+?\d[\d ()-]{7,}\d)")
SOCIAL_HOSTS = ("facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com", "youtube.com", "tiktok.com")

# A handful of niche keywords -> what an AI agent could plausibly help with.
# This is a heuristic for prioritizing outreach, never a factual claim.
AI_FIT_OPPORTUNITIES = {
    "restaurant": "reservations, menu/order questions, delivery updates",
    "cafe": "reservations, menu/order questions",
    "clinic": "appointment booking, FAQs, reminders and intake",
    "dentist": "appointment booking, FAQs, reminders and intake",
    "doctor": "appointment booking, FAQs, reminders and intake",
    "hospital": "appointment booking, FAQs, patient intake",
    "real_estate": "property qualification, viewing bookings and follow-up",
    "hotel": "availability questions, booking support, concierge FAQs",
    "school": "admissions FAQs, enquiry qualification and scheduling",
    "university": "admissions FAQs, enquiry qualification and scheduling",
    "law_firm": "intake forms, consultation booking and FAQs",
    "it_company": "demo qualification, onboarding and customer support",
    "gym": "trial booking, membership FAQs and reminders",
    "salon": "appointment booking and reminders",
    "spa": "appointment booking and reminders",
    "auto_repair": "booking, quote requests and status updates",
}


def normalize_url(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("//"):
        return "https:" + value
    if "." in value:
        return "https://" + value
    return value


def normalize_phone(value, region: str = "PK") -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return ""
    raw = re.sub(r"[^\d+]", "", text)
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if raw.startswith("+"):
        return raw
    if region.upper() == "PK" and raw.startswith("0") and len(raw) >= 10:
        return "+92" + raw[1:]
    if region.upper() == "US" and len(raw) == 10:
        return "+1" + raw
    return raw


def extract_emails(raw_html: str) -> list[str]:
    text = html.unescape(raw_html or "")
    found = EMAIL_RE.findall(text.replace("[at]", "@").replace("(at)", "@"))
    found += [m.split("?", 1)[0] for m in re.findall(r"mailto:([^\"' >]+)", text, re.I)]
    cleaned = [e.strip(" .,;:()[]<>").lower() for e in found if "@" in e]
    return list(dict.fromkeys(cleaned))  # de-dupe, keep order


def extract_social_links(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html or "", "html.parser")
    seen, links = set(), []
    for a in soup.find_all("a", href=True):
        href = normalize_url(a["href"].strip())
        if href and href not in seen and any(h in href.lower() for h in SOCIAL_HOSTS):
            seen.add(href)
            links.append(href)
    return " | ".join(links)


def quality_score(lead) -> int:
    score = 0
    if lead.name:
        score += 15
    if lead.niche:
        score += 15
    if lead.website:
        score += 20
    if lead.email and not any(x in lead.email.lower() for x in ("gmail.", "yahoo.", "hotmail.", "outlook.")):
        score += 25
    if lead.phone:
        score += 15
    if lead.location:
        score += 10
    return score


def assess_ai_agent_fit(lead):
    text = f"{lead.niche}".lower()
    match = AI_FIT_OPPORTUNITIES.get(text)
    if match:
        lead.ai_agent_fit_score = 70
        lead.ai_agent_priority = "high"
        lead.ai_agent_opportunities = match
    else:
        lead.ai_agent_fit_score = 30
        lead.ai_agent_priority = "low"
        lead.ai_agent_opportunities = ""
    return lead
