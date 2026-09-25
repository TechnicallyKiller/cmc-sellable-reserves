-- Sellable Reserves: hourly history. Run once in the Supabase SQL editor.
-- The server writes with the service-role key. RLS is on with no policies,
-- so the public anon key cannot read or write this table.

create table if not exists public.sellable_history (
  id            bigint generated always as identity primary key,
  fetched_at    timestamptz      not null,  -- when the quotes behind these numbers were fetched
  exchange_id   integer          not null,  -- CoinMarketCap exchange id
  slug          text             not null,
  name          text             not null,
  reported_usd  double precision not null,
  sellable_1d   double precision not null,  -- shares, 0..1
  sellable_7d   double precision not null,
  sellable_30d  double precision not null,
  no_market     double precision not null,
  unique (slug, fetched_at)
);

create index if not exists sellable_history_slug_time on public.sellable_history (slug, fetched_at);

alter table public.sellable_history enable row level security;
