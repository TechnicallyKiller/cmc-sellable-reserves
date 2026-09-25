"""CoinMarketCap Pro API client. Standard library only.

Every call returns the parsed body plus the raw bytes, so callers can store
the exact response behind each number.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://pro-api.coinmarketcap.com"
QUOTES_MAX_IDS = 399  # v3 rejects >400 ids: "'id' parameter is currently restricted to 400"


class CMCError(Exception):
    pass


class Client:
    def __init__(self, key, timeout=30):
        if not key:
            raise CMCError("CMC_KEY is not set")
        self._key = key
        self._timeout = timeout
        self.credits_used = 0

    def get(self, path, **params):
        """Return (body, raw_bytes). Raises CMCError on a non-zero error_code."""
        url = f"{BASE}{path}?{urllib.parse.urlencode(params)}" if params else f"{BASE}{path}"
        req = urllib.request.Request(url, headers={
            "X-CMC_PRO_API_KEY": self._key,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raw = e.read()
        body = json.loads(raw)
        status = body.get("status", {})
        self.credits_used += int(status.get("credit_count") or 0)
        # v1/v2 return error_code as a number, v3 as a string.
        if str(status.get("error_code")) != "0":
            raise CMCError(f"{path}: {status.get('error_code')} {status.get('error_message')}")
        return body, raw

    def exchange_map(self, limit=100):
        return self.get("/v1/exchange/map", limit=limit, sort="volume_24h")

    def exchange_assets(self, exchange_id):
        return self.get("/v1/exchange/assets", id=exchange_id)

    def exchange_info(self, exchange_ids):
        return self.get("/v1/exchange/info", id=",".join(map(str, exchange_ids)))

    def quotes(self, crypto_ids):
        """Yield (body, raw) per batch of at most QUOTES_MAX_IDS ids."""
        ids = sorted(set(crypto_ids))
        for i in range(0, len(ids), QUOTES_MAX_IDS):
            chunk = ids[i:i + QUOTES_MAX_IDS]
            yield self.get("/v3/cryptocurrency/quotes/latest", id=",".join(map(str, chunk)))


def parse_quotes(bodies):
    """Flatten v3 quote bodies into {crypto_id: {...}}. USD quote id is 2781."""
    out = {}
    for body in bodies:
        for coin in body["data"]:
            usd = next((q for q in coin["quote"] if q["id"] == 2781), None)
            if usd is None:
                continue
            out[coin["id"]] = {
                "symbol": coin["symbol"],
                "name": coin["name"],
                "price": usd["price"],
                "volume_24h": usd["volume_24h"],
                "cex_volume_24h": usd.get("cex_volume_24h"),
                "dex_volume_24h": usd.get("dex_volume_24h"),
                "circulating_supply": coin["circulating_supply"],
                "last_updated": usd["last_updated"],
            }
    return out
