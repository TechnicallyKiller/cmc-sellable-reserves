# DECISIONS

Each entry: what was decided, alternatives, evidence, what would make it wrong.
Evidence paths are relative to [`../evidence/`](../evidence/) (raw CMC responses, unmodified).

---

## D0 — The user and the decision they make (decided 2026-09-25)

**User.** A person keeping money on a centralized exchange, especially a
mid-tier one, who sees "$X in reserves" and takes it as a safety signal.

**Decision they make.** Keep funds there, or move them (to another exchange or
self-custody). The product answers: *of the reserves this exchange shows you,
how much is in assets that could actually be sold, and how much is in tokens
nobody trades?*

**Evidence that these users exist at the exchanges the metric flags.**
From `/v1/exchange/info` (`exchange/info_sample_2026-09-25.json`, field
`weekly_visits`), joined to D2's metric:

| Exchange | weekly_visits | Reported reserves | 7-day sellable | Largest holding |
|---|---|---|---|---|
| LBank | 2,815,676 | $552M | 3% | UMM 72% |
| Blockfinex | 227,711 | $1,396M | 0% (99% no market) | USDZ 98%, zero 24h volume |
| DigiFinex | 8,557 | $4M | 11% | CTB 88% |
| BitMart | 37,848 | $4M | 17% (82% no market) | BMX 82%, zero 24h volume |
| Binance (reference) | 7,369,881 | $172,537M | 83% | BTC 33% |

- BitMart's `notice` field reads: *"BitMart Exchange announces the shutdown of
  its operations."* Its reserves were 82% in a token with zero 24h volume.
  This is one case, not proof that the metric predicts failures. It shows
  the situation the product describes happening to a listed exchange.
- The failure mode has happened before: FTX's balance sheet relied on its own
  token FTT (public record; not from this API).
- `weekly_visits` is CMC's figure. Its source and method are not documented in
  the response, so treat it as an indicator of traffic, not a user count.

**Would be wrong if.** Users of these exchanges don't look at reserves at all.
Not testable with API data; it is the main assumption behind the usefulness
score.

---

## D1 — Product: "Sellable Reserves" (decided 2026-09-25)

**What.** For each exchange that publishes holdings via CMC, show the reported
reserve total next to how much of it could be sold within N days, given each
held token's global 24h trading volume. Track: **Data and Visualisation**.

**Alternatives considered.**
- *Own-token share only* ("Y% is its own token"). Rejected as the core metric:
  already published by DefiLlama ("clean assets" = total minus self-issued
  token) and by CMC's monthly exchange report (platform-token share). Also
  needs a curated exchange→token mapping the API does not provide (see D4).
- *Pivot to RWA track.* Rejected: 8+ RWA entries cover the obvious angles
  (handoff §4); RWA endpoint data has known gaps (handoff §7).

**Evidence.**
- Coverage: 44 of the top 100 exchanges by volume return holdings; 56 return
  an empty array with status 0. `exchange/map_top100_volume_2026-09-24.json`,
  `exchange/assets_2026-09-24/`.
- The metric separates exchanges: 7-day sellable share ranges from 0%
  (Blockfinex, $1.40B reported, 99% in USDZ with zero 24h volume) and 3%
  (LBank, $552M) to 87–94% (OKX, Bybit, Bitget, KuCoin). Computed from the
  files above plus `quotes/batch_all_2026-09-24.json`.
- Novelty (subagent check, 2026-09-25): no tool or article found computing
  holdings ÷ token volume, sellable-within-N-days reserves, or supply share of
  exchange holdings. DefiLlama API (`api.llama.fi/cexs`) has no per-token
  liquidity field. In 1,204 DoraHacks BUIDL pages (IDs 47900–49128), only
  Divergence (48779) uses `/v1/exchange/assets`, as one input to a sentiment
  score. Not checked: DoraHacks BUIDL tab (WAF), entries after ~24 Sep,
  DefiLlama/CryptoQuant/Nansen/CryptoRank rendered UIs.

**Would be wrong if.** A hackathon entry or existing tool is found computing a
volume-adjusted reserve figure; or coverage collapses below a handful of
exchanges in later refreshes.

**Stated limits (shown on the site, not buried).**
- Reserves are not solvency: the endpoint shows assets, not liabilities.
- No per-balance timestamp exists in the response; staleness is unknowable.
- Observed minimum row is $500,237 (docs say $100k; CMC's Reserves tab says
  $500k). Holdings below that are invisible.
- CMC states it does not verify third-party holdings.

---

## D2 — Metric definition (decided 2026-09-25)

**What.**
- Aggregate each exchange's rows by `currency.crypto_id` (across wallets and
  platforms).
- `holding_usd = balance × quote price`, where price and `volume_24h` come from
  the same quotes response.
- `sellable_N = Σ min(holding_usd, N × volume_24h)` over tokens with
  `volume_24h > 0`.
- Tokens with `volume_24h == 0` form a separate **"no market"** bucket, shown
  as its own line. Never displayed as "0 days" or merged with sellable.
- Headline horizon **N = 7**. 1 and 30 shown as secondary.
- Supply share = `balance ÷ circulating_supply`. Where `circulating_supply == 0`
  (36 of 798 tokens), show "supply not reported". Never 0% or ∞.

**Why N = 7, not 1.** At N = 1 Binance shows 63% because its BTC holding exceeds
one day of global BTC volume. That penalises size, not asset quality. At N = 7
Binance is 83%, while the junk-token cases stay low (Blockfinex 0%, LBank 3%).

**Why quote price, not `exchange/assets` `currency.price_usd`.** Quotes carry
`last_updated`; the assets price has no timestamp. Using one response keeps price
and volume from the same instant. Observed difference is small (BNB: 777.34 in
assets vs 777.24 in quotes, 2026-09-24).

**Alternatives.**
- Days-to-sell per token only, no aggregate. Kept as the per-exchange detail
  view, not the headline.
- Participation cap (e.g. exchange can take 10% of daily volume). Not adopted:
  any specific rate is an invented parameter. The 100% assumption is stated as
  a **best case** (upper bound on sellable).

**Would be wrong if.** `volume_24h` is dominated by wash trading for the tokens
that matter, which would make "sellable" overstated. Mitigation to evaluate:
`cex_volume_24h` / `dex_volume_24h` are in the response; not yet analysed.

---

## D3 — Endpoints and credit budget (decided 2026-09-25)

| Endpoint | Use | Observed cost |
|---|---|---|
| `/v1/exchange/map?limit=100&sort=volume_24h` | exchange list | 1 |
| `/v1/exchange/assets?id=<id>` | holdings, ×100 | 1 each |
| `/v3/cryptocurrency/quotes/latest?id=<≤399 ids>` | price, volume, supply | 2 per 399 ids |
| `/v1/exchange/info?id=<comma list>` | weekly_visits, notice (e.g. shutdown), PoR status | 1 for 10 ids (larger batches unobserved) |

- ~106 credits per full refresh of all exchanges (info cost for 44 ids to be confirmed). Basic tier (15,000/month, per pricing page)
  is the post-1 Oct budget (see D5 for live-refresh cost). `/v1/exchange/assets` and v3
  quotes are listed on all plans including Basic.
- **v3, not v2.** v2 quotes is listed as deprecated. v3 differs in shape:
  `data` is an array; `quote` is an array (USD id 2781); `status.error_code`
  is a string. v3 caps `id` at 400 per request (error `"400"`, 0 credits).
  Evidence: `quotes/v3_bnb_2026-09-25.json`, `quotes/v3_batch{1,2}_2026-09-25.json`.

**Would be wrong if.** Basic tier returns a restriction error on either
endpoint after 1 Oct (docs say it won't; unobserved).

---

## D4 — No exchange→own-token mapping in v1 (decided 2026-09-25)

**What.** The metric uses no affiliation mapping. Concentration is flagged for
any token, own or not.

**Evidence.** The API has a `centralized-exchange` tag (19 of 798 tokens), but
it is incomplete: OKB (OKX, 10% of OKX reserves), USDZ, UMM, CTB carry no such
tag. `quotes/v3_batch{1,2}_2026-09-25.json`. The tag also does not say *which*
exchange issued the token.

**Alternative.** Curated mapping with sources. Deferred: adds a hand-maintained
input to the core number, and the largest problem holdings (USDZ, UMM, CTB) are
not identifiable as own tokens anyway.

**Would be wrong if.** Users can't interpret the result without the "this is
their own token" label. Then add a curated, sourced, visibly labelled mapping.

---

## D5 — Live data via server-side cache (decided by user 2026-09-25; replaces daily snapshots)

**What.**
- A small always-on server holds `CMC_KEY` (environment variable, never in the
  repo) and refreshes from CMC on fixed intervals:
  - quotes (price, volume, supply): every **60 s**, 4 credits per refresh;
  - exchange map + assets + info: every **10 min**, ~106 credits per refresh.
- Every visitor reads the latest cached result from the server. **Credit use
  is set by the refresh intervals, not by the number of visitors.**
- Each refresh writes its raw responses to disk with the fetch timestamp, so
  every number on the site links to the exact response it came from, and the
  history accumulates.
- Language: **Python 3, standard library only** (server, refresher, metric).
- The chatbot (D7) runs on the same server.
- Raw responses stored gzipped. Quotes are ~1.5 MB per refresh (~2.2 GB/day
  at 60 s), so quotes are kept for every refresh in the last hour, then one
  per hour. Exchange responses (~1.5 MB per refresh uncompressed) are all kept.

**Measured (first live run, 2026-09-25T02:21Z).** Exchange refresh: 102
credits (map 1 + assets 100 + info for 44 ids 1). Quote refresh: 4 credits.
Matches the arithmetic below.

**Why not a CMC call per page view.** ~106 credits per visit. Also exposes
the key to per-visitor abuse. Rejected.

**Why not daily snapshots (previous version of D5).** The user wants live.
Evidence that holdings barely move (below) is why assets refresh less often
than quotes.

**Evidence that reserves barely change between calls.** Binance assets fetched
2026-09-24T23:37Z and 2026-09-25T02:07Z (`exchange/binance_2026-09-24.json`,
`exchange/binance_2026-09-25.json`), rows keyed by wallet + platform + token:
1,543 rows in common, **1 balance changed**, all 1,543 `price_usd` changed;
2 rows disappeared, 4 appeared.

**Credit arithmetic (Startup, 449,884 left on 2026-09-25).**
- Quotes: 1,440 refreshes/day × 4 = 5,760/day.
- Assets/info: 144 refreshes/day × ~106 = ~15,300/day.
- ≈ 21,000/day ≈ 126,000 through 30 Sep. Fits.
- Rate: a 10-min refresh bursts ~102 requests; limit is 600/min.

**Deferred by user.** Behaviour after 1 Oct (Basic, 15,000/month) is out of
scope for now. At the rates above the credits would run out within the first
day on Basic. Must be revisited before 30 Sep.

**Still open.** Host (must be always-on; free-tier limits not yet verified).

**Would be wrong if.** Measured credit use per refresh differs from the
figures above. The server logs `status.credit_count` of every call to check this.

---

## D6 — The site must explain, not just display (decided 2026-09-25)

**What.** The user said a page of numbers that people don't understand is not
acceptable. Requirements:
- Every exchange view leads with one plain-language sentence, e.g.
  *"LBank shows $552M in reserves. About 3% of it is in assets that could be
  sold within a week. 72% is in UMM, a token that trades far less than LBank holds."*
  These sentences are generated **deterministically from the cached data**,
  not written by hand.
- Search by exchange name as the entry point, not a table.
- Every number links to its receipt: token, wallet address, balance, volume,
  and the raw response it came from, with fetch time.
- Limits from D1 are stated in plain words where the number is shown.

**Would be wrong if.** Test users still can't say, in their own words, what the
headline means after reading one exchange page.

---

## D7 — Chatbot: yes (decided by user 2026-09-25)

**What.** A chat assistant so users can ask "is my money on X ok?",
"what is USDZ?", "what does 7-day sellable mean?"

**Constraints (binding).**
- Needs an LLM API key server-side, so a serverless function (e.g. Cloudflare
  Workers / Vercel). Static hosting alone can't hold the key.
- Cost scales per question (LLM cost, not CMC credits). Needs a rate limit.
- Must answer **only from the cached CMC data** and cite the numbers it uses.
  Otherwise it produces unsourced claims, which violates operating rule 4.
- Must not give financial advice ("move your money"). It describes the data
  and its limits.

**Build order.** D6's deterministic sentences first (they work with no LLM
and no running cost), then the chatbot on the same cached data (D5). The chatbot
earns its place by answering follow-up questions the page can't anticipate.

**Alternative.** No chatbot, deterministic explanations only. Rejected by the
user: the site must be easy for people who don't know crypto terms.

**Would be wrong if.** Answers cite numbers not present in the cached data, or
cost per question can't be capped. Then disable it and keep D6.

**Still open.** LLM provider/model, host for the serverless function, and the
rate limit.

**Visual direction (user, 2026-09-25).** Interactive site, soft neumorphism
with a touch of maximalism. Design brief: `design_prompt.md`.

---

## D8 — Row cleaning before aggregation (decided 2026-09-25)

**Evidence** (`exchange/assets_2026-09-24/`, 4,737 rows):
- The same EVM wallet appears in different letter case (`0xF977…` / `0xf977…`)
  with the **identical** balance, platform and token. 1,140 distinct addresses
  become 1,124 when EVM addresses are lowercased.
- Within single exchanges: Ourbit 7 duplicate groups ($5.84M counted twice),
  Phemex 1 ($7.89M), Gate 1 ($4.92M), Bitget 1 ($3.14M), Bybit 2 ($2.65M).
- Binance also has 3 wallet + platform + token keys with two **different**
  balances (e.g. USDT on BNB chain: 37,924,349.00 and 400,000,047.54). These
  are not copies.
- One wallet, `0xb8001c3ec9aa1985f6c747e25c28324e4a361ec1`, is listed by both
  **BVOX and Deepcoin** (~$13M each).

**Rules.**
1. Lowercase addresses only when they match `^0x[0-9a-fA-F]{40}$` (EVM).
   Other address formats (e.g. Bitcoin base58, Solana) are case-sensitive and
   left untouched.
2. Collapse rows identical in (normalised address, platform id, token id,
   balance) to one row, within an exchange. Count and show how many were
   collapsed.
3. Rows with the same key but different balances are summed. Can't tell from
   the response whether they are separate holdings; summing matches how CMC
   presents them. Flagged in the receipts view.
4. A wallet listed by more than one exchange is flagged on each of those
   exchanges' pages ("this wallet is also claimed by …"). Not removed from
   either total: the API gives no basis to decide who owns it.

**Would be wrong if.** CMC documents that case-variant rows are distinct
holdings. Nothing observed suggests so.
