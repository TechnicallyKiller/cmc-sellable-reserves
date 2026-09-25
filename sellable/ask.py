"""Ask panel LLM (DECISIONS D7). Any OpenAI-compatible chat endpoint; default Groq free tier.

The model only sees a compact extract of the current live view and is told to
answer from it alone. Any failure (no key, local or upstream rate limit, error,
empty reply) returns None and the frontend falls back to its rule-based answers.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque

BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
MODEL = os.environ.get("LLM_MODEL", "openai/gpt-oss-120b")
# Kept under Groq's free tier for gpt-oss-120b (30 RPM, 1K RPD, 8K TPM).
GLOBAL_PER_MIN = 20
GLOBAL_PER_DAY = 900
IP_PER_MIN = 5
MAX_QUESTION_CHARS = 400
TOP_HOLDINGS = 10

SYSTEM = """You answer questions on "Sellable Reserves", a site that checks crypto exchanges' proof-of-reserves using live CoinMarketCap data.

Definitions used by the site:
- reported_usd: sum of balance x latest price for every wallet CoinMarketCap lists for the exchange (wallets over $500k only; balances have no timestamp; CMC does not verify them).
- sellable_share[N]: share of reported reserves that could be sold within N days, capping each holding at N x that token's global 24h trading volume. A best case: it assumes the exchange could sell into all of the world's trading.
- days_to_sell: holding value / token's global 24h volume. null means zero volume.
- no_market: holdings in tokens with zero recorded 24h trading volume.
- supply_share: exchange's balance / token's circulating supply; null means CMC reports no circulating supply.

Rules:
- Use ONLY the DATA provided. If the answer is not in it, say the data doesn't show that.
- Never tell the user to buy, sell, withdraw, move or keep funds, and never call an exchange safe or unsafe.
- Reserves are assets only; they say nothing about what an exchange owes (not solvency). Say so when relevant.
- Plain language for a non-expert. 2 to 4 sentences. Quote the specific numbers you use. No markdown, no lists, no headings."""


class RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._global_min = deque()
        self._global_day = deque()
        self._ip = defaultdict(deque)

    @staticmethod
    def _trim(q, now, window):
        while q and now - q[0] > window:
            q.popleft()

    def allow(self, ip):
        now = time.monotonic()
        with self._lock:
            self._trim(self._global_min, now, 60)
            self._trim(self._global_day, now, 86400)
            ipq = self._ip[ip]
            self._trim(ipq, now, 60)
            if (len(self._global_min) >= GLOBAL_PER_MIN or len(self._global_day) >= GLOBAL_PER_DAY
                    or len(ipq) >= IP_PER_MIN):
                return False
            for q in (self._global_min, self._global_day, ipq):
                q.append(now)
            return True


def _r(x, nd=4):
    return round(x, nd) if isinstance(x, float) else x


def context(view, slug):
    """Compact JSON extract of the live view for the model."""
    out = {"prices_fetched_at": view.get("quotes_fetched_at"), "coverage": view.get("coverage")}
    ex = view["by_slug"].get(slug) if slug else None
    if ex and ex.get("has_data"):
        out["exchange"] = {
            "name": ex["name"],
            "reported_usd": round(ex["reported_usd"]),
            "sellable_share": {k: _r(v) for k, v in ex["sellable_share"].items()},
            "sellable_usd": {k: round(v) for k, v in ex["sellable_usd"].items()},
            "no_market_share": _r(ex["no_market_share"]),
            "weekly_visits": ex.get("weekly_visits"),
            "notice": ex.get("notice"),
            "wallets_also_listed_by": sorted({n for v in ex.get("shared_wallets", {}).values() for n in v}),
            "token_count": len(ex["holdings"]),
            "top_holdings": [{
                "symbol": h["symbol"], "name": h["name"], "share": _r(h["share"]), "usd": round(h["usd"]),
                "volume_24h": round(h["volume_24h"]), "days_to_sell": _r(h["days_to_sell"], 2),
                "supply_share": _r(h["supply_share"], 6),
            } for h in ex["holdings"][:TOP_HOLDINGS]],
        }
    elif ex:
        out["exchange"] = {"name": ex["name"], "publishes_reserves": False, "weekly_visits": ex.get("weekly_visits")}
    if ex and ex.get("has_data"):
        return json.dumps(out, separators=(",", ":"))
    # No single exchange in view: give one line per exchange instead (~4K chars).
    out["all_exchanges"] = [{
        "name": e["name"], "reported_usd": round(e["reported_usd"]),
        "sellable_7d": _r(e["sellable_share"][7], 3),
        "no_market": _r(e["no_market_share"], 3), "top": e.get("top_symbol"),
        **({"notice": True} if e.get("notice") else {}),
    } for e in view["exchanges"] if e.get("has_data")]
    return json.dumps(out, separators=(",", ":"))


class Asker:
    def __init__(self, key=None):
        self.key = key if key is not None else os.environ.get("LLM_API_KEY")
        self.limiter = RateLimiter()

    @property
    def enabled(self):
        return bool(self.key)

    def ask(self, view, question, slug, ip):
        """Return (answer_text, reason). answer_text is None when the caller should fall back."""
        if not self.enabled:
            return None, "no_llm"
        question = (question or "").strip()[:MAX_QUESTION_CHARS]
        if not question:
            return None, "empty"
        if not self.limiter.allow(ip):
            return None, "rate_limited"
        body = json.dumps({
            "model": MODEL,
            "temperature": 0.2,
            "max_completion_tokens": 700,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"DATA:\n{context(view, slug)}\n\nQUESTION: {question}"},
            ],
        }).encode()
        req = urllib.request.Request(f"{BASE_URL}/chat/completions", data=body, headers={
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            return None, "upstream_rate_limited" if e.code == 429 else f"upstream_{e.code}"
        except (urllib.error.URLError, TimeoutError, ValueError):
            return None, "upstream_error"
        try:
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            return None, "bad_response"
        return (text, "ok") if text else (None, "empty_reply")
