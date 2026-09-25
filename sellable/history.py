"""Hourly sellable-share history in Supabase (Postgres via its REST API).

Optional: enabled when SUPABASE_URL and SUPABASE_SERVICE_KEY are set. The service
key stays on the server; the table has row-level security on and no policies,
so the browser can never reach it directly. Schema: docs/supabase_schema.sql.
"""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .ask import USER_AGENT

log = logging.getLogger("history")
TABLE = "sellable_history"
CACHE_S = 300
DEFAULT_DAYS = 30


def iso_from_ts(ts):
    """'20260925T031451Z' -> '2026-09-25T03:14:51+00:00'."""
    return datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()


class History:
    def __init__(self, url=None, key=None):
        self.url = (url if url is not None else os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key if key is not None else os.environ.get("SUPABASE_SERVICE_KEY", "")
        self._last_hour = None
        self._cache = {}
        self._lock = threading.Lock()

    @property
    def enabled(self):
        return bool(self.url and self.key)

    def _request(self, method, path, body=None, extra_headers=None):
        req = urllib.request.Request(f"{self.url}/rest/v1/{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"apikey": self.key, "Authorization": f"Bearer {self.key}",
                                              "Content-Type": "application/json", "User-Agent": USER_AGENT,
                                              **(extra_headers or {})})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    @staticmethod
    def rows_from_view(view):
        at = iso_from_ts(view["quotes_fetched_at"])
        return [{
            "fetched_at": at, "exchange_id": e["id"], "slug": e["slug"], "name": e["name"],
            "reported_usd": e["reported_usd"],
            "sellable_1d": e["sellable_share"][1], "sellable_7d": e["sellable_share"][7],
            "sellable_30d": e["sellable_share"][30], "no_market": e["no_market_share"],
        } for e in view["exchanges"] if e.get("has_data")]

    def record(self, view):
        """Write one row per exchange, at most once per clock hour."""
        if not self.enabled or not view.get("quotes_fetched_at"):
            return
        hour = view["quotes_fetched_at"][:11]
        if hour == self._last_hour:
            return
        rows = self.rows_from_view(view)
        if not rows:
            return
        try:
            self._request("POST", f"{TABLE}?on_conflict=slug,fetched_at", rows,
                          {"Prefer": "resolution=ignore-duplicates,return=minimal"})
        except (urllib.error.URLError, OSError, ValueError) as err:
            log.error("history write failed: %s", getattr(err, "code", err))
            return
        self._last_hour = hour
        log.info("history: wrote %d rows for %s", len(rows), view["quotes_fetched_at"])

    def series(self, slug, days=DEFAULT_DAYS):
        """[{fetched_at, sellable_1d, sellable_7d, sellable_30d, no_market, reported_usd}], oldest first."""
        if not self.enabled:
            return None
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(slug)
            if hit and now - hit[0] < CACHE_S:
                return hit[1]
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        q = urllib.parse.urlencode({
            "select": "fetched_at,sellable_1d,sellable_7d,sellable_30d,no_market,reported_usd",
            "slug": f"eq.{slug}", "fetched_at": f"gte.{since}", "order": "fetched_at.asc", "limit": "2000",
        })
        try:
            data = self._request("GET", f"{TABLE}?{q}")
        except (urllib.error.URLError, OSError, ValueError) as err:
            log.error("history read failed: %s", getattr(err, "code", err))
            return None
        with self._lock:
            self._cache[slug] = (now, data)
        return data
