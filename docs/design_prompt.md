Design an interactive website called **Sellable Reserves**.

## What it is
Crypto exchanges publish "proof of reserves", a headline number like "$552M in reserves". People read that as "my money is safe". But the total adds Bitcoin and tokens nobody trades as if they were the same thing. This site answers one question per exchange:

> Of the reserves this exchange shows you, how much could actually be sold within a week?

The user is an ordinary person with money on an exchange, not a trader or analyst. They should understand the answer in 5 seconds without knowing any crypto jargon.

## Visual direction: soft neumorphism with a touch of maximalism
- **Neumorphic base:** one soft background colour. Cards, search bar, toggles and buttons look extruded from or pressed into the surface, with paired light/dark soft shadows. Pressed (inset) state for active controls.
- **Maximalist touch, used sparingly:**
  - Oversized display type for the one headline number per exchange (the 7-day sellable %), large enough to dominate the view.
  - One saturated accent colour for "no market" / illiquid holdings, so the problem part literally stands out against the soft surface.
  - Subtle grain or noise texture on the background.
  - Expressive, confident typography pairing: a characterful display face for numbers and headlines, a clean sans for body text.
- **Legibility over style:** neumorphism is often low-contrast. All text and meaningful UI must meet WCAG AA contrast. Don't rely on shadow alone to show state; pair it with colour, icon or label.
- Light and dark themes, both neumorphic.
- Responsive; must work well on a phone.

## Screens and interactions

### 1. Home
- A large neumorphic search field: "Which exchange do you use?", with autocomplete over exchange names.
- Below it, a small row of example chips: Binance, LBank, Blockfinex, BitMart.
- One line of context: "44 of the top 100 exchanges publish reserves. 56 publish nothing."

### 2. Exchange page (the core screen)
- **Plain sentence first**, e.g.:
  *"LBank shows $552M in reserves. About 3% of it could be sold within a week. 72% is in UMM, a token that trades far less than LBank holds."*
- **Headline number:** 7-day sellable %, oversized.
- **Horizon toggle:** 1 day / 7 days / 30 days (neumorphic segmented control; the number and visual animate on change).
- **Reserve bar/stack:** one horizontal bar of the reported total, split into:
  - sellable within the chosen horizon (calm colour),
  - too large to sell in that time (muted),
  - "no market", i.e. tokens with zero trading volume (the accent colour).
- **Holdings list:** each token as a soft card with its share of reserves, "days to sell" (holding ÷ that token's global daily trading volume), and share of the token's total supply the exchange holds. Tap to expand: wallet addresses, balance, volume, and a link to the raw data.
- **Notices:** if CMC shows a notice (e.g. BitMart: "announces the shutdown of its operations"), show it prominently at the top.
- **"How to read this"** expandable card, in plain words:
  - Reserves are not solvency: this shows what the exchange holds, not what it owes.
  - "Sellable" assumes the exchange could sell into all of the world's trading of a token, so it's a best case.
  - Only wallets over $500k are listed; balances have no timestamp; CMC doesn't verify them.

### 3. Compare / leaderboard
Exchanges ranked by 7-day sellable %, each row showing reported total vs sellable total. Sort and filter. Tapping a row opens the exchange page.

### 4. Ask panel (chat)
A collapsible neumorphic chat panel on every page: "Ask about this exchange."
- Suggested questions: "What is USDZ?", "What does 7-day sellable mean?", "Why is Binance not 100%?"
- Answers quote the exact numbers they use, with a small link to the source data.
- It never tells users to buy, sell or move money.

### 5. Receipts
Every number is tappable and shows where it came from: the CoinMarketCap endpoint, the snapshot date (2026-09-24), and the raw values.

## Real data for the mock (use these exact values; do not invent others)
Snapshot 2026-09-24. Source: CoinMarketCap API.

| Exchange | Reported | 1d | 7d | 30d | No market | Top holdings | Weekly visits |
|---|---|---|---|---|---|---|---|
| Binance | $172.5B | 63% | 83% | 93% | 0% | BTC 33%, USDT 19%, BNB 15% | 7,369,881 |
| OKX | $21.2B | 88% | 90% | 94% | 0% | BTC 43%, USDT 28%, OKB 10% | n/a |
| HTX | $3.44B | 34% | 51% | 60% | 1% | TRX 29%, BTCT 25%, BTC 17% | 416,322 |
| LBank | $552M | 3% | 3% | 5% | 0% | UMM 72%, ECHO 19%, PINS 5% | 2,815,676 |
| Blockfinex | $1.40B | 0% | 0% | 0% | 99% | USDZ 98% | 227,711 |
| BitMart | $4M | 17% | 17% | 17% | 82% | BMX 82%, ETH 17% | 37,848 |

BitMart notice: "BitMart Exchange announces the shutdown of its operations."
For OKX, show weekly visits as missing, not zero.

## Tone
Calm, clear, factual, never alarmist. Explain like a smart friend. No jargon without a one-line explanation. No financial advice.

## Deliverables
High-fidelity designs for Home, Exchange page (show LBank and Binance, one bad and one healthy), Compare, and the open Ask panel, in light and dark, desktop and mobile. Include the component set: search, chips, segmented toggle, reserve bar, holding card, notice banner, chat bubble, and receipt popover.
