"""Dynamic lead quality and AI-agent fit scoring."""

from __future__ import annotations

import re
from collections.abc import Mapping

import pandas as pd


ACTIVE_WEBSITE_STATUSES = {"200", "202"}
BROKEN_WEBSITE_STATUSES = {"403", "404", "429", "503", "unreachable", "robots_denied"}
HEALTHCARE_PATTERN = re.compile(r"clinic|health|medical|doctor|dental", re.IGNORECASE)
REAL_ESTATE_PATTERN = re.compile(r"real[_ -]?estate|realtor|property|broker", re.IGNORECASE)
HOSPITALITY_PATTERN = re.compile(r"restaurant|food|bar|cafe|bakery|pizza", re.IGNORECASE)


class LeadScorer:
    """Score lead reachability, web health, niche fit, and local presence."""

    def _text(self, value) -> str:
        if value is None or pd.isna(value):
            return ""
        return str(value).strip()

    def _valid_phone(self, value) -> bool:
        return len(re.sub(r"\D", "", self._text(value))) >= 7

    def _valid_email(self, value) -> bool:
        text = self._text(value)
        return "@" in text and "." in text.split("@", 1)[-1]

    def _reachability(self, lead: Mapping) -> tuple[int, int]:
        phone = self._valid_phone(lead.get("phone"))
        email = self._valid_email(lead.get("email"))
        social = bool(self._text(lead.get("social_links")))
        points = (15 if phone else 0) + (15 if email else 0) + (5 if social else 0)
        return points, int(phone) + int(email) + int(social)

    def _website_points(self, status) -> int:
        status_text = self._text(status).lower()
        if status_text in ACTIVE_WEBSITE_STATUSES:
            return 25
        if status_text in BROKEN_WEBSITE_STATUSES:
            return 15
        return 5

    def _niche_points(self, niche) -> int:
        text = self._text(niche)
        if HEALTHCARE_PATTERN.search(text):
            return 25
        if REAL_ESTATE_PATTERN.search(text):
            return 22
        if HOSPITALITY_PATTERN.search(text):
            return 20
        return 10

    def _priority(self, score: int, reachability: int, website_status: str) -> str:
        if reachability == 0:
            return "Low / Disqualified"
        if score >= 80 and website_status in ACTIVE_WEBSITE_STATUSES:
            return "High (AI Agent)"
        if score >= 60:
            return "High (Web + Agent)"
        if score >= 40:
            return "Medium"
        return "Low / Disqualified"

    def _offer(self, reachability: int, website_status: str) -> str:
        if reachability == 0:
            return "Enrichment Required"
        if website_status in ACTIVE_WEBSITE_STATUSES:
            return "AI Agent Integration"
        if website_status in BROKEN_WEBSITE_STATUSES:
            return "Website Rebuild + AI Agent"
        return "Full Web Build"

    def score_lead(self, lead: dict) -> dict:
        """Return the lead dictionary with dynamic scoring fields added."""
        result = dict(lead)
        reachability, contact_count = self._reachability(result)
        website_status = self._text(result.get("website_status")).lower()
        web_points = self._website_points(website_status)
        niche_points = self._niche_points(result.get("niche"))
        local_points = (10 if len(self._text(result.get("location"))) > 4 else 0)
        local_points += 5 if self._text(result.get("source_url")) else 0

        score = reachability + web_points + niche_points + local_points
        if contact_count == 0:
            score = min(score, 25)
        score = max(0, min(100, score))

        result["ai_agent_fit_score"] = score
        result["ai_agent_priority"] = self._priority(score, reachability, website_status)
        result["recommended_offer"] = self._offer(reachability, website_status)
        return result

    def score_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Vectorized batch scoring for DataFrame workloads."""
        scored = df.copy()
        for column in ("phone", "email", "social_links", "website_status", "niche", "location", "source_url"):
            if column not in scored:
                scored[column] = ""
            scored[column] = scored[column].fillna("").astype(str).str.strip()

        phone = scored["phone"].str.replace(r"\D", "", regex=True).str.len().ge(7)
        email = scored["email"].str.contains("@", regex=False) & scored["email"].str.rsplit("@", n=1).str[-1].str.contains(".", regex=False)
        social = scored["social_links"].ne("")
        reachability = phone.astype(int) * 15 + email.astype(int) * 15 + social.astype(int) * 5
        contact_count = phone.astype(int) + email.astype(int) + social.astype(int)

        status = scored["website_status"].str.lower()
        web_points = status.isin(ACTIVE_WEBSITE_STATUSES).astype(int) * 25
        web_points += status.isin(BROKEN_WEBSITE_STATUSES).astype(int) * 15
        web_points += (~status.isin(ACTIVE_WEBSITE_STATUSES | BROKEN_WEBSITE_STATUSES)).astype(int) * 5

        healthcare = scored["niche"].str.contains(HEALTHCARE_PATTERN)
        real_estate = scored["niche"].str.contains(REAL_ESTATE_PATTERN)
        hospitality = scored["niche"].str.contains(HOSPITALITY_PATTERN)
        niche_points = healthcare.astype(int) * 25
        niche_points += (~healthcare & real_estate).astype(int) * 22
        niche_points += (~healthcare & ~real_estate & hospitality).astype(int) * 20
        niche_points += (~healthcare & ~real_estate & ~hospitality).astype(int) * 10

        local_points = (scored["location"].str.len() > 4).astype(int) * 10
        local_points += scored["source_url"].ne("").astype(int) * 5
        total = (reachability + web_points + niche_points + local_points).clip(upper=100)
        total = total.where(contact_count.ne(0), total.clip(upper=25)).astype(int)

        scored["ai_agent_fit_score"] = total
        scored["ai_agent_priority"] = "Low / Disqualified"
        scored.loc[(reachability > 0) & (total >= 40), "ai_agent_priority"] = "Medium"
        scored.loc[(reachability > 0) & (total >= 60), "ai_agent_priority"] = "High (Web + Agent)"
        scored.loc[(reachability > 0) & (total >= 80) & status.isin(ACTIVE_WEBSITE_STATUSES), "ai_agent_priority"] = "High (AI Agent)"

        scored["recommended_offer"] = "Full Web Build"
        scored.loc[reachability.eq(0), "recommended_offer"] = "Enrichment Required"
        scored.loc[reachability.gt(0) & status.isin(ACTIVE_WEBSITE_STATUSES), "recommended_offer"] = "AI Agent Integration"
        scored.loc[reachability.gt(0) & status.isin(BROKEN_WEBSITE_STATUSES), "recommended_offer"] = "Website Rebuild + AI Agent"
        return scored
