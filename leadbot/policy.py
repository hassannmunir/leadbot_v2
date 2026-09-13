"""
Safety and quota layer.

WHY THIS FILE EXISTS:
This is the single place that decides "are we allowed to make this request
right now, and how do we behave if it fails?" Three separate jobs live here
on purpose, because the old code mixed them up and got each one slightly
wrong:

1. Guard         -> per-host pacing (don't hammer a site) + robots.txt check
2. retry_request -> uniform retry-with-backoff for any HTTP call
3. QuotaTracker  -> a persistent daily counter per API provider, so we NEVER
                    get close to a provider's daily free-tier limit

Bugs fixed vs the old policy.py:
- robots.txt fetch failing (timeout, bad SSL, DNS glitch) used to mean
  "assume disallowed" -> real, legit small-business sites were being
  skipped for no good reason. Now: a robots.txt fetch failure means
  "assume allowed" (this is the common, industry-normal default -- absence
  of a readable robots.txt is not a disallow signal).
- robots.txt fetch had no timeout, so one slow site could hang everything.
- A 429 used to permanently block a host for the rest of the run. Now we
  back off and retry a bounded number of times instead, since rate limits
  are almost always temporary.
"""

import json
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests


class Guard:
    """Deliberately simple safety layer: no proxy rotation, no CAPTCHA bypass, no stealth."""

    def __init__(self, delay=3.0, user_agent="LeadBot/2.0 (+contact-your-business)"):
        self.delay = max(2.0, delay)
        self.user_agent = user_agent
        self._last_request_at = {}

    def wait(self, host: str):
        """Block just long enough to keep at least `delay` seconds between requests to `host`."""
        gap = self.delay - (time.monotonic() - self._last_request_at.get(host, 0))
        if gap > 0:
            time.sleep(gap)
        self._last_request_at[host] = time.monotonic()

    def allowed(self, url: str) -> bool:
        """
        Check robots.txt for `url`. Fails OPEN (returns True) if robots.txt
        can't be read at all -- see the module docstring for why.
        """
        parsed = urlparse(url)
        host = parsed.netloc
        self.wait(host)
        robots_url = f"{parsed.scheme}://{host}/robots.txt"
        parser = RobotFileParser(robots_url)
        try:
            response = requests.get(
                robots_url, headers={"User-Agent": self.user_agent}, timeout=8
            )
            if response.status_code >= 400:
                return True  # no readable robots.txt -> nothing to disallow
            parser.parse(response.text.splitlines())
            return parser.can_fetch(self.user_agent, url)
        except requests.RequestException:
            return True  # network hiccup -> don't punish the business for it


def retry_request(request_fn, max_attempts=3, backoff_seconds=4, retry_statuses=(429, 500, 502, 503, 504)):
    """
    Call `request_fn()` (a zero-argument function that returns a
    requests.Response) and retry with exponential backoff if it fails or
    comes back with a retry-able status code.

    Returns the Response on success, or None if every attempt failed --
    callers should treat None as "skip this one, move on", never as a
    crash.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            response = request_fn()
        except requests.RequestException:
            response = None

        if response is not None and response.status_code not in retry_statuses:
            return response  # success OR a non-retryable error (e.g. 404) -- caller decides

        if attempt < max_attempts:
            time.sleep(backoff_seconds * attempt)  # 4s, 8s, 12s...
    return response  # last attempt's result (may be None or a bad status)


class QuotaTracker:
    """
    Persists "how many calls has provider X made today" to a small JSON
    file, so limits are respected even across separate runs of the tool
    on the same day. This is the piece that was completely missing from
    the old code -- it only ever paced individual requests, never tracked
    a running total against a daily cap.
    """

    def __init__(self, path="quota_state.json"):
        self.path = Path(path)
        self._state = self._load()

    def _load(self):
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self):
        try:
            self.path.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except OSError:
            pass  # quota tracking is best-effort; never crash the run over a disk write

    def _today_count(self, provider: str) -> int:
        today = date.today().isoformat()
        entry = self._state.get(provider, {})
        if entry.get("date") != today:
            return 0
        return entry.get("count", 0)

    def can_use(self, provider: str, daily_limit: int, buffer: int = 2) -> bool:
        """
        True if using this provider one more time would still stay under
        (daily_limit - buffer). The buffer is the "stop at 18 out of a 20
        limit" margin.
        """
        return self._today_count(provider) < max(0, daily_limit - buffer)

    def record_use(self, provider: str, n: int = 1):
        today = date.today().isoformat()
        entry = self._state.get(provider, {})
        if entry.get("date") != today:
            entry = {"date": today, "count": 0}
        entry["count"] = entry.get("count", 0) + n
        self._state[provider] = entry
        self._save()

    def remaining(self, provider: str, daily_limit: int, buffer: int = 2) -> int:
        return max(0, daily_limit - buffer - self._today_count(provider))
