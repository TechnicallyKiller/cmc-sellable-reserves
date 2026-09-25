"""Ask panel LLM (DECISIONS D7). Any OpenAI-compatible chat endpoint; default Groq free tier.

The model only sees a compact extract of the current live view and is told to
answer from it alone. Any failure (no key, local or upstream rate limit, error,
empty reply) returns None and the frontend falls back to its rule-based answers.
"""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict, deque

BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1")
# Tried in order; Groq's free-tier limits are per model, so the second model
# adds capacity when the first returns 429.
MODELS = [m.strip() for m in os.environ.get("LLM_MODELS", "openai/gpt-oss-120b,openai/gpt-oss-20b").split(",") if m.strip()]
MODEL = MODELS[0]
# Groq's Cloudflare front rejects Python's default urllib User-Agent (error 1010).
USER_AGENT = "sellable-reserves/1.0 (+https://github.com/TechnicallyKiller/cmc-sellable-reserves)"
# Kept under Groq's free tier for gpt-oss-120b (30 RPM, 1K RPD, 8K TPM).
GLOBAL_PER_MIN = 20
GLOBAL_PER_DAY = 900
IP_PER_MIN = 5
MAX_QUESTION_CHARS = 400
TOP_HOLDINGS = 10

SYSTEM = """You answer questions on "Sellable Reserves", a site that checks crypto exchanges' proof-of-reserves using live CoinMarketCap data.

Fields in DATA (all money is US dollars, all *_pct are percentages 0-100):
- reported_usd: sum of balance x latest price for every wallet CoinMarketCap lists for the exchange (wallets over $500k only; balances have no timestamp; CMC does not verify them).
- sellable_pct["1"|"7"|"30"]: share of reported reserves that could be sold within 1, 7 or 30 days, capping each holding at days x that token's global 24h trading volume in dollars. A best case: it assumes the exchange could sell into all of the world's trading.
- volume_24h_usd: the token's global trading volume over 24 hours, in dollars.
- days_to_sell: holding value / volume_24h_usd. null means zero volume.
- no_market_pct: share of reserves in tokens with zero 24h trading volume.
- supply_pct: exchange's balance as a share of the token's circulating supply; null means CMC reports no circulating supply.

Rules:
- Use ONLY the DATA provided. If the answer is not in it, say the data doesn't show that.
- Never tell the user to buy, sell, withdraw, move or keep funds, and never call an exchange safe or unsafe.
- Reserves are assets only; they say nothing about what an exchange owes (not solvency). Mention this only when the question is about safety, risk or solvency.
- Write for a non-expert: 2 to 4 short sentences, no markdown, no lists.
- Round like a person: money as $1.4B, $406M, $186K; percentages as whole numbers ("under 1%" when below 1); days as whole numbers, or years when over two years.
- Never mention field names or raw decimals."""


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


def _pct(x):
    return None if x is None else round(x * 100, 1)


def _money(x):
    return None if x is None else float(f"{x:.3g}")


def context(view, slug):
    """Compact JSON extract of the live view for the model: pre-rounded, dollar-labelled."""
    out = {"prices_fetched_at": view.get("quotes_fetched_at"), "coverage": view.get("coverage")}
    ex = view["by_slug"].get(slug) if slug else None
    if ex and ex.get("has_data"):
        out["exchange"] = {
            "name": ex["name"],
            "reported_usd": _money(ex["reported_usd"]),
            "sellable_pct": {str(k): _pct(v) for k, v in ex["sellable_share"].items()},
            "sellable_usd": {str(k): _money(v) for k, v in ex["sellable_usd"].items()},
            "no_market_pct": _pct(ex["no_market_share"]),
            "weekly_visits": ex.get("weekly_visits"),
            "notice": ex.get("notice"),
            "wallets_also_listed_by": sorted({n for v in ex.get("shared_wallets", {}).values() for n in v}),
            "token_count": len(ex["holdings"]),
            "top_holdings": [{
                "symbol": h["symbol"], "name": h["name"], "share_pct": _pct(h["share"]), "value_usd": _money(h["usd"]),
                "volume_24h_usd": _money(h["volume_24h"]),
                "days_to_sell": None if h["days_to_sell"] is None else round(h["days_to_sell"], 1),
                "supply_pct": None if h["supply_share"] is None else round(h["supply_share"] * 100, 3),
            } for h in ex["holdings"][:TOP_HOLDINGS]],
        }
        return json.dumps(out, separators=(",", ":"))
    if ex:
        out["exchange"] = {"name": ex["name"], "publishes_reserves": False, "weekly_visits": ex.get("weekly_visits")}
    # No single exchange with data in view: one line per exchange instead.
    out["all_exchanges"] = [{
        "name": e["name"], "reported_usd": _money(e["reported_usd"]),
        "sellable_7d_pct": _pct(e["sellable_share"][7]), "no_market_pct": _pct(e["no_market_share"]),
        "largest_holding": e.get("top_symbol"), **({"has_notice": True} if e.get("notice") else {}),
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
        """Return (answer_text, model_or_reason). answer_text is None when the caller should fall back."""
        if not self.enabled:
            return None, "no_llm"
        question = (question or "").strip()[:MAX_QUESTION_CHARS]
        if not question:
            return None, "empty"
        if not self.limiter.allow(ip):
            return None, "rate_limited"
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"DATA:\n{context(view, slug)}\n\nQUESTION: {question}"},
        ]
        reason = "no_model"
        for model in MODELS:
            text, reason = self._complete(model, messages)
            if text is not None:
                return text, model
            if reason != "upstream_rate_limited":
                break
        return None, reason

    def _complete(self, model, messages):
        body = json.dumps({
            "model": model,
            "temperature": 0.2,
            "max_completion_tokens": 700,
            "messages": messages,
        }).encode()
        req = urllib.request.Request(f"{BASE_URL}/chat/completions", data=body, headers={
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        })
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            return None, "upstream_rate_limited" if e.code == 429 else f"upstream_{e.code}"
        except (urllib.error.URLError, TimeoutError, ValueError):
            return None, "upstream_error"
        usage = data.get("usage") or {}
        logging.getLogger("ask").info("llm usage (%s): prompt=%s completion=%s total=%s", model,
                                      usage.get("prompt_tokens"), usage.get("completion_tokens"), usage.get("total_tokens"))
        try:
            text = (data["choices"][0]["message"]["content"] or "").strip()
        except (KeyError, IndexError, TypeError):
            return None, "bad_response"
        return (text, "ok") if text else (None, "empty_reply")
