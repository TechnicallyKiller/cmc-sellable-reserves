# Submission kit

Checklist for the DoraHacks submission (closes 30 Sep 2026, 23:59 UTC).

| Required | Where |
|---|---|
| Public repo | https://github.com/TechnicallyKiller/cmc-sellable-reserves |
| Working demo / deployed link | Render URL (to add after deploy) |
| Screen recording | script below |
| X post with #BuildwithCMC, linking the submission and the video | draft below |
| CMC endpoints, named | README → "CoinMarketCap endpoints" |
| Visible evidence of a real API call: code and response | `sellable/cmc.py` + `evidence/` + the in-app receipts (`/api/receipt`) |
| Note on what the API made possible / where it got in the way | `FEEDBACK.md` (written by the author; notes below) |
| Track | Data and Visualisation |

## Demo video script (~2 minutes)

Numbers below are from 2026-09-25; read them off the live site when recording.

1. **0:00 — The problem (home).** "Exchanges publish proof of reserves as one
   big number. It adds Bitcoin and tokens nobody trades as if they were the
   same. So: could the exchange actually sell it?"
2. **0:15 — Search LBank.** Type "lb", press Enter. Read the sentence: $558M
   reported, about 4% sellable within a week, 73% in UMM, which would take
   about 6 years of the whole world's UMM trading to sell.
3. **0:35 — Liquidity curve.** Scroll to "How fast could it sell?". Hover
   across: flat near 0% for a year. Point at the milestones: half sellable in
   about 3 years.
4. **0:50 — Receipts.** Tap "Reported". Show the endpoint, the values, then
   open the raw CMC response. "Every number links to the exact API response
   it came from."
5. **1:05 — Blockfinex and BitMart.** Blockfinex: $1.4B, 99% in USDZ, which had
   zero trading in 24 hours; the curve is capped under 1%. BitMart: the
   shutdown notice from CoinMarketCap, 82% in a token with no trading.
6. **1:25 — Compare.** The scatter: most exchanges sit near 100%; LBank and
   Blockfinex sit alone at the bottom. Filter "Under half sellable".
7. **1:40 — Ask + MCP.** "Why is Binance not 100%?" Show the AI answer,
   labelled, with its source link. Then show an agent calling the MCP tool
   `token_exposure("BNB")` via Claude Code or the MCP Inspector.
8. **1:50 — Close.** "Live CoinMarketCap data, refreshed every minute. Every
   number has a receipt. Reserves aren't solvency, and the page says so."

## X post draft

Replace the two links before posting.

> Exchanges say "$X in reserves". But how much of it could they actually sell?
>
> Sellable Reserves checks the top 100 exchanges live with the @CoinMarketCap API:
> LBank reports $558M, about 4% sellable within a week.
> Blockfinex reports $1.4B, 99% in a token with zero trading.
>
> Every number links to the raw API response.
>
> Demo: <video link>
> Submission: <DoraHacks link>
> #BuildwithCMC

## Notes for FEEDBACK.md

API behaviour observed while building, each with the response that shows it.

**What the API made possible**
- `/v1/exchange/assets` gives wallet-level holdings for 44 of the top 100
  exchanges in one call each (1 credit). Joined with v3 quotes (24h volume,
  circulating supply), that is enough to compute a liquidity-adjusted reserve
  figure that no existing tool publishes.
- `/v1/exchange/info` adds `weekly_visits` and `notice`, which is how the site
  surfaces BitMart's shutdown notice next to its reserves.
- v3 quotes: all ~800 held tokens in two calls (4–5 credits).
- The same computed data is exposed to AI agents as an MCP server, with no
  extra API calls per agent request.

**Where it got in the way**
1. Exchange assets rows have no per-balance or per-wallet timestamp, although
   the docs say balances "might be delayed". Staleness can't be measured.
   (`evidence/exchange/binance_2026-09-24.json`)
2. Docs say wallets ≥ $100k are shown; the smallest of 4,737 rows was
   $500,237, and CMC's own Reserves tab says ≥ $500k.
   (`evidence/exchange/assets_2026-09-24/`)
3. Exchanges without data return `[]` with `error_code` 0, so "not tracked" and
   "holds nothing" look the same.
4. The same EVM wallet appears twice with different letter case and an
   identical balance: 12 duplicate rows within 5 exchanges on 2026-09-24,
   $24.4M counted twice (Phemex $7.89M, Ourbit $5.84M, Gate $4.92M, Bitget
   $3.14M, Bybit $2.65M). Separately, one wallet is listed by two exchanges
   (BVOX and Deepcoin, ~$13M each). (`evidence/exchange/assets_2026-09-24/`)
5. `currency.price_usd` in exchange assets is a 30-decimal JSON number
   (`7.071437790639997000000000000000`).
6. v2 quotes is documented at 1 credit per 100 ids; 798 ids cost 4 credits,
   which matches v3's documented per-250 rate.
   (`evidence/quotes/batch_all_2026-09-24.json`)
7. v3 quotes caps `id` at 400 ("'id' parameter is currently restricted to
   400", 0 credits); not stated on the reference page.
8. v3 returns `status.error_code` as a string (`"0"`, `"400"`); v1/v2 return a
   number. v3 also changes shape: `data` is an array, `quote` is an array keyed
   by id 2781. (`evidence/quotes/v3_bnb_2026-09-25.json`)
9. The `centralized-exchange` tag misses OKB (OKX's token), so exchange tokens
   can't be identified from tags. (`evidence/quotes/v3_batch1_2026-09-25.json`)
10. Keyless `/public-api/v3/cryptocurrency/quotes/latest` works; keyless
    `/public-api/v1/exchange/assets` returns 1005 "An API Key is required".
    (`evidence/quotes/v3_keyless_publicapi_2026-09-25.txt`,
    `evidence/exchange/keyless_publicapi_assets_2026-09-25.txt`)
11. Tokens with `volume_24h: 0` and `circulating_supply: 0` still carry a USD
    price: USDZ is priced at $1.38B of Blockfinex's reserves with zero trading.
12. `/v1/key/info` reported 450,000 credits / 600 per minute for the hackathon
    key vs the published Startup 300,000 / 30.
    (`evidence/key_info_2026-09-24.json`)
