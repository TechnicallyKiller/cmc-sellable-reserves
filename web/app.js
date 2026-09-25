'use strict';
/* Sellable Reserves frontend. Reads only this server's API (never CMC directly).
   Routes: #/  #/compare  #/exchange/<slug> */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);
const HZ = { 1: { short: '1 day', phrase: 'a day' }, 7: { short: '7 days', phrase: 'a week' }, 30: { short: '30 days', phrase: 'a month' } };
const POLL_MS = 20000;
const HOLDS_PAGE = 8;

const state = {
  list: null, details: {}, hz: 7, sort: 'pct', filter: 'all',
  holdsShown: HOLDS_PAGE, how: false, open: new Set(), lastSlug: null, rendered: false,
};

/* ---------------- formatting ---------------- */
const money = v => {
  if (v == null) return '–';
  if (v === 0) return '$0';
  if (v >= 1e9) return '$' + parseFloat((v / 1e9).toPrecision(3)) + 'B';
  if (v >= 1e6) return '$' + parseFloat((v / 1e6).toPrecision(3)) + 'M';
  if (v >= 1e3) return '$' + parseFloat((v / 1e3).toPrecision(3)) + 'K';
  return '$' + v.toFixed(2);
};
const usdFull = v => v == null ? 'null' : '$' + v.toLocaleString('en-US', { maximumFractionDigits: 2 });
const num = v => v == null ? 'null' : v.toLocaleString('en-US', { maximumFractionDigits: v < 1 ? 8 : 2 });
const pctInt = x => x == null ? 0 : Math.round(x * 100);
const pctLabel = x => {
  if (x == null) return '–';
  if (x === 0) return '0';
  if (x < 0.01) return '<1';
  if (x >= 0.995 && x < 1) return '99';
  return String(Math.round(x * 100));
};
const daysLabel = d => {
  if (d == null) return 'Never';
  if (d < 0.1) return 'Under 0.1 days';
  if (d < 2) return d.toFixed(1) + ' days';
  if (d < 730) return Math.round(d).toLocaleString('en-US') + ' days';
  return 'About ' + Math.round(d / 365).toLocaleString('en-US') + ' years';
};
const supplyLabel = x => {
  if (x == null) return 'Not reported';
  if (x < 0.0001) return 'Under 0.01%';
  if (x < 0.01) return (x * 100).toFixed(2) + '%';
  return (x * 100).toFixed(1) + '%';
};
const visitsLabel = v => v == null ? 'Not published' : v.toLocaleString('en-US');
const parseTs = ts => ts ? new Date(ts.replace(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/, '$1-$2-$3T$4:$5:$6Z')) : null;
const fmtTime = ts => { const d = parseTs(ts); return d ? d.toISOString().replace('T', ' ').slice(0, 19) + ' UTC' : '–'; };
const ago = d => {
  const s = Math.max(0, Math.round((Date.now() - d) / 1000));
  if (s < 60) return s + 's ago';
  if (s < 3600) return Math.round(s / 60) + ' min ago';
  return Math.round(s / 3600) + ' h ago';
};
const mdLinks = s => esc(s).replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
  (m, t, u) => `<a href="${u}" target="_blank" rel="noopener noreferrer">${t}</a>`);
const words = (text, start = 0) => text.split(' ').map((w, i) => `<span class="w" style="--i:${start + i}">${esc(w)}</span>`).join(' ');

/* ---------------- data ---------------- */
async function api(path) {
  const r = await fetch(path, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}
const ready = () => state.list && state.list.coverage && state.list.coverage.with_data > 0;
const withData = () => state.list.exchanges.filter(x => x.has_data);
async function loadList() { state.list = await api('/api/exchanges'); updateLive(); return state.list; }
async function loadDetail(slug) { const d = await api('/api/exchange/' + encodeURIComponent(slug)); state.details[slug] = d; return d; }
const shares = (d, hz) => {
  const s = d.sellable_share[hz] ?? 0, n = d.no_market_share ?? 0;
  return { s, n, b: Math.max(0, 1 - s - n) };
};

/* ---------------- routing & transitions ---------------- */
function route() {
  const h = location.hash.replace(/^#/, '');
  const m = h.match(/^\/exchange\/([^/?]+)/);
  if (m) return { screen: 'exchange', slug: decodeURIComponent(m[1]) };
  if (h.startsWith('/compare')) return { screen: 'compare' };
  return { screen: 'home' };
}

async function navigate() {
  const r = route();
  if (r.screen === 'exchange' && ready() && !state.details[r.slug]) {
    try { await loadDetail(r.slug); } catch (_) { /* rendered as not found */ }
  }
  const update = () => { renderView(r); };
  const first = !state.rendered;
  if (!first && document.startViewTransition && !reduceMotion.matches) {
    const t = document.startViewTransition(update);
    // A newer navigation can skip this transition; the DOM is still updated.
    t.ready.catch(() => {});
    t.finished.catch(() => {}).finally(() => { afterNav(r, first); });
  } else {
    update();
    afterNav(r, first);
  }
}

function afterNav(r, first) {
  $$('[style*="view-transition-name"]').forEach(el => { if (!el.classList.contains('ex-name')) el.style.viewTransitionName = ''; });
  if (!first) { $('#view h1')?.focus({ preventScroll: true }); }
  if (r.screen === 'exchange') state.lastSlug = r.slug;
}

function renderView(r) {
  const view = $('#view');
  $$('[data-nav]').forEach(a => a.setAttribute('aria-current', a.dataset.nav === r.screen ? 'page' : 'false'));
  if (!ready()) { view.innerHTML = warmHTML(); state.rendered = true; return; }
  if (r.screen === 'home') view.innerHTML = homeHTML();
  else if (r.screen === 'compare') view.innerHTML = compareHTML();
  else {
    const d = state.details[r.slug];
    if (r.slug !== state.lastSlug) { state.holdsShown = HOLDS_PAGE; state.open.clear(); state.how = false; }
    view.innerHTML = !d ? notFoundHTML(r.slug) : d.has_data ? exchangeHTML(d) : noDataHTML(d);
  }
  window.scrollTo(0, 0);
  bindView(r);
  updateAskContext();
  state.rendered = true;
}

/* ---------------- screens ---------------- */
function warmHTML() {
  return `<section class="warm stagger">
    <div class="spin" style="--i:0"><span></span></div>
    <h1 tabindex="-1" style="--i:1">Fetching live data from CoinMarketCap…</h1>
    <p style="--i:2">The server has just started. Loading reserves for the top 100 exchanges and prices for every token they hold takes about half a minute. This page will update on its own.</p>
  </section>`;
}

function homeHTML() {
  const c = state.list.coverage;
  const chips = ['binance', 'lbank', 'blockfinex', 'bitmart']
    .map(s => state.list.exchanges.find(x => x.slug === s && x.has_data)).filter(Boolean);
  const h1a = 'Of what your exchange shows you, how much could';
  const h1b = 'actually be sold';
  const n = h1a.split(' ').length;
  return `<section class="home">
    <p class="home-kicker pop">Proof of reserves, in plain words</p>
    <h1 class="home-h1" tabindex="-1">${words(h1a)} <em>${words(h1b, n)}</em> ${words('in a week?', n + 3)}</h1>
    <div class="search stagger">
      <label for="q" style="--i:6">Which exchange do you use?</label>
      <div class="search-wrap" style="--i:7">
        <div class="search-box">
          <span class="search-ico" aria-hidden="true"></span>
          <input id="q" role="combobox" aria-expanded="false" aria-controls="suggest" aria-autocomplete="list" autocomplete="off" placeholder="Type an exchange name">
          <button type="button" class="btn-calm" id="q-go">Show me</button>
        </div>
        <div class="suggest" id="suggest" role="listbox" aria-label="Exchanges" hidden></div>
      </div>
      <div class="chips" style="--i:8">
        <span>For example</span>
        ${chips.map(x => `<a class="pill" href="#/exchange/${esc(x.slug)}">${esc(x.name)}</a>`).join('')}
      </div>
    </div>
    <p class="home-foot pop" style="animation-delay:.5s">
      <button type="button" class="linkish" data-rc="count">${c.with_data} of the top ${c.listed}</button> exchanges publish reserves.
      <button type="button" class="linkish" data-rc="count">${c.listed - c.with_data}</button> publish nothing.
      <a class="go" href="#/compare">Compare all ${c.with_data} <span>→</span></a>
    </p>
  </section>`;
}

function exchangeHTML(d) {
  const hz = state.hz, sh = shares(d, hz);
  const sharedWith = [...new Set(Object.values(d.shared_wallets || {}).flat())];
  const notices = [];
  if (d.notice) notices.push(`<div class="notice" role="alert">
      <span class="notice-ico" aria-hidden="true">!</span>
      <div class="notice-body">
        <span class="notice-kicker">Notice on CoinMarketCap</span>
        <span class="notice-text">“${mdLinks(d.notice)}”</span>
        <button type="button" class="src-link" data-rc="notice">Source · /v1/exchange/info</button>
      </div></div>`);
  if (sharedWith.length) notices.push(`<div class="notice soft">
      <span class="notice-ico" aria-hidden="true">⇄</span>
      <div class="notice-body">
        <span class="notice-kicker">Shared wallet</span>
        <span class="notice-text">${Object.keys(d.shared_wallets).length === 1 ? 'One wallet' : Object.keys(d.shared_wallets).length + ' wallets'} listed here ${Object.keys(d.shared_wallets).length === 1 ? 'is' : 'are'} also listed by ${esc(sharedWith.join(', '))}. The same money may be counted by both.</span>
      </div></div>`);
  if (d.error) notices.push(`<div class="notice soft">
      <span class="notice-ico" aria-hidden="true">↻</span>
      <div class="notice-body"><span class="notice-kicker">Refresh problem</span>
      <span class="notice-text">The latest fetch for ${esc(d.name)} failed, so this shows the previous data.</span></div></div>`);
  const unpriced = d.unpriced.length ? `<p class="cmp-note">Not priced by CoinMarketCap, so left out of the totals: ${esc(d.unpriced.map(u => u.symbol).join(', '))}.</p>` : '';
  return `<section class="exch stagger">
    ${notices.map((n, i) => n.replace('class="notice', `style="--i:${i}" class="notice`)).join('')}
    <div class="ex-head" style="--i:${notices.length}">
      <div class="ex-head-l">
        <a class="back" href="#/compare">← All exchanges</a>
        <h1 class="ex-name" tabindex="-1" style="view-transition-name:ex-name">${esc(d.name)}</h1>
      </div>
      <div class="stat-chips">
        <button type="button" class="stat" data-rc="total"><span class="k">Reported</span><span class="v">${money(d.reported_usd)}</span></button>
        <button type="button" class="stat" data-rc="visits"><span class="k">Weekly visits</span><span class="v"${d.weekly_visits == null ? ' style="color:var(--mut)"' : ''}>${visitsLabel(d.weekly_visits)}</span></button>
        <div class="stat inset"><span class="k">Prices as of</span><span class="v mono" data-bind="quotesAt">${fmtTime(state.list.quotes_fetched_at).slice(11, 16)} UTC</span></div>
      </div>
    </div>
    <p class="sentence" style="--i:${notices.length + 1}" data-bind="sentence">${esc(d.sentences[hz])}</p>
    <div class="ex-grid" style="--i:${notices.length + 2}">
      <section class="card">
        <span class="eyebrow" data-bind="sellWithin">Sellable within ${HZ[hz].short}</span>
        <button type="button" class="bignum" data-rc="pct" data-bind="big"><span class="n">0</span><span class="pct">%</span></button>
        <p class="big-sub">≈ <strong data-bind="sellAmt">${money(d.sellable_usd[hz])}</strong> of the ${money(d.reported_usd)} shown</p>
        <div class="hz-wrap">
          <span>How long would they have to sell?</span>
          ${hzSeg('')}
        </div>
      </section>
      <section class="card" style="gap:22px">
        <span class="eyebrow">Where the ${money(d.reported_usd)} sits</span>
        <div class="bar-track" role="img" data-bind="bar" aria-label="${barAria(sh, hz)}">
          <div class="bar-fill"><span class="s"></span><span class="b"></span><span class="n"></span></div>
        </div>
        <div class="legend">
          <button type="button" data-rc="seg-s"><span class="sw" style="background:var(--calm)"></span><span class="t"><b data-bind="lgS">Sellable within ${HZ[hz].short}</b><span>Could be sold into the world's trading in time.</span></span><span class="r"><b data-bind="lgSp">${pctLabel(sh.s)}%</b><span data-bind="lgSa">≈ ${money(d.sellable_usd[hz])}</span></span></button>
          <button type="button" data-rc="seg-b"><span class="sw" style="background:var(--bigBg)"></span><span class="t"><b data-bind="lgB">Too large to sell in ${HZ[hz].short}</b><span>There is a market, but not enough trading to absorb it in time.</span></span><span class="r"><b data-bind="lgBp">${pctLabel(sh.b)}%</b><span data-bind="lgBa">≈ ${money(bigUsd(d, hz))}</span></span></button>
          <button type="button" data-rc="seg-n" class="${sh.n > 0 ? 'accent' : ''}"><span class="sw" style="background:var(--acc)"></span><span class="t"><b>∅ No market</b><span>Tokens with zero recorded trading volume.</span></span><span class="r"><b>${pctLabel(sh.n)}%</b><span>≈ ${money(d.no_market_usd)}</span></span></button>
        </div>
      </section>
    </div>
    <section style="display:flex;flex-direction:column;gap:18px;--i:${notices.length + 3}">
      <div class="sec-head">
        <h2 class="h2">What it holds</h2>
        <span class="mut" style="font-size:15px">${d.holdings.length} token${d.holdings.length === 1 ? '' : 's'} · tap a holding for details</span>
      </div>
      <div class="holds" id="holds">${holdsHTML(d, true)}</div>
      ${unpriced}
    </section>
    ${howHTML(notices.length + 4)}
  </section>`;
}

const bigUsd = (d, hz) => Math.max(0, d.reported_usd - d.sellable_usd[hz] - d.no_market_usd);
const barAria = (sh, hz) => `${pctLabel(sh.s)}% sellable, ${pctLabel(sh.b)}% too large to sell in ${HZ[hz].short}, ${pctLabel(sh.n)}% no market`;

function hzSeg(cls) {
  return `<div class="seg ${cls}" role="group" aria-label="Time horizon">${[1, 7, 30].map(h =>
    `<button type="button" data-hz="${h}" aria-pressed="${state.hz === h}">${HZ[h].short}</button>`).join('')}</div>`;
}

function holdsHTML(d, animate) {
  const shown = d.holdings.slice(0, state.holdsShown);
  const cards = shown.map((h, i) => holdHTML(h, i, animate)).join('');
  const rest = d.holdings.length - shown.length;
  return cards + (rest > 0 ? `<button type="button" class="pill more-holds" id="more-holds">Show all ${d.holdings.length} holdings</button>` : '');
}

function holdHTML(h, i, animate) {
  const nm = h.volume_24h === 0;
  const open = state.open.has(h.token_id);
  const wallets = h.wallets.slice(0, 10);
  const moreW = h.wallets.length - wallets.length;
  return `<div class="hold${nm ? ' nm' : ''}${open ? ' open' : ''}${animate ? ' pop' : ''}" style="${animate ? `animation-delay:${Math.min(i, 12) * 45}ms` : ''}" data-token="${h.token_id}">
    <button type="button" class="hold-btn" aria-expanded="${open}" aria-controls="hd-${h.token_id}">
      <span class="hold-top">
        <span class="hold-idx">${String(i + 1).padStart(2, '0')}</span>
        <span class="hold-id">
          <span class="hold-sym"><b>${esc(h.symbol)}</b>${nm ? '<span class="tag-nm">∅ No market</span>' : ''}</span>
          <span class="hold-cap">≈ ${money(h.usd)}</span>
        </span>
        <span class="hold-share">${pctLabel(h.share)}<small>%</small></span>
      </span>
      <span class="meter"><span data-w="${Math.max(0, Math.min(100, h.share * 100))}"></span></span>
      <span class="hold-stats">
        <span><span class="k">Share of reserves</span><span class="v">${pctLabel(h.share)}%</span></span>
        <span><span class="k">Days to sell</span><span class="v${nm ? ' never' : ' small'}">${daysLabel(h.days_to_sell)}</span></span>
        <span><span class="k">Share of all ${esc(h.symbol)}</span><span class="v small">${supplyLabel(h.supply_share)}</span></span>
      </span>
      <span class="hold-more"><i>+</i>${open ? 'Hide details' : 'Wallets, balance, volume'}</span>
    </button>
    <div class="hold-detail" id="hd-${h.token_id}"><div class="hold-detail-in">
      <div class="kv">
        <span>Balance</span><span>${num(h.balance)} ${esc(h.symbol)}</span>
        <span>Price</span><span>${usdFull(h.price)}</span>
        <span>24h volume</span><span>${h.volume_24h === 0 ? '$0, no trading recorded' : usdFull(h.volume_24h)}</span>
        <span>Wallets</span><span>${h.wallets.length}</span>
      </div>
      <div class="wallets"><ul>${wallets.map(w => `<li><span class="addr">${esc(w.address)}</span><span class="mut">${esc(w.platform)} · ${num(w.balance)}</span>${w.also_claimed_by ? `<span class="also">Also listed by ${esc(w.also_claimed_by.join(', '))}</span>` : ''}</li>`).join('')}</ul>
        ${moreW > 0 ? `<span class="mut" style="font-family:inherit">+ ${moreW} more wallets in the raw data</span>` : ''}</div>
      <button type="button" class="raw-btn" data-rc="hold" data-token="${h.token_id}">Open raw data →</button>
    </div></div>
  </div>`;
}

function howHTML(i) {
  return `<section class="how${state.how ? ' open' : ''}" style="--i:${i}">
    <button type="button" class="how-btn" aria-expanded="${state.how}" aria-controls="how-body">
      <span class="t"><b>How to read this</b><span>Three things this page can't tell you</span></span><i aria-hidden="true">+</i>
    </button>
    <div class="how-body" id="how-body"><div class="how-grid">
      <div><strong>Reserves aren't solvency.</strong><span>This shows what the exchange holds, not what it owes its customers.</span></div>
      <div><strong>“Sellable” is a best case.</strong><span>It assumes the exchange could sell into all of the world's daily trading of each token. Days to sell = holding ÷ that token's global daily trading.</span></div>
      <div><strong>The list is partial.</strong><span>Only wallets over $500k are listed. Balances have no timestamp, and CoinMarketCap doesn't verify them.</span></div>
    </div></div>
  </section>`;
}

function noDataHTML(d) {
  const c = state.list.coverage;
  return `<section class="exch stagger">
    ${d.notice ? `<div class="notice" role="alert" style="--i:0"><span class="notice-ico" aria-hidden="true">!</span><div class="notice-body"><span class="notice-kicker">Notice on CoinMarketCap</span><span class="notice-text">“${mdLinks(d.notice)}”</span></div></div>` : ''}
    <div class="ex-head" style="--i:1"><div class="ex-head-l">
      <a class="back" href="#/compare">← All exchanges</a>
      <h1 class="ex-name" tabindex="-1" style="view-transition-name:ex-name">${esc(d.name)}</h1>
    </div>
    <div class="stat-chips"><div class="stat inset"><span class="k">Weekly visits</span><span class="v">${visitsLabel(d.weekly_visits)}</span></div></div></div>
    <p class="sentence" style="--i:2">${esc(d.sentence)}</p>
    <p class="home-foot" style="--i:3">That's common: ${c.listed - c.with_data} of the top ${c.listed} exchanges by volume publish nothing. With no wallet list, there is nothing to check. <a class="go" href="#/compare">See the ${c.with_data} that do <span>→</span></a></p>
  </section>`;
}

function notFoundHTML(slug) {
  return `<section class="warm stagger"><h1 tabindex="-1" style="--i:0">No exchange called “${esc(slug)}”</h1>
    <p style="--i:1">This site covers CoinMarketCap's top ${state.list.coverage.listed} exchanges by volume. <a href="#/">Search again</a>.</p></section>`;
}

function compareHTML() {
  const c = state.list.coverage;
  const none = state.list.exchanges.filter(x => !x.has_data);
  return `<section class="cmp">
    <div class="stagger" style="display:flex;flex-direction:column;gap:10px">
      <h1 class="cmp-h1" tabindex="-1" style="--i:0">Compare exchanges</h1>
      <p class="cmp-lede" style="--i:1">Reported reserves next to the part that could be sold within <span data-bind="hzShort">${HZ[state.hz].short}</span>. Tap a row for the full picture.</p>
    </div>
    <div class="controls stagger">
      <div class="ctl" style="--i:2"><span class="eyebrow-sm">Time to sell</span>${hzSeg('sm')}</div>
      <div class="ctl" style="--i:3"><span class="eyebrow-sm">Sort by</span>
        <div class="seg sm" role="group" aria-label="Sort">${[['pct', 'Sellable %'], ['size', 'Reported size'], ['visits', 'Weekly visits'], ['name', 'Name']].map(([v, l]) =>
          `<button type="button" data-sort="${v}" aria-pressed="${state.sort === v}">${l}</button>`).join('')}</div></div>
      <div class="ctl" style="--i:4"><span class="eyebrow-sm">Show</span>
        <div class="filters">${[['all', `All ${c.with_data}`], ['nm', 'Has no-market tokens'], ['low', 'Under half sellable'], ['notice', 'Has a notice']].map(([v, l]) =>
          `<button type="button" class="pill" data-filter="${v}" aria-pressed="${state.filter === v}">${l}</button>`).join('')}</div></div>
    </div>
    <div class="rows stagger" id="rows">${rowsHTML()}</div>
    <p class="cmp-note">Sellable = each holding capped at days × that token's global daily trading, summed. A best case.
      <span class="keys"><span><i style="background:var(--calm)"></i>Sellable</span><span><i style="background:var(--bigBg)"></i>Too large</span><span><i style="background:var(--acc)"></i>No market</span></span></p>
    <p class="cmp-note"><strong>No reserves published (${none.length}):</strong> ${none.map(x => `<a href="#/exchange/${esc(x.slug)}">${esc(x.name)}</a>`).join(', ')}.</p>
  </section>`;
}

function rowsHTML() {
  const hz = state.hz;
  let rows = withData().map(x => ({ x, s: x.sellable_share[hz] ?? 0, n: x.no_market_share ?? 0 }));
  if (state.filter === 'nm') rows = rows.filter(r => r.n > 0);
  if (state.filter === 'low') rows = rows.filter(r => r.s < 0.5);
  if (state.filter === 'notice') rows = rows.filter(r => r.x.notice);
  const by = {
    pct: (a, b) => b.s - a.s || b.x.reported_usd - a.x.reported_usd,
    size: (a, b) => b.x.reported_usd - a.x.reported_usd,
    visits: (a, b) => (b.x.weekly_visits ?? -1) - (a.x.weekly_visits ?? -1),
    name: (a, b) => a.x.name.localeCompare(b.x.name),
  }[state.sort];
  rows.sort(by);
  if (!rows.length) return '<p class="empty-box">No exchanges match this filter.</p>';
  return rows.map((r, i) => {
    const x = r.x, b = Math.max(0, 1 - r.s - r.n);
    const vtn = x.slug === state.lastSlug ? ' style="view-transition-name:ex-name"' : '';
    return `<div class="row" role="link" tabindex="0" data-slug="${esc(x.slug)}" style="--i:${i}">
      <span class="rk">${String(i + 1).padStart(2, '0')}</span>
      <div class="mid">
        <div class="nmrow"><b class="rname"${vtn}>${esc(x.name)}</b>
          ${r.n > 0 ? `<span class="tag-nm">∅ ${pctLabel(r.n)}% no market</span>` : ''}
          ${x.notice ? '<span class="tag-notice">! Notice</span>' : ''}</div>
        <div class="bar-track thin"><div class="bar-fill"><span class="s" data-w="${r.s * 100}"></span><span class="b" data-w="${b * 100}"></span><span class="n" data-w="${r.n * 100}"></span></div></div>
        <div class="facts">
          <span>Reported <button type="button" class="linkish" data-rc="total" data-slug="${esc(x.slug)}">${money(x.reported_usd)}</button></span>
          <span>Sellable <button type="button" class="linkish" data-rc="pct" data-slug="${esc(x.slug)}">≈ ${money(x.reported_usd * r.s)}</button></span>
          <span>Weekly visits <button type="button" class="linkish" data-rc="visits" data-slug="${esc(x.slug)}">${visitsLabel(x.weekly_visits)}</button></span>
        </div>
      </div>
      <span class="big">${pctLabel(r.s)}<small>%</small></span>
    </div>`;
  }).join('');
}

/* ---------------- animation helpers ---------------- */
const rafs = new WeakMap();
function countTo(el, to, label) {
  const from = +(el.dataset.v || 0);
  el.dataset.v = to;
  cancelAnimationFrame(rafs.get(el));
  if (reduceMotion.matches || from === to) { el.textContent = label; return; }
  const t0 = performance.now(), dur = 750;
  const step = t => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = k < 1 ? String(Math.round(from + (to - from) * e)) : label;
    if (k < 1) rafs.set(el, requestAnimationFrame(step));
  };
  rafs.set(el, requestAnimationFrame(step));
}
// Widths start at 0 in CSS; set them a frame later so the transition runs.
function growBars(root) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    $$('[data-w]', root).forEach(el => { el.style.width = el.dataset.w + '%'; });
  }));
}
function setBar(track, sh) {
  const [s, b, n] = $$('.bar-fill>span', track);
  s.style.width = sh.s * 100 + '%'; b.style.width = sh.b * 100 + '%'; n.style.width = sh.n * 100 + '%';
}

/* ---------------- exchange page updates ---------------- */
function paintExchangeNumbers(d, { swapSentence = false } = {}) {
  const hz = state.hz, sh = shares(d, hz), v = $('#view');
  const bind = k => $(`[data-bind="${k}"]`, v);
  if (!bind('big')) return;
  countTo($('.n', bind('big')), pctInt(sh.s), pctLabel(sh.s));
  bind('big').setAttribute('aria-label', `${pctLabel(sh.s)} percent sellable within ${HZ[hz].short}, show source`);
  bind('sellWithin').textContent = `Sellable within ${HZ[hz].short}`;
  bind('sellAmt').textContent = money(d.sellable_usd[hz]);
  bind('lgS').textContent = `Sellable within ${HZ[hz].short}`;
  bind('lgB').textContent = `Too large to sell in ${HZ[hz].short}`;
  bind('lgSp').textContent = pctLabel(sh.s) + '%';
  bind('lgSa').textContent = '≈ ' + money(d.sellable_usd[hz]);
  bind('lgBp').textContent = pctLabel(sh.b) + '%';
  bind('lgBa').textContent = '≈ ' + money(bigUsd(d, hz));
  bind('bar').setAttribute('aria-label', barAria(sh, hz));
  requestAnimationFrame(() => setBar(bind('bar'), sh));
  const sEl = bind('sentence');
  if (swapSentence && !reduceMotion.matches) {
    sEl.classList.add('swap');
    setTimeout(() => { sEl.textContent = d.sentences[hz]; sEl.classList.remove('swap'); }, 220);
  } else sEl.textContent = d.sentences[hz];
  $$('[data-hz]', v).forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.hz === hz)));
}

/* ---------------- event binding ---------------- */
function bindView(r) {
  const v = $('#view');
  growBars(v);
  if (r.screen === 'home' && ready()) bindSearch();
  if (r.screen === 'exchange') {
    const d = state.details[r.slug];
    if (d && d.has_data) paintExchangeNumbers(d);
  }
}

// Delegated handlers on the view (survive re-renders).
$('#view').addEventListener('click', ev => {
  const t = ev.target.closest('button, [role=link]');
  if (!t) return;
  const r = route();
  const d = r.screen === 'exchange' ? state.details[r.slug] : null;

  if (t.dataset.rc) { ev.stopPropagation(); openReceipt(t.dataset.rc, t.dataset.slug || (d && d.slug), t, t.dataset.token); return; }
  if (t.dataset.hz) {
    state.hz = +t.dataset.hz;
    if (d) paintExchangeNumbers(d, { swapSentence: true });
    if (r.screen === 'compare') { $$('[data-hz]').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.hz === state.hz))); $('[data-bind="hzShort"]').textContent = HZ[state.hz].short; refreshRows(); }
    return;
  }
  if (t.dataset.sort) { state.sort = t.dataset.sort; $$('[data-sort]').forEach(b => b.setAttribute('aria-pressed', String(b === t))); refreshRows(); return; }
  if (t.dataset.filter) { state.filter = t.dataset.filter; $$('[data-filter]').forEach(b => b.setAttribute('aria-pressed', String(b === t))); refreshRows(); return; }
  if (t.classList.contains('row')) { goExchange(t); return; }
  if (t.classList.contains('hold-btn')) { toggleHold(t.closest('.hold')); return; }
  if (t.id === 'more-holds' && d) { state.holdsShown = d.holdings.length; $('#holds').innerHTML = holdsHTML(d, true); growBars($('#holds')); return; }
  if (t.classList.contains('how-btn')) {
    state.how = !state.how;
    const s = t.closest('.how'); s.classList.toggle('open', state.how); t.setAttribute('aria-expanded', String(state.how));
  }
});
$('#view').addEventListener('keydown', ev => {
  if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.classList.contains('row')) { ev.preventDefault(); goExchange(ev.target); }
});

function goExchange(row) {
  const name = $('.rname', row);
  $$('.rname').forEach(n => { n.style.viewTransitionName = ''; });
  name.style.viewTransitionName = 'ex-name';
  location.hash = '#/exchange/' + row.dataset.slug;
}

function refreshRows() {
  const rows = $('#rows');
  rows.innerHTML = rowsHTML();
  $$('.rname', rows).forEach(n => { n.style.viewTransitionName = ''; });
  growBars(rows);
}

function toggleHold(card) {
  const id = +card.dataset.token;
  const open = !state.open.has(id);
  open ? state.open.add(id) : state.open.delete(id);
  card.classList.toggle('open', open);
  const btn = $('.hold-btn', card);
  btn.setAttribute('aria-expanded', String(open));
  $('.hold-more', card).lastChild.textContent = open ? 'Hide details' : 'Wallets, balance, volume';
}

/* ---------------- search combobox ---------------- */
function bindSearch() {
  const input = $('#q'), list = $('#suggest'), go = $('#q-go');
  let active = -1, matches = [];
  const all = state.list.exchanges;
  const compute = () => {
    const q = input.value.trim().toLowerCase();
    matches = q ? all.filter(x => x.name.toLowerCase().includes(q))
      .sort((a, b) => (a.name.toLowerCase().startsWith(q) ? 0 : 1) - (b.name.toLowerCase().startsWith(q) ? 0 : 1) || a.volume_rank - b.volume_rank)
      : withData().slice(0, 8);
  };
  const paint = () => {
    compute();
    active = Math.min(active, matches.length - 1);
    list.innerHTML = matches.length ? matches.map((x, i) =>
      `<button type="button" role="option" id="opt-${i}" aria-selected="${i === active}" data-slug="${esc(x.slug)}"><span class="nm">${esc(x.name)}</span><span class="meta">${x.has_data ? money(x.reported_usd) + ' reported' : 'Publishes no reserves'}</span></button>`).join('')
      : `<p class="empty">No exchange called “${esc(input.value.trim())}” in CoinMarketCap's top ${state.list.coverage.listed} by volume. ${state.list.coverage.listed - state.list.coverage.with_data} of those publish nothing anyway.</p>`;
    input.setAttribute('aria-activedescendant', active >= 0 ? `opt-${active}` : '');
  };
  const show = on => { list.hidden = !on; input.setAttribute('aria-expanded', String(on)); if (on) paint(); };
  const pick = slug => { if (slug) location.hash = '#/exchange/' + slug; };
  input.addEventListener('focus', () => show(true));
  input.addEventListener('input', () => { active = -1; show(true); });
  input.addEventListener('blur', () => setTimeout(() => show(false), 150));
  input.addEventListener('keydown', ev => {
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') {
      ev.preventDefault(); if (list.hidden) show(true);
      active = (active + (ev.key === 'ArrowDown' ? 1 : -1) + matches.length) % Math.max(1, matches.length);
      paint(); $('#opt-' + active)?.scrollIntoView({ block: 'nearest' });
    } else if (ev.key === 'Enter') { ev.preventDefault(); compute(); pick((matches[Math.max(0, active)] || {}).slug); }
    else if (ev.key === 'Escape') show(false);
  });
  list.addEventListener('mousedown', ev => { const o = ev.target.closest('[role=option]'); if (o) { ev.preventDefault(); pick(o.dataset.slug); } });
  go.addEventListener('click', () => { if (input.value.trim()) { compute(); pick((matches[0] || {}).slug); } else input.focus(); });
}

/* ---------------- receipts ---------------- */
const receiptUrl = p => '/api/receipt?path=' + encodeURIComponent(p);
const fileLinks = (label, paths) => (paths || []).map((p, i) => ({ label: paths.length > 1 ? `${label} ${i + 1}` : label, path: p }));

function receiptFor(kind, d, token) {
  const hz = state.hz, sh = d && d.has_data ? shares(d, hz) : null;
  const rc = d && d.receipts ? d.receipts : {};
  const at = fmtTime(state.list.exchanges_fetched_at);
  const qat = fmtTime(state.list.quotes_fetched_at);
  const assetsEp = d ? `GET /v1/exchange/assets?id=${d.id}` : '';
  const quotesEp = 'GET /v3/cryptocurrency/quotes/latest?id=<every token held>';
  if (kind === 'count') {
    const c = state.list.coverage, lr = state.list.receipts || {};
    return { title: 'Who publishes reserves', value: `${c.with_data} / ${c.listed}`, at,
      endpoint: 'GET /v1/exchange/map?limit=100&sort=volume_24h\nGET /v1/exchange/assets?id=<each exchange>',
      raw: [['top_exchanges_checked', c.listed], ['publish_reserves', c.with_data], ['publish_nothing', c.listed - c.with_data]],
      files: fileLinks('exchange/map response', lr.map),
      note: 'An exchange counts as publishing if CoinMarketCap returns at least one reserve wallet for it. An empty list comes back with no error, so "publishes nothing" and "not tracked" look the same.' };
  }
  if (kind === 'total') return { title: `${d.name} · reported reserves`, value: money(d.reported_usd), at,
    endpoint: `${assetsEp}\n${quotesEp}`,
    raw: [['reported_total_usd', usdFull(d.reported_usd)], ['tokens', d.holdings.length], ['wallet_rows_collapsed', d.rows_collapsed], ['tokens_unpriced', d.unpriced.length]],
    files: [...fileLinks('exchange/assets response', rc.assets), ...fileLinks('quotes response', rc.quotes)],
    note: `Sum of balance × latest CoinMarketCap price for every wallet listed for ${d.name}. Only wallets over $500k are listed; balances have no timestamp; CMC doesn't verify them.${d.rows_collapsed ? ` ${d.rows_collapsed} duplicate row${d.rows_collapsed === 1 ? '' : 's'} (same wallet in different letter case, same balance) were counted once.` : ''}` };
  if (kind === 'pct') return { title: `${d.name} · sellable within ${HZ[hz].short}`, value: pctLabel(sh.s) + '%', at: qat,
    endpoint: `${assetsEp}\n${quotesEp}  (volume_24h)`,
    raw: [['sellable_1d', pctLabel(d.sellable_share[1]) + '%'], ['sellable_7d', pctLabel(d.sellable_share[7]) + '%'], ['sellable_30d', pctLabel(d.sellable_share[30]) + '%'],
      [`sellable_usd_${hz}d`, usdFull(d.sellable_usd[hz])], ['no_market_usd', usdFull(d.no_market_usd)], ['reported_total_usd', usdFull(d.reported_usd)]],
    files: [...fileLinks('exchange/assets response', rc.assets), ...fileLinks('quotes response', rc.quotes)],
    note: 'Each holding is capped at (days × that token\'s global 24h trading volume), then summed and divided by the reported total. A best case: selling that much would likely push prices down.' };
  if (kind.startsWith('seg-')) {
    const k = kind.slice(4);
    const m = { s: ['sellable', sh.s, d.sellable_usd[hz]], b: ['too large to sell', sh.b, bigUsd(d, hz)], n: ['no market', sh.n, d.no_market_usd] }[k];
    return { title: `${d.name} · ${m[0]} (${HZ[hz].short})`, value: pctLabel(m[1]) + '%', at: qat,
      endpoint: `${assetsEp}\n${quotesEp}  (volume_24h)`,
      raw: [['sellable', pctLabel(sh.s) + '%'], ['too_large', pctLabel(sh.b) + '%'], ['no_market', pctLabel(sh.n) + '%'], ['usd', usdFull(m[2])]],
      files: [...fileLinks('exchange/assets response', rc.assets), ...fileLinks('quotes response', rc.quotes)],
      note: 'Too large = reported − sellable − no market. No market = tokens with zero recorded 24h trading volume.' };
  }
  if (kind === 'hold') {
    const h = d.holdings.find(x => x.token_id === +token);
    return { title: `${d.name} · ${h.symbol}`, value: pctLabel(h.share) + '%', at: qat,
      endpoint: `${assetsEp}\nGET /v3/cryptocurrency/quotes/latest?id=${h.token_id}`,
      raw: [['token', `${h.name} (${h.symbol})`], ['crypto_id', h.token_id], ['balance', num(h.balance)], ['price_usd', usdFull(h.price)], ['value_usd', usdFull(h.usd)],
        ['volume_24h', usdFull(h.volume_24h)], ['days_to_sell', daysLabel(h.days_to_sell)], ['share_of_circulating_supply', supplyLabel(h.supply_share)],
        ['quote_last_updated', h.quote_last_updated], ['wallets', h.wallets.length]],
      files: [...fileLinks('exchange/assets response', rc.assets), ...fileLinks('quotes response', rc.quotes)],
      note: 'Days to sell = value ÷ 24h volume. Wallet addresses and per-wallet balances are in the exchange/assets response.' };
  }
  if (kind === 'visits') return { title: `${d.name} · weekly visits`, value: visitsLabel(d.weekly_visits), at,
    endpoint: `GET /v1/exchange/info?id=${d.id}`, raw: [['weekly_visits', d.weekly_visits == null ? 'null' : d.weekly_visits]],
    files: fileLinks('exchange/info response', rc.info),
    note: d.weekly_visits == null ? 'CoinMarketCap returns no value here. That means missing, not zero.' : 'Website visits CoinMarketCap reports for the exchange over a week. CMC doesn\'t document how it measures this.' };
  if (kind === 'notice') return { title: `${d.name} · notice`, value: 'Notice', at,
    endpoint: `GET /v1/exchange/info?id=${d.id}`, raw: [['notice', d.notice]], files: fileLinks('exchange/info response', rc.info),
    note: 'Shown exactly as CoinMarketCap publishes it.' };
  return null;
}

async function openReceipt(kind, slug, opener, token) {
  let d = null;
  if (slug) { d = state.details[slug] || await loadDetail(slug).catch(() => null); if (!d) return; }
  const r = receiptFor(kind, d, token);
  if (r) showReceipt(r, opener);
}

let receiptOpener = null;
function showReceipt(r, opener) {
  receiptOpener = opener || document.activeElement;
  $('#receipt-title').textContent = 'Receipt · ' + r.title;
  $('#receipt-val').textContent = r.value;
  $('#receipt-at').textContent = r.at;
  $('#receipt-ep').textContent = r.endpoint;
  $('#receipt-raw').innerHTML = r.raw.map(([k, v]) => `<div class="row-kv"><span>${esc(k)}</span><span>${esc(v)}</span></div>`).join('');
  $('#receipt-files').innerHTML = r.files.map(f => `<a href="${receiptUrl(f.path)}" target="_blank" rel="noopener">${esc(f.label)} ↗</a>`).join('');
  $('#receipt-note').textContent = r.note;
  $('#receipt').showModal();
}
$('#receipt-close').addEventListener('click', () => $('#receipt').close());
$('#receipt').addEventListener('click', ev => { if (ev.target === ev.currentTarget) ev.currentTarget.close(); });
$('#receipt').addEventListener('close', () => { receiptOpener?.focus?.(); });

/* ---------------- ask panel ---------------- */
const chat = { msgs: [{ role: 'b', text: 'Ask me anything about the numbers on this site. I\'ll quote the exact figures and link to where they came from.' }] };

function currentDetail() { const r = route(); return r.screen === 'exchange' ? state.details[r.slug] : null; }

function updateAskContext() {
  const d = currentDetail();
  const title = d && d.has_data ? 'Ask about this exchange' : 'Ask about reserves';
  $('#ask-title').textContent = title; $('#ask-fab-label').textContent = title;
  const sugg = [];
  if (d && d.has_data) {
    sugg.push(`Summarize ${d.name}`, `Why is ${d.name} not 100%?`);
    const top = d.holdings.find(h => h.volume_24h === 0 || (h.days_to_sell ?? 0) > 7);
    if (top) sugg.push(`What is ${top.symbol}?`);
  } else if (ready()) {
    const worst = withData().filter(x => x.no_market_share > 0).sort((a, b) => b.no_market_share - a.no_market_share)[0];
    if (worst) sugg.push(`What is ${worst.top_symbol}?`);
    sugg.push('Which exchanges have a notice?');
  }
  sugg.push('What does 7-day sellable mean?');
  $('#ask-sugg').innerHTML = sugg.slice(0, 4).map(s => `<button type="button">${esc(s)}</button>`).join('');
}

function paintMsgs() {
  const box = $('#msgs');
  box.innerHTML = chat.msgs.map((m, i) => `<div class="msg ${m.role}"><span>${esc(m.text)}</span>${m.src ? `<button type="button" class="src-link" data-msg="${i}">Source · ${esc(m.srcLabel)}</button>` : ''}</div>`).join('')
    + (chat.typing ? '<div class="typing" aria-label="Checking the data"><i></i><i></i><i></i></div>' : '');
  box.scrollTop = box.scrollHeight;
}

async function answer(q) {
  const t = q.toLowerCase();
  const L = state.list;
  if (!ready()) return { text: 'The live data is still loading. Try again in a few seconds.' };
  const named = [...L.exchanges].sort((a, b) => b.name.length - a.name.length).find(x => t.includes(x.name.toLowerCase()));
  let d = named ? (state.details[named.slug] || await loadDetail(named.slug).catch(() => null)) : currentDetail();
  const has = d && d.has_data;
  const src = (kind, extra) => ({ src: { kind, slug: d.slug, token: extra }, srcLabel: `${d.name} · ${kind === 'hold' ? 'holding' : kind === 'total' ? 'reserves' : 'sellable'}` });

  if (named && !named.has_data) return { text: `${named.name} doesn't publish any reserves that CoinMarketCap tracks, so there is nothing to measure. ${L.coverage.listed - L.coverage.with_data} of the top ${L.coverage.listed} exchanges are in the same position.` };
  if (/(should i|withdraw|move my|sell my|\bbuy\b|is it safe|\bsafe\b|trust|invest)/.test(t)) {
    if (!has) return { text: 'I can\'t tell you whether to buy, sell or move money. Open an exchange and I can tell you what its reserves data shows.' };
    return { text: `I can't tell you whether to buy, sell or move money. What the data shows for ${d.name}: ${money(d.reported_usd)} reported, ${pctLabel(d.sellable_share[7])}% sellable within 7 days, ${pctLabel(d.no_market_share)}% in tokens with no market. Reserves show what an exchange holds, not what it owes.`, ...src('pct') };
  }
  if (/notice|shut ?down|closing/.test(t)) {
    const withNotice = L.exchanges.filter(x => x.notice);
    if (!withNotice.length) return { text: 'None of the top exchanges currently has a notice on CoinMarketCap.' };
    return { text: 'CoinMarketCap shows a notice for: ' + withNotice.map(x => `${x.name} (“${x.notice.replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')}”)`).join('; ') + '.' };
  }
  const symQ = t.match(/what(?:'s| is| are)\s+([a-z0-9.$-]{2,15})\??$/i);
  if (symQ && !/sellable|days|this|it/.test(symQ[1])) {
    const sym = symQ[1].toUpperCase();
    let hd = has ? d : null, h = hd && hd.holdings.find(x => x.symbol.toUpperCase() === sym);
    if (!h) {
      const ex = withData().find(x => (x.top_symbol || '').toUpperCase() === sym);
      if (ex) { hd = state.details[ex.slug] || await loadDetail(ex.slug).catch(() => null); h = hd && hd.holdings.find(x => x.symbol.toUpperCase() === sym); }
    }
    if (!h) return { text: `I only know tokens held by the exchanges on this site, and I couldn't find ${sym}${has ? ` in ${d.name}'s holdings` : ''}. Open an exchange that holds it and ask again.` };
    d = hd;
    const trade = h.volume_24h === 0
      ? `It had no recorded trading in the last 24 hours, so it counts as "no market": none of it can be sold at any horizon.`
      : `Its global 24h trading volume is ${money(h.volume_24h)}, so selling ${d.name}'s holding would take ${daysLabel(h.days_to_sell).toLowerCase()} of all the world's trading in it.`;
    const supply = h.supply_share == null ? 'CoinMarketCap reports no circulating supply for it.' : `${d.name} holds ${supplyLabel(h.supply_share)} of all ${h.symbol} in circulation.`;
    return { text: `${h.name === h.symbol ? h.symbol : `${h.name} (${h.symbol})`} is ${pctLabel(h.share)}% of ${d.name}'s reported reserves, about ${money(h.usd)}. ${trade} ${supply} The data doesn't describe the token beyond that.`, ...src('hold', h.token_id) };
  }
  if (/solven|owe|debt|liabilit/.test(t)) return { text: `This site can't tell you that. Proof of reserves shows what ${has ? d.name : 'an exchange'} holds${has ? ` (${money(d.reported_usd)} reported)` : ''}, not what it owes its customers.`, ...(has ? src('total') : {}) };
  if (/days to sell/.test(t)) return { text: 'Days to sell = what the exchange holds of a token ÷ that token\'s global 24h trading volume. A token with zero trading never sells, which is what "no market" means.' };
  if (has && /not 100|100%|why/.test(t)) {
    const sh = shares(d, 7);
    return { text: `${d.name} is at ${pctLabel(sh.s)}% for 7 days. ${pctLabel(sh.n)}% is in tokens with no market; the other ${pctLabel(sh.b)}% is holdings too large to sell within 7 days, even using all of the world's trading. With 30 days it reaches ${pctLabel(d.sellable_share[30])}%.`, ...src('pct') };
  }
  if (/sellable|7.?day|mean|how does|how is/.test(t)) {
    const base = 'It\'s the share of the reported total that could be sold within 7 days, if the exchange could sell into all of the world\'s daily trading of each token. It\'s a best case: selling that much would likely push prices down.';
    return has ? { text: `${base} For ${d.name}: ${pctLabel(d.sellable_share[7])}% of ${money(d.reported_usd)}, about ${money(d.sellable_usd[7])}.`, ...src('pct') } : { text: base };
  }
  if (has) {
    const top = d.holdings.slice(0, 3).map(h => `${h.symbol} ${pctLabel(h.share)}%`).join(', ');
    return { text: `${d.sentences[7]} Sellable within 1 day: ${pctLabel(d.sellable_share[1])}%, 30 days: ${pctLabel(d.sellable_share[30])}%. Largest holdings: ${top}.`, ...src('pct') };
  }
  return { text: `This site checks the reserves of CoinMarketCap's top ${L.coverage.listed} exchanges; ${L.coverage.with_data} publish any. Search for your exchange, or ask about one by name, e.g. "Summarize Binance".` };
}

async function ask(q) {
  q = (q || '').trim(); if (!q) return;
  chat.msgs.push({ role: 'u', text: q }); chat.typing = true; paintMsgs();
  $('#ask-input').value = '';
  const [a] = await Promise.all([answer(q), new Promise(r => setTimeout(r, reduceMotion.matches ? 0 : 500))]);
  chat.typing = false; chat.msgs.push({ role: 'b', ...a }); paintMsgs();
}

function setAsk(open) {
  $('#ask').hidden = !open; $('#ask-fab').hidden = open;
  if (open) { paintMsgs(); setTimeout(() => $('#ask-input').focus(), 50); } else $('#ask-fab').focus();
}
$('#ask-fab').addEventListener('click', () => setAsk(true));
$('#ask-close').addEventListener('click', () => setAsk(false));
$('#ask').addEventListener('keydown', ev => { if (ev.key === 'Escape') setAsk(false); });
$('#ask-form').addEventListener('submit', ev => { ev.preventDefault(); ask($('#ask-input').value); });
$('#ask-sugg').addEventListener('click', ev => { const b = ev.target.closest('button'); if (b) ask(b.textContent); });
$('#msgs').addEventListener('click', ev => {
  const b = ev.target.closest('[data-msg]'); if (!b) return;
  const s = chat.msgs[+b.dataset.msg].src; openReceipt(s.kind, s.slug, b, s.token);
});

/* ---------------- theme ---------------- */
function paintTheme() { $$('[data-theme-opt]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.themeOpt === document.documentElement.dataset.theme))); }
$$('[data-theme-opt]').forEach(b => b.addEventListener('click', () => {
  const t = b.dataset.themeOpt;
  const apply = () => { document.documentElement.dataset.theme = t; paintTheme(); };
  if (document.startViewTransition && !reduceMotion.matches) document.startViewTransition(apply).ready.catch(() => {}); else apply();
  try { localStorage.setItem('sr-theme', t); } catch (_) { /* storage unavailable */ }
}));
paintTheme();

/* ---------------- live status & polling ---------------- */
function updateLive() {
  const el = $('#live'), txt = $('#live-text');
  const L = state.list;
  if (!L || !ready()) { el.className = 'live warming'; txt.textContent = 'Warming up…'; return; }
  const q = parseTs(L.quotes_fetched_at);
  if (L.mode === 'replay') { el.className = 'live replay'; txt.textContent = 'Saved data · prices from ' + fmtTime(L.quotes_fetched_at).slice(11, 16) + ' UTC'; }
  else {
    const stale = Date.now() - q > 5 * 60 * 1000;
    el.className = 'live' + (stale ? ' stale' : '');
    txt.textContent = (stale ? 'Stale · prices ' : 'Live · prices ') + ago(q);
  }
  const qa = $('[data-bind="quotesAt"]'); if (qa) qa.textContent = fmtTime(L.quotes_fetched_at).slice(11, 16) + ' UTC';
}
setInterval(updateLive, 1000);

async function poll() {
  const wasReady = ready();
  const before = state.list && state.list.quotes_fetched_at;
  try { await loadList(); } catch (_) { updateLive(); return; }
  if (!wasReady && ready()) { navigate(); return; }
  if (!ready() || state.list.quotes_fetched_at === before) return;
  const r = route();
  if (r.screen === 'exchange' && state.details[r.slug]?.has_data) {
    const d = await loadDetail(r.slug).catch(() => null);
    if (d && d.has_data) {
      paintExchangeNumbers(d);
      $('[data-bind="big"]')?.classList.remove('tick'); void $('[data-bind="big"]')?.offsetWidth; $('[data-bind="big"]')?.classList.add('tick');
      const holds = $('#holds'); if (holds) { holds.innerHTML = holdsHTML(d, false); $$('[data-w]', holds).forEach(e => { e.style.width = e.dataset.w + '%'; }); }
    }
  } else if (r.screen === 'compare') {
    refreshRows();
  }
  Object.keys(state.details).forEach(s => { if (s !== r.slug) delete state.details[s]; });
}

window.addEventListener('hashchange', navigate);
(async function start() {
  try { await loadList(); } catch (_) { /* server unreachable: warm screen, keep polling */ }
  await navigate();
  // Poll fast while the server warms up, then every POLL_MS.
  const loop = async () => { await poll(); setTimeout(loop, ready() ? POLL_MS : 3000); };
  setTimeout(loop, ready() ? POLL_MS : 3000);
})();
