"""MCP server (Streamable HTTP) exposing Sellable Reserves as read-only tools.

Dual-era, per the MCP spec:
- Modern (2026-07-28): stateless; every request carries `_meta` with the
  protocol version and client capabilities; headers MCP-Protocol-Version,
  Mcp-Method and (for tools/call) Mcp-Name must match the body.
- Legacy (2025-11-25, 2025-06-18, 2025-03-26): `initialize` handshake. No
  sessions are minted (the server is stateless either way).

Tools read the same in-memory view the website serves, so agent calls never
spend CMC credits. Every result states the data's limits and links receipts.
"""
import base64
import difflib
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque

from . import metric

MODERN = "2026-07-28"
LEGACY = ("2025-11-25", "2025-06-18", "2025-03-26")
SUPPORTED = (MODERN,) + LEGACY
SERVER_INFO = {"name": "sellable-reserves", "title": "Sellable Reserves", "version": "1.0.0"}
PER_IP_PER_MIN = 60
CACHE_TTL_MS = 3_600_000

def supply_text(x):
    return "not reported by CoinMarketCap (no circulating supply)" if x is None else metric.pct_label(x) if x >= 0.01 else f"{x * 100:.2f}%"


LIMITS = ("Method: 'sellable' and 'days to sell' are this site's calculation from CoinMarketCap data, "
          "not CoinMarketCap metrics. Limits: reserves are assets only, not solvency (liabilities are not published). "
          "'Sellable' is a best case: it assumes the exchange could sell into all of the world's "
          "24h trading of each token. CoinMarketCap lists only wallets over $500k, balances have no "
          "timestamp, and CMC does not verify them. This is data, not financial advice.")

TOKEN_NOTE = ("Token names are as listed by CoinMarketCap; this data does not describe what a token is, "
              "who issues it or what backs it.")

INSTRUCTIONS = (
    "Sellable Reserves measures how much of a crypto exchange's published proof-of-reserves could "
    "actually be sold within 1, 7 or 30 days, using live CoinMarketCap data (holdings from "
    "/v1/exchange/assets, 24h volume and supply from /v3/cryptocurrency/quotes/latest). "
    "Use get_exchange_reserves for one exchange, list_exchanges to screen, compare_exchanges for "
    "side-by-side figures, and token_exposure to see which exchanges hold a token. "
    "Report the numbers and the stated limits; do not present them as a recommendation to deposit, "
    "withdraw, buy or sell. Do not describe what a token is beyond its CoinMarketCap name. " + LIMITS)

READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
HORIZON = {"type": "integer", "enum": [1, 7, 30], "default": 7,
           "description": "Days the exchange would have to sell: 1, 7 or 30."}

TOOLS = [
    {
        "name": "get_exchange_reserves",
        "title": "Exchange reserves, liquidity-adjusted",
        "description": ("One exchange's published reserves and how much could be sold within 1, 7 and 30 days, "
                        "the exact time until 50% and 90% become sellable, the share in tokens with no trading, "
                        "top holdings with days-to-sell and share of supply, CoinMarketCap notices, wallets also "
                        "listed by other exchanges, and receipt URLs to the raw CMC responses."),
        "inputSchema": {"type": "object", "properties": {
            "exchange": {"type": "string", "description": "Exchange name or CoinMarketCap slug, e.g. 'Binance' or 'lbank'."},
        }, "required": ["exchange"], "additionalProperties": False},
        "annotations": READ_ONLY,
    },
    {
        "name": "list_exchanges",
        "title": "Screen exchanges by sellable share",
        "description": ("Exchanges from CoinMarketCap's top 100 by volume that publish reserves, with reported "
                        "total, share sellable within the horizon, share with no market, weekly visits and notices."),
        "inputSchema": {"type": "object", "properties": {
            "horizon_days": HORIZON,
            "sort": {"type": "string", "enum": ["sellable", "size", "visits", "name"], "default": "sellable",
                     "description": "sellable = lowest sellable share first; size = largest reported first."},
            "filter": {"type": "string", "enum": ["all", "no_market", "under_half", "notice"], "default": "all"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
        }, "additionalProperties": False},
        "annotations": READ_ONLY,
    },
    {
        "name": "compare_exchanges",
        "title": "Compare exchanges side by side",
        "description": "Reported reserves, sellable share and amount, no-market share and time to half sellable for 2 to 10 exchanges.",
        "inputSchema": {"type": "object", "properties": {
            "exchanges": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 10,
                          "description": "Exchange names or slugs."},
            "horizon_days": HORIZON,
        }, "required": ["exchanges"], "additionalProperties": False},
        "annotations": READ_ONLY,
    },
    {
        "name": "token_exposure",
        "title": "Which exchanges hold a token",
        "description": ("For a token symbol, every exchange whose published reserves hold it: balance, value, share "
                        "of that exchange's reserves, days to sell at the token's global 24h volume, and share of "
                        "circulating supply."),
        "inputSchema": {"type": "object", "properties": {
            "symbol": {"type": "string", "description": "Token symbol, e.g. 'BNB' or 'USDZ'."},
        }, "required": ["symbol"], "additionalProperties": False},
        "annotations": READ_ONLY,
    },
]
TOOL_NAMES = {t["name"] for t in TOOLS}


class ToolError(Exception):
    """Reported to the model as a tool execution error (isError: true)."""


class _RateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._q = defaultdict(deque)

    def allow(self, ip):
        now = time.monotonic()
        with self._lock:
            q = self._q[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= PER_IP_PER_MIN:
                return False
            q.append(now)
            return True


def _decode_header(v):
    m = re.fullmatch(r"=\?base64\?(.*)\?=", v or "")
    return base64.b64decode(m.group(1)).decode() if m else v


def _rpc_error(id_, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    out = {"jsonrpc": "2.0", "error": err}
    if id_ is not None:
        out["id"] = id_
    return out


class McpServer:
    def __init__(self, get_view):
        self._view = get_view
        self._limiter = _RateLimiter()

    # ---- HTTP -----------------------------------------------------------

    def handle(self, http_method, headers, body, ip, origin_base, allowed_origins):
        """Return (status, content_type_or_None, payload_dict_or_None). `headers` keys are lowercase."""
        origin = headers.get("origin")
        if origin and origin.rstrip("/") not in allowed_origins:
            return 403, "application/json", _rpc_error(None, -32600, "Origin not allowed")
        if http_method != "POST":
            return 405, None, None
        if not self._limiter.allow(ip):
            # App-defined code, outside the JSON-RPC reserved range as the spec asks.
            return 429, "application/json", _rpc_error(None, -31029, "Rate limit: 60 requests per minute")
        try:
            msg = json.loads(body or b"")
        except ValueError:
            return 400, "application/json", _rpc_error(None, -32700, "Parse error")
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
            return 400, "application/json", _rpc_error(None, -32600, "Invalid Request: one JSON-RPC 2.0 message per POST")
        is_request = "id" in msg
        if is_request and msg["id"] is None:
            return 400, "application/json", _rpc_error(None, -32600, "Invalid Request: id must not be null")
        if not is_request:
            return 202, None, None  # notifications (e.g. legacy notifications/initialized) need no reply

        method, params, id_ = msg["method"], msg.get("params") or {}, msg["id"]
        meta = params.get("_meta") or {} if isinstance(params, dict) else {}
        modern_version = meta.get("io.modelcontextprotocol/protocolVersion")
        if method != "initialize" and modern_version is not None:
            return self._modern(id_, method, params, meta, headers, origin_base)
        return self._legacy(id_, method, params, headers, origin_base)

    def _modern(self, id_, method, params, meta, headers, origin_base):
        version = meta.get("io.modelcontextprotocol/protocolVersion")
        hv = headers.get("mcp-protocol-version")
        if hv is None or headers.get("mcp-method") is None:
            return 400, "application/json", _rpc_error(id_, -32020, "Header mismatch: MCP-Protocol-Version and Mcp-Method headers are required")
        if hv != version:
            return 400, "application/json", _rpc_error(id_, -32020, f"Header mismatch: MCP-Protocol-Version '{hv}' does not match body '{version}'")
        if headers["mcp-method"] != method:
            return 400, "application/json", _rpc_error(id_, -32020, f"Header mismatch: Mcp-Method '{headers['mcp-method']}' does not match body '{method}'")
        if version != MODERN:
            return 400, "application/json", _rpc_error(id_, -32022, "Unsupported protocol version",
                                                       {"supported": list(SUPPORTED), "requested": version})
        if "io.modelcontextprotocol/clientCapabilities" not in meta:
            return 400, "application/json", _rpc_error(id_, -32602, "Invalid params: _meta io.modelcontextprotocol/clientCapabilities is required")
        if method == "tools/call":
            name_h = headers.get("mcp-name")
            if name_h is None:
                return 400, "application/json", _rpc_error(id_, -32020, "Header mismatch: Mcp-Name header is required for tools/call")
            if _decode_header(name_h) != params.get("name"):
                return 400, "application/json", _rpc_error(id_, -32020, f"Header mismatch: Mcp-Name '{name_h}' does not match body '{params.get('name')}'")
        result = self._dispatch(method, params, origin_base, modern=True)
        if result is None:
            return 404, "application/json", _rpc_error(id_, -32601, f"Method not found: {method}")
        if "error" in result:
            return 200, "application/json", _rpc_error(id_, *result["error"])
        result = {"resultType": "complete", **result,
                  "_meta": {**result.get("_meta", {}), "io.modelcontextprotocol/serverInfo": SERVER_INFO}}
        return 200, "application/json", {"jsonrpc": "2.0", "id": id_, "result": result}

    def _legacy(self, id_, method, params, headers, origin_base):
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = requested if requested in LEGACY else LEGACY[0]
            return 200, "application/json", {"jsonrpc": "2.0", "id": id_, "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            }}
        hv = headers.get("mcp-protocol-version", "2025-03-26")
        if hv not in LEGACY:
            return 400, "application/json", _rpc_error(id_, -32022, "Unsupported protocol version",
                                                       {"supported": list(SUPPORTED), "requested": hv})
        result = self._dispatch(method, params, origin_base, modern=False)
        if result is None:
            return 200, "application/json", _rpc_error(id_, -32601, f"Method not found: {method}")
        if "error" in result:
            return 200, "application/json", _rpc_error(id_, *result["error"])
        return 200, "application/json", {"jsonrpc": "2.0", "id": id_, "result": result}

    # ---- methods --------------------------------------------------------

    def _dispatch(self, method, params, origin_base, modern):
        if method == "tools/call":
            logging.getLogger("mcp").info("tools/call %s (%s)", params.get("name"), "modern" if modern else "legacy")
        if method == "ping":
            return {}
        # 2026-07-28 caching: discover and tools/list MUST carry ttlMs and cacheScope.
        # Both are static and identical for every caller.
        cache = {"ttlMs": CACHE_TTL_MS, "cacheScope": "public"} if modern else {}
        if method == "server/discover" and modern:
            return {"supportedVersions": list(SUPPORTED), "capabilities": {"tools": {"listChanged": False}},
                    "instructions": INSTRUCTIONS, **cache}
        if method == "tools/list":
            return {"tools": TOOLS, **cache}
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            if name not in TOOL_NAMES:
                return {"error": (-32602, f"Unknown tool: {name}")}
            if not isinstance(args, dict):
                return {"error": (-32602, "Invalid params: arguments must be an object")}
            try:
                text, data = getattr(self, "_t_" + name)(args, origin_base)
            except ToolError as e:
                return {"content": [{"type": "text", "text": str(e)}], "isError": True}
            return {"content": [{"type": "text", "text": text}], "structuredContent": data, "isError": False}
        return None

    # ---- tools ----------------------------------------------------------

    def _ready_view(self):
        view = self._view()
        if not view.get("coverage", {}).get("with_data"):
            raise ToolError("Live data is still loading (the server refreshes from CoinMarketCap on start). Retry in about 30 seconds.")
        return view

    def _find(self, view, query):
        q = (query or "").strip().lower()
        if not q:
            raise ToolError("Give an exchange name or slug.")
        for e in view["exchanges"]:
            if q in (e["slug"].lower(), e["name"].lower()):
                return view["by_slug"][e["slug"]]
        names = {e["name"].lower(): e for e in view["exchanges"]}
        close = difflib.get_close_matches(q, list(names), n=3, cutoff=0.6)
        if len(close) == 1:
            return view["by_slug"][names[close[0]]["slug"]]
        hint = f" Did you mean: {', '.join(names[c]['name'] for c in close)}?" if close else ""
        raise ToolError(f"No exchange '{query}' in CoinMarketCap's top {view['coverage']['listed']} by volume.{hint}")

    @staticmethod
    def _horizon(args):
        h = args.get("horizon_days", 7)
        if h not in metric.HORIZONS:
            raise ToolError("horizon_days must be 1, 7 or 30.")
        return h

    @staticmethod
    def _as_of(view):
        return {"prices_fetched_at": view.get("quotes_fetched_at"), "reserves_fetched_at": view.get("exchanges_fetched_at")}

    @staticmethod
    def _days(d):
        return None if d is None else round(d, 2)

    def _t_get_exchange_reserves(self, args, base):
        view = self._ready_view()
        ex = self._find(view, args.get("exchange"))
        page = f"{base}/#/exchange/{ex['slug']}"
        if not ex.get("has_data"):
            data = {"exchange": ex["name"], "slug": ex["slug"], "publishes_reserves": False,
                    "weekly_visits": ex.get("weekly_visits"), "notice": ex.get("notice"), "page_url": page, **self._as_of(view)}
            return f"{ex['sentence']} Page: {page}", data
        holdings = [{
            "symbol": h["symbol"], "name": h["name"], "crypto_id": h["token_id"], "balance": h["balance"],
            "value_usd": round(h["usd"], 2), "share_of_reserves": round(h["share"], 6), "volume_24h_usd": round(h["volume_24h"], 2),
            "days_to_sell": self._days(h["days_to_sell"]), "share_of_circulating_supply": h["supply_share"],
        } for h in ex["holdings"][:10]]
        shared = sorted({n for v in ex["shared_wallets"].values() for n in v})
        receipts = {k: [f"{base}/api/receipt?path={p}" for p in v] for k, v in ex["receipts"].items()}
        data = {
            "exchange": ex["name"], "slug": ex["slug"], "publishes_reserves": True,
            "reported_usd": round(ex["reported_usd"], 2),
            "sellable": {str(n): {"share": round(ex["sellable_share"][n], 6), "usd": round(ex["sellable_usd"][n], 2)} for n in metric.HORIZONS},
            "no_market": {"share": round(ex["no_market_share"], 6), "usd": round(ex["no_market_usd"], 2)},
            "days_until_sellable": {"50_percent": self._days(ex["days_to_share"]["50"]), "90_percent": self._days(ex["days_to_share"]["90"])},
            "token_count": len(ex["holdings"]), "top_holdings": holdings,
            "unpriced_tokens": [u["symbol"] for u in ex["unpriced"]],
            "weekly_visits": ex.get("weekly_visits"), "notice": ex.get("notice"),
            "wallets_also_listed_by": shared, "duplicate_rows_collapsed": ex["rows_collapsed"],
            "page_url": page, "receipts": receipts, "limits": LIMITS, **self._as_of(view),
        }
        half = ex["days_to_share"]["50"]
        lines = [
            ex["sentences"][7],
            f"Sellable within 1 / 7 / 30 days: {metric.pct_label(ex['sellable_share'][1])} / "
            f"{metric.pct_label(ex['sellable_share'][7])} / {metric.pct_label(ex['sellable_share'][30])}.",
            f"Half sellable in: {'never (tokens with no trading block it)' if half is None else metric.days_label(half)}. "
            f"No market: {metric.pct_label(ex['no_market_share'])} ({metric.money_label(ex['no_market_usd'])}).",
            "Top holdings (symbol, CoinMarketCap name): " + "; ".join(
                f"{h['symbol']} ({h['name']}) {metric.pct_label(h['share'])} ({metric.money_label(h['usd'])}, "
                f"{metric.days_label(h['days_to_sell'])} to sell, share of circulating supply {supply_text(h['supply_share'])})"
                for h in ex["holdings"][:5]) + ".",
            TOKEN_NOTE,
        ]
        if ex.get("notice"):
            notice = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", ex["notice"])  # drop markdown link targets
            lines.append(f"CoinMarketCap notice: {notice}")
        if shared:
            lines.append(f"Some wallets are also listed by: {', '.join(shared)}.")
        lines += [f"Page: {page}", LIMITS]
        return "\n".join(lines), data

    def _t_list_exchanges(self, args, base):
        view = self._ready_view()
        h = self._horizon(args)
        rows = [e for e in view["exchanges"] if e.get("has_data")]
        flt = args.get("filter", "all")
        if flt == "no_market":
            rows = [e for e in rows if e["no_market_share"] > 0]
        elif flt == "under_half":
            rows = [e for e in rows if e["sellable_share"][h] < 0.5]
        elif flt == "notice":
            rows = [e for e in rows if e.get("notice")]
        elif flt != "all":
            raise ToolError("filter must be all, no_market, under_half or notice.")
        key = {"sellable": lambda e: (e["sellable_share"][h], -e["reported_usd"]),
               "size": lambda e: -e["reported_usd"], "visits": lambda e: -(e.get("weekly_visits") or -1),
               "name": lambda e: e["name"].lower()}.get(args.get("sort", "sellable"))
        if key is None:
            raise ToolError("sort must be sellable, size, visits or name.")
        limit = args.get("limit", 20)
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ToolError("limit must be an integer from 1 to 100.")
        rows = sorted(rows, key=key)[:limit]
        out = [{"exchange": e["name"], "slug": e["slug"], "reported_usd": round(e["reported_usd"], 2),
                "sellable_share": round(e["sellable_share"][h], 6), "no_market_share": round(e["no_market_share"], 6),
                "days_until_half_sellable": self._days(e.get("days_to_half")), "weekly_visits": e.get("weekly_visits"),
                "has_notice": bool(e.get("notice"))} for e in rows]
        text = (f"{len(out)} exchanges (horizon {h} day{'s' if h > 1 else ''}, filter {flt}):\n" +
                "\n".join(f"- {e['name']}: {metric.money_label(e['reported_usd'])} reported, "
                          f"{metric.pct_label(e['sellable_share'][h])} sellable, {metric.pct_label(e['no_market_share'])} no market"
                          + (" [notice]" if e.get("notice") else "") for e in rows) + f"\n{LIMITS}")
        return text, {"horizon_days": h, "filter": flt, "exchanges": out,
                      "coverage": view["coverage"], "limits": LIMITS, **self._as_of(view)}

    def _t_compare_exchanges(self, args, base):
        view = self._ready_view()
        h = self._horizon(args)
        names = args.get("exchanges")
        if not isinstance(names, list) or not 2 <= len(names) <= 10:
            raise ToolError("exchanges must list 2 to 10 names or slugs.")
        found = [self._find(view, n) for n in names]
        out, lines = [], []
        for ex in found:
            if not ex.get("has_data"):
                out.append({"exchange": ex["name"], "publishes_reserves": False})
                lines.append(f"- {ex['name']}: publishes no reserves")
                continue
            out.append({"exchange": ex["name"], "slug": ex["slug"], "reported_usd": round(ex["reported_usd"], 2),
                        "sellable_share": round(ex["sellable_share"][h], 6), "sellable_usd": round(ex["sellable_usd"][h], 2),
                        "no_market_share": round(ex["no_market_share"], 6),
                        "days_until_half_sellable": self._days(ex["days_to_share"]["50"]), "notice": ex.get("notice")})
            half = ex["days_to_share"]["50"]
            lines.append(f"- {ex['name']}: {metric.money_label(ex['reported_usd'])} reported, "
                         f"{metric.pct_label(ex['sellable_share'][h])} ({metric.money_label(ex['sellable_usd'][h])}) sellable, "
                         f"{metric.pct_label(ex['no_market_share'])} no market, half sellable in "
                         f"{'never' if half is None else metric.days_label(half)}")
        text = f"Within {h} day{'s' if h > 1 else ''}:\n" + "\n".join(lines) + f"\n{LIMITS}"
        return text, {"horizon_days": h, "exchanges": out, "limits": LIMITS, **self._as_of(view)}

    def _t_token_exposure(self, args, base):
        view = self._ready_view()
        sym = (args.get("symbol") or "").strip().upper()
        if not sym or len(sym) > 20:
            raise ToolError("Give a token symbol, e.g. 'BNB'.")
        out = []
        for ex in view["by_slug"].values():
            if not ex.get("has_data"):
                continue
            for hd in ex["holdings"]:
                if hd["symbol"].upper() == sym:
                    out.append({"exchange": ex["name"], "slug": ex["slug"], "token": hd["name"], "crypto_id": hd["token_id"],
                                "balance": hd["balance"], "value_usd": round(hd["usd"], 2),
                                "share_of_exchange_reserves": round(hd["share"], 6), "volume_24h_usd": round(hd["volume_24h"], 2),
                                "days_to_sell": self._days(hd["days_to_sell"]),
                                "share_of_circulating_supply": hd["supply_share"]})
        if not out:
            raise ToolError(f"No exchange's published reserves hold a token with symbol '{sym}'.")
        out.sort(key=lambda r: -r["value_usd"])
        ids = {r["crypto_id"] for r in out}
        note = (f" Note: {len(ids)} different tokens share the symbol {sym}; check crypto_id." if len(ids) > 1 else "")
        total = sum(r["value_usd"] for r in out)
        text = (f"{sym} ({out[0]['token']} on CoinMarketCap) is held by {len(out)} exchange{'s' if len(out) > 1 else ''}, {metric.money_label(total)} in total.{note}\n" +
                "\n".join(f"- {r['exchange']}: {metric.money_label(r['value_usd'])} "
                          f"({metric.pct_label(r['share_of_exchange_reserves'])} of its reserves), "
                          f"{metric.days_label(r['days_to_sell'])} to sell, 24h volume {metric.money_label(r['volume_24h_usd'])}, "
                          f"share of circulating supply {supply_text(r['share_of_circulating_supply'])}" for r in out[:15]) + f"\n{TOKEN_NOTE}\n{LIMITS}")
        return text, {"symbol": sym, "total_value_usd": round(total, 2), "holders": out, "limits": LIMITS, **self._as_of(view)}
