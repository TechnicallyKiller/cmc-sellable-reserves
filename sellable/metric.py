"""Row cleaning (DECISIONS D8), sellable-reserves metric (D2), plain sentences (D6)."""
import re
from collections import defaultdict

HORIZONS = (1, 7, 30)
HEADLINE_HORIZON = 7
MILESTONES = (0.5, 0.9)
# Liquidity buckets by days to sell; index 5 is "no market" (zero 24h volume).
BUCKETS = ((1, "Under a day"), (7, "1–7 days"), (30, "1–4 weeks"), (365, "1–12 months"), (float("inf"), "Over a year"))
NO_MARKET_BUCKET = len(BUCKETS)
TOP_CHAINS = 7


def bucket_of(days_to_sell):
    if days_to_sell is None:
        return NO_MARKET_BUCKET
    return next(i for i, (edge, _) in enumerate(BUCKETS) if days_to_sell < edge)
# 1 to 365 days, log-spaced, for the liquidity curve.
CURVE_DAYS = [round(365 ** (i / 59), 4) for i in range(60)]
_EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")


def normalise_address(addr):
    # EVM addresses are case-insensitive; other formats (base58 etc.) are not.
    return addr.lower() if _EVM.match(addr) else addr


def clean_rows(rows):
    """Collapse rows identical in (address, platform, token, balance).

    Returns (rows, collapsed_count). Rows sharing a key with different balances
    are kept; they are summed during aggregation.
    """
    seen = set()
    kept = []
    for r in rows:
        key = (normalise_address(r["wallet_address"]), r["platform"]["crypto_id"],
               r["currency"]["crypto_id"], r["balance"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)
    return kept, len(rows) - len(kept)


def shared_wallets(assets_by_exchange):
    """{normalised address: sorted exchange ids} for wallets listed by >1 exchange."""
    owners = defaultdict(set)
    for ex_id, rows in assets_by_exchange.items():
        for r in rows:
            owners[normalise_address(r["wallet_address"])].add(ex_id)
    return {a: sorted(ids) for a, ids in owners.items() if len(ids) > 1}


def compute_exchange(rows, quotes):
    """Aggregate one exchange's cleaned rows against quotes.

    Holdings are split into three buckets that are never merged:
      - priced with volume > 0  -> contribute to sellable
      - volume == 0             -> "no market"
      - token missing in quotes -> "unpriced"
    """
    by_token = defaultdict(lambda: {"balance": 0.0, "wallets": []})
    for r in rows:
        t = by_token[r["currency"]["crypto_id"]]
        t["balance"] += r["balance"]
        t["symbol"] = r["currency"]["symbol"]
        t["name"] = r["currency"]["name"]
        t["wallets"].append({
            "address": r["wallet_address"],
            "platform": r["platform"]["name"],
            "balance": r["balance"],
        })

    holdings = []
    unpriced = []
    for token_id, t in by_token.items():
        q = quotes.get(token_id)
        if q is None:
            unpriced.append({"token_id": token_id, "symbol": t["symbol"], "balance": t["balance"]})
            continue
        usd = t["balance"] * q["price"]
        vol = q["volume_24h"]
        circ = q["circulating_supply"]
        holdings.append({
            "token_id": token_id,
            "symbol": t["symbol"],
            "name": t["name"],
            "balance": t["balance"],
            "price": q["price"],
            "usd": usd,
            "volume_24h": vol,
            "days_to_sell": usd / vol if vol > 0 else None,
            "supply_share": t["balance"] / circ if circ > 0 else None,
            "quote_last_updated": q["last_updated"],
            "cex_share": _cex_share(q),
            "chains": sorted({w["platform"] for w in t["wallets"]}),
            "wallets": t["wallets"],
        })
    holdings.sort(key=lambda h: h["usd"], reverse=True)

    reported = sum(h["usd"] for h in holdings)
    no_market = sum(h["usd"] for h in holdings if h["volume_24h"] == 0)
    sellable = {
        n: sum(min(h["usd"], n * h["volume_24h"]) for h in holdings if h["volume_24h"] > 0)
        for n in HORIZONS
    }
    for h in holdings:
        h["share"] = h["usd"] / reported if reported else None

    liquid = [h for h in holdings if h["volume_24h"] > 0]
    for h in holdings:
        h["bucket"] = bucket_of(h["days_to_sell"])
    return {
        "buckets": _buckets(holdings, reported),
        "chains": _chains(holdings, reported),
        "concentration": _concentration(holdings),
        "curve": [[d, sellable_at(liquid, d) / reported if reported else None] for d in CURVE_DAYS],
        "ceiling_share": (reported - no_market) / reported if reported else None,
        "days_to_share": {str(int(f * 100)): days_to_reach(liquid, f * reported) for f in MILESTONES},
        "reported_usd": reported,
        "sellable_usd": sellable,
        "sellable_share": {n: (v / reported if reported else None) for n, v in sellable.items()},
        "no_market_usd": no_market,
        "no_market_share": no_market / reported if reported else None,
        "holdings": holdings,
        "unpriced": unpriced,
    }


def _cex_share(q):
    """Share of the token's 24h volume on centralized exchanges; None when CMC gives no split."""
    cex, dex = q.get("cex_volume_24h"), q.get("dex_volume_24h")
    if cex is None or dex is None or cex + dex <= 0:
        return None
    return cex / (cex + dex)


def _buckets(holdings, reported):
    labels = [lab for _, lab in BUCKETS] + ["No market"]
    out = [{"label": lab, "usd": 0.0, "tokens": 0} for lab in labels]
    for h in holdings:
        out[h["bucket"]]["usd"] += h["usd"]
        out[h["bucket"]]["tokens"] += 1
    for b in out:
        b["share"] = b["usd"] / reported if reported else None
    return out


def _chains(holdings, reported):
    """Reported value by blockchain (CoinMarketCap's platform name), top chains plus the rest."""
    by = defaultdict(float)
    for h in holdings:
        for w in h["wallets"]:
            by[w["platform"]] += w["balance"] * h["price"]
    ranked = sorted(by.items(), key=lambda kv: kv[1], reverse=True)
    out = [{"chain": c, "usd": v} for c, v in ranked[:TOP_CHAINS]]
    rest = ranked[TOP_CHAINS:]
    if rest:
        out.append({"chain": f"{len(rest)} other chain{'s' if len(rest) > 1 else ''}", "usd": sum(v for _, v in rest), "other": True})
    for c in out:
        c["share"] = c["usd"] / reported if reported else None
    return out


def _concentration(holdings):
    shares = [h["share"] for h in holdings if h["share"]]
    if not shares:
        return None
    return {
        "top1_share": shares[0],
        "top5_share": sum(shares[:5]),
        # Inverse Herfindahl index: reserves behave like this many equal-sized holdings.
        "effective_tokens": 1 / sum(x * x for x in shares),
        "tokens": len(shares),
        "wallets": len({w["address"].lower() for h in holdings for w in h["wallets"]}),
        "chains": len({w["platform"] for h in holdings for w in h["wallets"]}),
    }


def sellable_at(liquid, days):
    """USD sellable within `days`: each holding capped at days × its 24h volume."""
    return sum(min(h["usd"], days * h["volume_24h"]) for h in liquid)


def days_to_reach(liquid, target_usd):
    """Exact days until `target_usd` becomes sellable, or None if never.

    sellable(d) = Σ usd_i over holdings already fully sold by day d
                + d × Σ volume_i over the rest.
    It is piecewise linear with breakpoints at each holding's days_to_sell,
    so solve it segment by segment. Zero-volume holdings never count.
    """
    if target_usd <= 0:
        return 0.0
    rows = sorted(liquid, key=lambda h: h["usd"] / h["volume_24h"])
    done_usd = 0.0
    rest_vol = sum(h["volume_24h"] for h in rows)
    prev = 0.0
    for h in rows:
        brk = h["usd"] / h["volume_24h"]
        at_brk = done_usd + brk * rest_vol
        if at_brk >= target_usd:
            return max(prev, (target_usd - done_usd) / rest_vol)
        done_usd += h["usd"]
        rest_vol -= h["volume_24h"]
        prev = brk
    return None  # target exceeds everything sellable (no-market holdings block it)


def money_label(x):
    """Same rounding as the frontend: 3 significant figures, $B/$M/$K."""
    if x is None:
        return None
    if x == 0:
        return "$0"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if x >= div:
            return f"${float(f'{x / div:.3g}'):g}{unit}"
    return f"${x:.2f}"


def pct_label(x):
    """Same rules as the frontend's pctLabel."""
    if x is None:
        return None
    if x == 0:
        return "0%"
    if x < 0.01:
        return "under 1%"
    if 0.995 <= x < 1:
        return "99%"
    return f"{round(x * 100)}%"


def days_label(d):
    if d is None:
        return "never (no trading in the last 24 hours)"
    if d < 0.1:
        return "under 0.1 days"
    return duration(d)


def _pct(x):
    p = x * 100
    return f"{p:.0f}%" if p >= 1 or p == 0 else "Under 1%"


def sentence(name, result, horizon=HEADLINE_HORIZON):
    """One plain-language summary, built only from computed values."""
    reported = result["reported_usd"]
    if not reported:
        return f"{name} does not publish any reserves that CoinMarketCap tracks."
    share = result["sellable_share"][horizon]
    span = {1: "a day", 7: "a week", 30: "a month"}[horizon]
    if share == 0:
        amount = "None of it"
    elif share < 0.01:
        amount = "Less than 1% of it"
    else:
        amount = f"About {share * 100:.0f}% of it"
    parts = [f"{name} shows {money_label(reported)} in reserves.",
             f"{amount} could be sold within {span}."]
    worst = biggest_blocker(result, horizon)
    if worst is not None:
        if worst["volume_24h"] == 0:
            parts.append(f"{_pct(worst['share'])} is in {worst['symbol']}, "
                         f"which had no trading at all in the last 24 hours.")
        else:
            parts.append(f"{_pct(worst['share'])} is in {worst['symbol']}; selling it would take "
                         f"{duration(worst['days_to_sell'])} of the whole world's trading in {worst['symbol']}.")
    return " ".join(parts)


def duration(days):
    if days >= 730:
        return f"about {days / 365:,.0f} years"
    if days >= 2:
        return f"{days:,.0f} days"
    return f"{days:.1f} days"


def unsellable_usd(h, horizon):
    if h["volume_24h"] == 0:
        return h["usd"]
    return h["usd"] - min(h["usd"], horizon * h["volume_24h"])


def biggest_blocker(result, horizon):
    """The holding that leaves the most value unsellable within the horizon, or None."""
    blockers = [h for h in result["holdings"] if unsellable_usd(h, horizon) > 0]
    return max(blockers, key=lambda h: unsellable_usd(h, horizon)) if blockers else None
