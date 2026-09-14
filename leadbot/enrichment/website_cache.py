"""Persistent cache for website verification results."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from ..core.models import Lead


class WebsiteCache:
    """SQLite cache that survives process restarts and is safe for workers."""

    def __init__(self, path: str = "website_cache.sqlite3", ttl_seconds: int = 604800):
        self.path = Path(path)
        self.ttl_seconds = max(0, int(ttl_seconds))
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.execute(
            """CREATE TABLE IF NOT EXISTS website_cache (
                cache_key TEXT PRIMARY KEY,
                fetched_at REAL NOT NULL,
                website_status TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                social_links TEXT NOT NULL,
                notes TEXT NOT NULL
            )"""
        )
        self._connection.commit()

    @staticmethod
    def _key(website: str) -> str:
        return website.strip().lower().rstrip("/")

    def load(self, lead: Lead) -> bool:
        """Apply a fresh cached result; return False when no result is usable."""
        if not lead.website:
            return False
        key = self._key(lead.website)
        with self._lock:
            row = self._connection.execute(
                "SELECT fetched_at, website_status, email, phone, social_links, notes "
                "FROM website_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if not row or time.time() - row[0] >= self.ttl_seconds:
            return False
        lead.website_status = row[1]
        if not lead.email:
            lead.email = row[2]
        if not lead.phone:
            lead.phone = row[3]
        if not lead.social_links:
            lead.social_links = row[4]
        lead.notes = row[5]
        return True

    def save(self, lead: Lead) -> None:
        if not lead.website:
            return
        key = self._key(lead.website)
        with self._lock:
            self._connection.execute(
                """INSERT INTO website_cache
                   (cache_key, fetched_at, website_status, email, phone, social_links, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET
                     fetched_at=excluded.fetched_at,
                     website_status=excluded.website_status,
                     email=excluded.email,
                     phone=excluded.phone,
                     social_links=excluded.social_links,
                     notes=excluded.notes""",
                (
                    key,
                    time.time(),
                    lead.website_status,
                    lead.email,
                    lead.phone,
                    lead.social_links,
                    lead.notes,
                ),
            )
            self._connection.commit()

    def close(self) -> None:
        """Close the SQLite connection during a clean process shutdown."""
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
