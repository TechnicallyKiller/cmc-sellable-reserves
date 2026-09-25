"""Live state: refreshes CMC data on fixed intervals (DECISIONS D5) and builds
the view the API serves. Visitors only ever read the last built view.
"""
import json
import logging
import threading
import time

from . import cmc, metric
from .store import Store, now_ts

log = logging.getLogger("sellable")

QUOTES_EVERY_S = 60
EXCHANGES_EVERY_S = 600


class Live:
    def __init__(self, store: Store, client=None, history=None):
        self.store = store
        self.client = client
        self.history = history
        self._lock = threading.Lock()
        self.exchanges = []        # [{id, name, slug}] from exchange/map, volume order
        self.assets = {}           # id -> cleaned rows
        self.collapsed = {}        # id -> rows collapsed by D8 rule 2
        self.info = {}             # id -> info record
        self.receipts = {}         # "map", "info", "assets:<id>", "quotes" -> [paths]
        self.quotes = {}
        self.errors = {}           # id -> last error message for that exchange
        self.exchanges_at = None
        self.quotes_at = None
        self.view = {"exchanges": [], "by_slug": {}}

    # ---- fetching -------------------------------------------------------

    def refresh_exchanges(self):
        ts = now_ts()
        body, raw = self.client.exchange_map()
        receipts = {"map": [self.store.write("exchanges", ts, "map", raw)]}
        exchanges = [{"id": e["id"], "name": e["name"], "slug": e["slug"]} for e in body["data"]]

        assets, collapsed, errors = {}, {}, {}
        for e in exchanges:
            try:
                body, raw = self.client.exchange_assets(e["id"])
            except (cmc.CMCError, OSError, ValueError) as err:
                errors[e["id"]] = str(err)
                if e["id"] in self.assets:  # keep last good data, flagged via errors
                    assets[e["id"]] = self.assets[e["id"]]
                    collapsed[e["id"]] = self.collapsed.get(e["id"], 0)
                    receipts[f"assets:{e['id']}"] = self.receipts.get(f"assets:{e['id']}", [])
                continue
            receipts[f"assets:{e['id']}"] = [self.store.write("exchanges", ts, f"assets_{e['id']}", raw)]
            if body["data"]:
                assets[e["id"]], collapsed[e["id"]] = metric.clean_rows(body["data"])

        info = {}
        if assets:
            body, raw = self.client.exchange_info(sorted(assets))
            receipts["info"] = [self.store.write("exchanges", ts, "info", raw)]
            info = {int(k): v for k, v in body["data"].items()}

        with self._lock:
            self.exchanges, self.assets, self.collapsed = exchanges, assets, collapsed
            self.info, self.errors = info, errors
            self.receipts.update(receipts)
            self.exchanges_at = ts
        log.info("exchanges refreshed: %d listed, %d with assets, %d errors, credits so far %d",
                 len(exchanges), len(assets), len(errors), self.client.credits_used)

    def refresh_quotes(self):
        ids = {r["currency"]["crypto_id"] for rows in self.assets.values() for r in rows}
        if not ids:
            return
        ts = now_ts()
        bodies, paths = [], []
        for i, (body, raw) in enumerate(self.client.quotes(ids)):
            bodies.append(body)
            paths.append(self.store.write("quotes", ts, f"quotes_{i}", raw))
        quotes = cmc.parse_quotes(bodies)
        with self._lock:
            self.quotes = quotes
            self.receipts["quotes"] = paths
            self.quotes_at = ts
        self.store.prune_quotes()
        log.info("quotes refreshed: %d tokens, credits so far %d", len(quotes), self.client.credits_used)

    # ---- replay (no key) ------------------------------------------------

    def load_latest_from_store(self):
        """Rebuild state from the newest stored responses, without calling CMC."""
        ex_runs, q_runs = self.store.runs("exchanges"), self.store.runs("quotes")
        if not ex_runs or not q_runs:
            raise FileNotFoundError(f"no stored runs under {self.store.root}")
        self.load_from_store(ex_runs[-1], q_runs[-1])

    def load_from_store(self, ts, qts):
        """Rebuild state from one stored exchanges run and one stored quotes run."""
        self.assets, self.collapsed, self.errors = {}, {}, {}
        m = self.store.read(f"exchanges/{ts}/map.json")
        self.exchanges = [{"id": e["id"], "name": e["name"], "slug": e["slug"]} for e in m["data"]]
        self.receipts = {"map": [f"exchanges/{ts}/map.json"]}
        for e in self.exchanges:
            path = f"exchanges/{ts}/assets_{e['id']}.json"
            try:
                body = self.store.read(path)
            except FileNotFoundError:
                self.errors[e["id"]] = "response not stored"
                continue
            self.receipts[f"assets:{e['id']}"] = [path]
            if body["data"]:
                self.assets[e["id"]], self.collapsed[e["id"]] = metric.clean_rows(body["data"])
        try:
            self.info = {int(k): v for k, v in self.store.read(f"exchanges/{ts}/info.json")["data"].items()}
            self.receipts["info"] = [f"exchanges/{ts}/info.json"]
        except FileNotFoundError:
            self.info = {}
        paths, bodies, i = [], [], 0
        while True:
            p = f"quotes/{qts}/quotes_{i}.json"
            try:
                bodies.append(self.store.read(p))
            except FileNotFoundError:
                break
            paths.append(p)
            i += 1
        self.quotes = cmc.parse_quotes(bodies)
        self.receipts["quotes"] = paths
        self.exchanges_at, self.quotes_at = ts, qts

    # ---- view -----------------------------------------------------------

    def build_view(self):
        with self._lock:
            exchanges, assets, info = list(self.exchanges), dict(self.assets), dict(self.info)
            quotes, receipts = dict(self.quotes), dict(self.receipts)
            collapsed, errors = dict(self.collapsed), dict(self.errors)
            exchanges_at, quotes_at = self.exchanges_at, self.quotes_at

        shared = metric.shared_wallets(assets)
        names = {e["id"]: e["name"] for e in exchanges}
        summary, by_slug = [], {}
        for rank, e in enumerate(exchanges, 1):
            inf = info.get(e["id"], {})
            base = {
                "id": e["id"], "name": e["name"], "slug": e["slug"], "volume_rank": rank,
                "weekly_visits": inf.get("weekly_visits"),
                "notice": inf.get("notice") or None,
                "error": errors.get(e["id"]),
            }
            if e["id"] not in assets:
                row = {**base, "has_data": False}
                summary.append(row)
                by_slug[e["slug"]] = {**row, "sentence": metric.sentence(e["name"], {"reported_usd": 0})}
                continue
            res = metric.compute_exchange(assets[e["id"]], quotes)
            also_claimed = {}
            for h in res["holdings"]:
                for w in h["wallets"]:
                    owners = shared.get(metric.normalise_address(w["address"]))
                    if owners:
                        w["also_claimed_by"] = [names.get(o, str(o)) for o in owners if o != e["id"]]
                        also_claimed[w["address"]] = w["also_claimed_by"]
            row = {
                **base, "has_data": True,
                "reported_usd": res["reported_usd"],
                "sellable_share": res["sellable_share"],
                "no_market_share": res["no_market_share"],
                "top_symbol": res["holdings"][0]["symbol"] if res["holdings"] else None,
                "days_to_half": res["days_to_share"]["50"],
            }
            summary.append(row)
            by_slug[e["slug"]] = {
                **row,
                "sentences": {n: metric.sentence(e["name"], res, n) for n in metric.HORIZONS},
                "sellable_usd": res["sellable_usd"],
                "curve": res["curve"],
                "ceiling_share": res["ceiling_share"],
                "days_to_share": res["days_to_share"],
                "buckets": res["buckets"],
                "chains": res["chains"],
                "concentration": res["concentration"],
                "no_market_usd": res["no_market_usd"],
                "holdings": res["holdings"],
                "unpriced": res["unpriced"],
                "rows_collapsed": collapsed.get(e["id"], 0),
                "shared_wallets": also_claimed,
                "receipts": {
                    "assets": receipts.get(f"assets:{e['id']}", []),
                    "quotes": receipts.get("quotes", []),
                    "info": receipts.get("info", []),
                    "map": receipts.get("map", []),
                },
            }
        view = {
            "exchanges": summary,
            "by_slug": by_slug,
            "exchanges_fetched_at": exchanges_at,
            "quotes_fetched_at": quotes_at,
            "coverage": {"listed": len(exchanges), "with_data": len(assets)},
            "receipts": {"map": receipts.get("map", []), "quotes": receipts.get("quotes", [])},
        }
        with self._lock:
            self.view = view
        return view

    def status(self):
        return {
            "exchanges_fetched_at": self.exchanges_at,
            "quotes_fetched_at": self.quotes_at,
            "credits_used_since_start": self.client.credits_used if self.client else 0,
            "mode": "live" if self.client else "replay",
            "quotes_every_s": QUOTES_EVERY_S,
            "exchanges_every_s": EXCHANGES_EVERY_S,
        }

    # ---- loop -----------------------------------------------------------

    def run_forever(self, stop: threading.Event):
        next_ex = next_q = 0.0
        while not stop.is_set():
            now = time.monotonic()
            try:
                if now >= next_ex:
                    self.refresh_exchanges()
                    next_ex = now + EXCHANGES_EVERY_S
                    next_q = 0.0  # re-quote immediately against the new holdings
                if time.monotonic() >= next_q:
                    self.refresh_quotes()
                    next_q = time.monotonic() + QUOTES_EVERY_S
                view = self.build_view()
                if self.history:
                    self.history.record(view)
            except (cmc.CMCError, OSError, ValueError, KeyError) as err:
                log.error("refresh failed: %s", err)
            stop.wait(max(1.0, min(next_ex, next_q) - time.monotonic()))


def dumps(obj):
    return json.dumps(obj, separators=(",", ":")).encode()
