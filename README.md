# Sellable Reserves

Exchanges publish "proof of reserves" as one dollar total. That total adds
Bitcoin and tokens nobody trades as if they were the same. This project shows,
for each exchange, how much of its reported reserves could actually be sold
within 1, 7 or 30 days, given each token's global 24h trading volume.

Built for #BuildwithCMC. Track: **Data and Visualisation**.

Decisions, evidence and limits: [`docs/DECISIONS.md`](docs/DECISIONS.md).
Raw API responses captured while deciding: [`evidence/`](evidence/).

## What it shows

- **Exchange page:** one plain sentence, the share sellable within 1 / 7 / 30
  days, where the reported total sits (sellable, too large to sell in time,
  no market), every holding with days-to-sell and share of circulating supply,
  and the wallets behind it.
- **Liquidity curve:** share sellable against time, 1 day to a year, with the
  exact time until 50% and 90% become sellable (or "never" when tokens with no
  trading block it).
- **Compare:** all exchanges that publish reserves, sortable and filterable,
  plus a scatter of reported size against sellable share (bubble = weekly visits).
- **History** (optional, Supabase): hourly sellable share per exchange.
- **Receipts:** tap any number to see the CMC endpoint, values and the raw
  response it came from.
- **Ask panel:** questions answered from the live data, by an LLM when
  configured, otherwise by rule-based answers. Never gives buy/sell advice.
- **MCP server:** the same data as read-only tools for AI agents (below).
- **Flags:** CoinMarketCap notices (e.g. shutdowns), wallets listed by more
  than one exchange, and duplicate wallet rows counted once.

## For AI agents (MCP)

`/mcp` is a remote [Model Context Protocol](https://modelcontextprotocol.io)
server (Streamable HTTP), so agents that manage assets can check an
exchange's reserve liquidity before acting. Read-only, no login, and it reads
the server's cached data, so agent calls spend no CMC credits.

It is model-agnostic: any MCP client can use it, whichever LLM runs the agent.

| Client | Connect |
|---|---|
| Claude Code | `claude mcp add --transport http sellable-reserves https://<your-app>/mcp` |
| Gemini CLI | `gemini mcp add --transport http sellable-reserves https://<your-app>/mcp`, or `"mcpServers": {"sellable-reserves": {"httpUrl": "https://<your-app>/mcp"}}` in `settings.json` |
| Codex (CLI / IDE) | `codex mcp add sellable-reserves --url https://<your-app>/mcp`, or `[mcp_servers.sellable-reserves]` with `url = "https://<your-app>/mcp"` in `config.toml` |
| Any other MCP client | Streamable HTTP endpoint `https://<your-app>/mcp`, no auth |
| MCP Inspector | `npx @modelcontextprotocol/inspector --cli https://<your-app>/mcp --transport http --method tools/list` |

Browser-based MCP clients send an `Origin` header, which the server checks
against DNS rebinding; allow them with `MCP_ALLOWED_ORIGINS` (comma-separated).

| Tool | Returns |
|---|---|
| `get_exchange_reserves(exchange)` | reported total; sellable share and amount at 1/7/30 days; exact days until 50% / 90% sellable; no-market share; top holdings with days-to-sell and supply share; notices; shared wallets; receipt URLs |
| `list_exchanges(horizon_days, sort, filter, limit)` | screen all exchanges, e.g. `filter: "under_half"` |
| `compare_exchanges(exchanges[], horizon_days)` | side-by-side figures for 2–10 exchanges |
| `token_exposure(symbol)` | every exchange holding a token: value, share of its reserves, days to sell, share of supply |

Every result carries plain text plus `structuredContent`, and states the
limits (not solvency, best case, $500k wallet floor, no timestamps). Protocol:
modern 2026-07-28 (stateless, header validation) and legacy
2025-11-25 / 2025-06-18 / 2025-03-26 (`initialize`). Origin checked against
DNS rebinding; 60 requests per minute per client.

## Metric

For each token an exchange holds (rows aggregated by CMC `crypto_id`):

- `holding_usd = balance × price`
- `days_to_sell = holding_usd ÷ volume_24h`
- `sellable(N) = Σ min(holding_usd, N × volume_24h)`, over tokens with volume > 0
- Time until a share *f* is sellable: the exact solution of
  `sellable(d) = f × reported`. `sellable` is piecewise linear with a
  breakpoint at each holding's `days_to_sell`, so it is solved segment by
  segment (`sellable/metric.py: days_to_reach`, tested against brute force).
- Tokens with `volume_24h == 0` are reported separately as **no market**;
  tokens missing from quotes as **unpriced**. Neither is merged with zero.

This assumes the exchange could sell into all of the world's trading of a
token, so it is a best case. Reserves are assets only, not solvency.

## CoinMarketCap endpoints

| Endpoint | Used for | Refresh |
|---|---|---|
| `GET /v1/exchange/map?limit=100&sort=volume_24h` | exchange list | 10 min |
| `GET /v1/exchange/assets?id=<id>` | wallet holdings per exchange | 10 min |
| `GET /v1/exchange/info?id=<ids>` | weekly visits, notices | 10 min |
| `GET /v3/cryptocurrency/quotes/latest?id=<≤399 ids>` | price, 24h volume, circulating supply | 60 s |

Measured cost: 102 credits per exchange refresh, 4–5 per quote refresh (the
v3 endpoint accepts at most 400 ids per call). Visitors never trigger CMC
calls; they read the server's latest refresh.

## Run

Requires Python 3.10+; no dependencies.

```bash
CMC_KEY=... python3 server.py          # live
python3 server.py --replay             # no key: serve the newest stored responses from ./data
python3 -m unittest discover -s tests -t .
```

Then open http://localhost:8000.

Optional environment variables:

| Variable | Effect |
|---|---|
| `LLM_API_KEY` | Ask panel answers with an LLM grounded in the live data. Groq by default; any OpenAI-compatible endpoint via `LLM_BASE_URL`, models tried in order from `LLM_MODELS`. Without it, or when rate limited, answers are rule-based. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | Hourly history. Create the table once with [`docs/supabase_schema.sql`](docs/supabase_schema.sql). The service key stays on the server; the table has row-level security on and no public policies. `scripts/backfill_history.py` rebuilds past hours from the raw responses stored in `data/`. |

## Tests

- `python3 -m unittest discover -s tests -t .`: metric, cleaning, milestones,
  LLM fallbacks and rate limits, history rows. Runs on real captured CMC
  responses in `tests/fixtures/`.
- `tests/e2e/run.js`: browser checks of every flow, keyboard access, and an
  axe-core WCAG 2.2 AA audit of each screen in light and dark. Setup and usage
  are at the top of the file.
- `tests/e2e/mcp_agent.mjs`: the official MCP SDK client against `/mcp` in
  both protocol eras, then a real LLM agent (any OpenAI-compatible endpoint)
  answering a question with the tools.

## Accessibility

- Zero axe-core violations (WCAG 2.2 AA + best practice) on every screen,
  light and dark.
- Keyboard: skip link, every control reachable, dialogs return focus, charts
  explorable with the arrow keys.
- Every chart has a table view and a text summary for screen readers.
- Chart colours are validated for colour-blind separation; identity never
  relies on colour alone.
- All motion is disabled under `prefers-reduced-motion`.

## Deploy (Render)

`render.yaml` defines a free Python web service. Set `CMC_KEY` in the Render
dashboard (never in the repo), and optionally the variables above. Free
services sleep after 15 minutes without traffic, so an external cron pings
`/api/status` to keep it awake. The disk is ephemeral: after a restart the
first refresh (~35 s, ~107 credits) runs before data appears, and the page
shows a warm-up screen meanwhile.

## API

| Route | Returns |
|---|---|
| `GET /api/status` | refresh times, credits used, coverage |
| `GET /api/exchanges` | one row per exchange |
| `GET /api/exchange/<slug>` | full detail: holdings, curve, milestones, receipts |
| `GET /api/history/<slug>` | hourly history (when Supabase is configured) |
| `GET /api/receipt?path=...` | the raw CMC response behind a number |
| `POST /api/ask` | `{question, slug}` → LLM answer or `{fallback: true}` |
| `GET /e/<slug>` | share link with preview tags for that exchange |
| `POST /mcp` | MCP server for AI agents (see above) |

Raw responses are stored gzipped under `data/`. Quotes: every refresh for the
last hour, then one per hour.
