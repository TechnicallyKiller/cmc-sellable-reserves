# Sellable Reserves

Exchanges publish "proof of reserves" as one dollar total. That total adds
Bitcoin and tokens nobody trades as if they were the same. This project shows,
for each exchange, how much of its reported reserves could actually be sold
within 1, 7 or 30 days, given each token's global 24h trading volume.

Decisions, evidence and limits: [`docs/DECISIONS.md`](docs/DECISIONS.md). Raw API responses captured while deciding: [`evidence/`](evidence/).

## Metric

For each token an exchange holds (rows aggregated by CMC `crypto_id`):

- `holding_usd = balance × price`
- `days_to_sell = holding_usd ÷ volume_24h`
- `sellable_N = Σ min(holding_usd, N × volume_24h)`, over tokens with volume > 0
- Tokens with `volume_24h == 0` are reported separately as **no market**.
- Tokens missing from quotes are reported separately as **unpriced**.

This assumes the exchange could sell into all of the world's trading of a
token, so it is a best case. Reserves are assets only, not solvency.

## CoinMarketCap endpoints

| Endpoint | Used for | Refresh |
|---|---|---|
| `GET /v1/exchange/map?limit=100&sort=volume_24h` | exchange list | 10 min |
| `GET /v1/exchange/assets?id=<id>` | wallet holdings per exchange | 10 min |
| `GET /v1/exchange/info?id=<ids>` | weekly visits, notices | 10 min |
| `GET /v3/cryptocurrency/quotes/latest?id=<≤399 ids>` | price, 24h volume, circulating supply | 60 s |

Measured cost: 102 credits per exchange refresh, 4 per quote refresh.
Visitors never trigger CMC calls; they read the server's latest refresh.

## Run

Requires Python 3.10+; no dependencies.

```bash
CMC_KEY=... python3 server.py          # live
python3 server.py --replay             # no key: serve the newest stored responses from ./data
python3 -m unittest discover -s tests -t .
```

API: `/api/status`, `/api/exchanges`, `/api/exchange/<slug>`,
`/api/receipt?path=...` (the raw CMC response behind a number).

Raw responses are stored gzipped under `data/`. Quotes: every refresh for the
last hour, then one per hour.
