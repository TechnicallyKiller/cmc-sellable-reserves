'use strict';
/* Docs (#/docs) and MCP (#/mcp) pages. Static content plus two live pieces on
   the MCP page: the tool list is read from this server's own /mcp endpoint, and
   "Try it" makes real MCP tools/call requests from the browser. */

const Pages = (() => {
  const E = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const code = (txt, label) => `<div class="code"><pre tabindex="0" aria-label="${E(label || 'code')}"><code>${E(txt)}</code></pre><button type="button" class="copy" data-copy="${E(txt)}" aria-label="Copy ${E(label || 'code')}">Copy</button></div>`;
  const origin = () => location.origin;

  function toc(items) {
    return `<nav class="doc-toc" aria-label="On this page">${items.map(([id, t]) => `<a href="#" data-jump="${id}">${E(t)}</a>`).join('')}</nav>`;
  }

  function docsHTML(cov) {
    const listed = cov ? cov.listed : 100, withData = cov ? cov.with_data : '–';
    return `<article class="doc stagger">
      <header class="doc-head" style="--i:0">
        <p class="home-kicker">Docs</p>
        <h1 class="cmp-h1" tabindex="-1">How Sellable Reserves works</h1>
        <p class="cmp-lede">Exchanges publish "proof of reserves" as one dollar total. That total adds Bitcoin and tokens nobody trades as if they were the same. This site measures how much of it could actually be sold, and shows the raw data behind every number.</p>
      </header>
      ${toc([['d-metric', 'The metric'], ['d-data', 'Data sources'], ['d-clean', 'Data cleaning'], ['d-limits', 'Limits'], ['d-api', 'Public API'], ['d-ai', 'Ask panel'], ['d-a11y', 'Accessibility'], ['d-src', 'Source code']])}

      <section class="card doc-card" id="d-metric" style="--i:1">
        <h2 class="h2">The metric</h2>
        <p>For each token an exchange holds, CoinMarketCap gives the balance, the price, and the token's global trading volume over the last 24 hours.</p>
        <dl class="defs">
          <div><dt>Value</dt><dd>balance × price</dd></div>
          <div><dt>Days to sell</dt><dd>value ÷ 24h volume: how many days of the <em>whole world's</em> trading in that token it would take to sell the holding</dd></div>
          <div><dt>Sellable within N days</dt><dd>Σ min(value, N × 24h volume), across all tokens: each holding counts only up to what N days of global trading could absorb</dd></div>
          <div><dt>No market</dt><dd>holdings in tokens with zero 24h trading volume; never sellable, shown separately, never counted as zero</dd></div>
          <div><dt>Time until 50% / 90%</dt><dd>solved exactly: sellable(d) is piecewise linear with a break at each holding's days-to-sell, so it is solved segment by segment. "Never" when no-market tokens make the target unreachable.</dd></div>
          <div><dt>Share of supply</dt><dd>the exchange's balance ÷ the token's circulating supply; "not reported" when CoinMarketCap has no supply figure</dd></div>
        </dl>
        <p class="doc-note">It is a <strong>best case</strong>: it assumes the exchange could sell into all of the world's trading of each token without moving the price.</p>
      </section>

      <section class="card doc-card" id="d-data" style="--i:2">
        <h2 class="h2">Data sources</h2>
        <p>Everything comes from the CoinMarketCap API. The server refreshes on a fixed schedule and visitors read the latest refresh, so traffic never adds API calls.</p>
        <div class="table-wrap"><table class="doc-table">
          <thead><tr><th scope="col">Endpoint</th><th scope="col">Used for</th><th scope="col">Refresh</th></tr></thead>
          <tbody>
            <tr><td><code>/v1/exchange/map?sort=volume_24h</code></td><td>the top ${listed} exchanges by volume</td><td>10 min</td></tr>
            <tr><td><code>/v1/exchange/assets?id=…</code></td><td>wallet holdings per exchange (${withData} of ${listed} publish any)</td><td>10 min</td></tr>
            <tr><td><code>/v1/exchange/info?id=…</code></td><td>weekly visits, notices (e.g. shutdowns)</td><td>10 min</td></tr>
            <tr><td><code>/v3/cryptocurrency/quotes/latest?id=…</code></td><td>price, 24h volume, circulating supply for every held token</td><td>60 s</td></tr>
          </tbody></table></div>
        <p>Tap any number on the site to open its <strong>receipt</strong>: the endpoint, the values, and a link to the exact raw response it came from. Hourly history is stored in Postgres (Supabase).</p>
      </section>

      <section class="card doc-card" id="d-clean" style="--i:3">
        <h2 class="h2">Data cleaning</h2>
        <ul class="doc-list">
          <li><strong>Duplicate wallets.</strong> The same EVM wallet sometimes appears twice in different letter case with the identical balance. It is counted once, and the receipt says how many rows were collapsed.</li>
          <li><strong>Shared wallets.</strong> A wallet listed by more than one exchange is flagged on each of them. It is not removed from either: the data gives no basis to decide who owns it.</li>
          <li><strong>Unpriced tokens.</strong> Tokens CoinMarketCap returns no quote for are listed separately and left out of totals, never treated as $0.</li>
          <li><strong>Missing values stay missing.</strong> A missing weekly-visits figure shows "Not published", not 0.</li>
        </ul>
      </section>

      <section class="card doc-card" id="d-limits" style="--i:4">
        <h2 class="h2">Limits</h2>
        <div class="how-grid" style="padding:0">
          <div><strong>Reserves aren't solvency.</strong><span>This shows what an exchange holds, not what it owes its customers. Liabilities are not published.</span></div>
          <div><strong>"Sellable" is a best case.</strong><span>Real selling at this scale would push prices down.</span></div>
          <div><strong>The wallet list is partial.</strong><span>CoinMarketCap lists only wallets over $500k. Balances carry no timestamp, and CMC doesn't verify them.</span></div>
          <div><strong>Not advice.</strong><span>The site describes data. It never recommends depositing, withdrawing, buying or selling.</span></div>
        </div>
      </section>

      <section class="card doc-card" id="d-api" style="--i:5">
        <h2 class="h2">Public API</h2>
        <p>The same data as JSON, no key needed. For AI agents, use the <a href="#/mcp">MCP server</a>.</p>
        <div class="table-wrap"><table class="doc-table">
          <thead><tr><th scope="col">Route</th><th scope="col">Returns</th></tr></thead>
          <tbody>
            <tr><td><code>GET /api/exchanges</code></td><td>one row per exchange: reported total, sellable shares, no-market share, visits, notice</td></tr>
            <tr><td><code>GET /api/exchange/&lt;slug&gt;</code></td><td>full detail: holdings, wallets, curve, milestones, sentences, receipts</td></tr>
            <tr><td><code>GET /api/history/&lt;slug&gt;</code></td><td>hourly sellable shares, last 30 days</td></tr>
            <tr><td><code>GET /api/receipt?path=…</code></td><td>the raw CoinMarketCap response behind a number</td></tr>
            <tr><td><code>GET /api/status</code></td><td>refresh times and coverage</td></tr>
            <tr><td><code>POST /mcp</code></td><td>MCP server for AI agents</td></tr>
          </tbody></table></div>
        ${code(`curl ${origin()}/api/exchange/lbank`, 'curl example')}
      </section>

      <section class="card doc-card" id="d-ai" style="--i:6">
        <h2 class="h2">Ask panel</h2>
        <p>Questions are answered by an LLM that sees only a small extract of the live data for the page you're on, pre-rounded exactly as the page shows it, and is told to copy numbers rather than recompute them. Answers are labelled with the model's name and link to a receipt. Questions about buying, selling or moving money always get a fixed reply, never the model. If the model is unavailable or rate limited, rule-based answers take over.</p>
      </section>

      <section class="card doc-card" id="d-a11y" style="--i:7">
        <h2 class="h2">Accessibility</h2>
        <p>Every screen is audited with axe-core against WCAG 2.2 AA in light and dark mode, with zero violations. Everything works with a keyboard, charts can be explored with the arrow keys and each has a table view, chart colours are checked for colour-blind separation, and all motion stops when your system asks for reduced motion.</p>
      </section>

      <section class="card doc-card" id="d-src" style="--i:8">
        <h2 class="h2">Source code</h2>
        <p>Open source, Python standard library only, with tests, a decision log and the raw evidence behind each decision: <a href="https://github.com/TechnicallyKiller/cmc-sellable-reserves" target="_blank" rel="noopener">github.com/TechnicallyKiller/cmc-sellable-reserves</a>. Built for #BuildwithCMC.</p>
      </section>
    </article>`;
  }

  const CLIENTS = [
    ['claude', 'Claude Code', () => `claude mcp add --transport http sellable-reserves ${origin()}/mcp`],
    ['gemini', 'Gemini CLI', () => `gemini mcp add --transport http sellable-reserves ${origin()}/mcp`],
    ['codex', 'Codex', () => `codex mcp add sellable-reserves --url ${origin()}/mcp`],
    ['json', 'Config file', () => JSON.stringify({ mcpServers: { 'sellable-reserves': { type: 'http', url: `${origin()}/mcp` } } }, null, 2)],
    ['inspector', 'MCP Inspector', () => `npx @modelcontextprotocol/inspector --cli ${origin()}/mcp --transport http --method tools/list`],
  ];
  const CLIENT_NOTE = {
    claude: 'Then ask Claude, e.g. "Which exchanges hold BNB, and how long would each take to sell it?"',
    gemini: 'Or add "httpUrl" under "mcpServers" in Gemini CLI\'s settings.json.',
    codex: 'Or add [mcp_servers.sellable-reserves] with url = "…/mcp" to Codex\'s config.toml.',
    json: 'The shape most MCP clients accept. Some name the URL key differently (Gemini CLI uses "httpUrl").',
    inspector: 'The official MCP debugging tool: lists the tools and lets you call them.',
  };
  const EXAMPLES = [
    ['token_exposure', { symbol: 'BNB' }, 'Who holds BNB?'],
    ['get_exchange_reserves', { exchange: 'LBank' }, 'LBank in detail'],
    ['list_exchanges', { filter: 'under_half', horizon_days: 7 }, 'Under half sellable'],
    ['compare_exchanges', { exchanges: ['Binance', 'OKX', 'LBank'], horizon_days: 7 }, 'Compare three'],
  ];

  function mcpHTML() {
    return `<article class="doc stagger">
      <header class="doc-head" style="--i:0">
        <p class="home-kicker">For AI agents</p>
        <h1 class="cmp-h1" tabindex="-1">Sellable Reserves over MCP</h1>
        <p class="cmp-lede">An AI agent managing someone's crypto can check how liquid an exchange's reserves are before it acts. Connect any MCP client to one URL. It works with any model, needs no login, and every answer carries its limits and links to the raw data.</p>
      </header>

      <section class="card doc-card" style="--i:1">
        <h2 class="h2">Endpoint</h2>
        ${code(`${origin()}/mcp`, 'endpoint URL')}
        <ul class="facts-list">
          <li><b>Transport</b> Streamable HTTP</li>
          <li><b>Protocol</b> 2026-07-28, plus 2025-11-25 / 06-18 / 03-26</li>
          <li><b>Access</b> read-only, no auth, 60 requests/min per client</li>
          <li><b>Cost</b> reads cached data: agent calls add no API calls</li>
        </ul>
      </section>

      <section class="card doc-card" style="--i:2">
        <h2 class="h2">Connect</h2>
        <div class="seg sm client-tabs" role="tablist" aria-label="MCP client">${CLIENTS.map(([id, label], i) =>
          `<button type="button" role="tab" id="tab-${id}" aria-controls="panel-client" aria-selected="${i === 0}" tabindex="${i === 0 ? 0 : -1}" data-client="${id}">${label}</button>`).join('')}</div>
        <div id="panel-client" role="tabpanel" aria-labelledby="tab-claude">${code(CLIENTS[0][2](), 'command')}<p class="doc-note" id="client-note">${E(CLIENT_NOTE.claude)}</p></div>
      </section>

      <section class="card doc-card" style="--i:3">
        <div class="chart-head"><div><h2 class="h2">Tools</h2>
          <p class="chart-sub">Read live from this server's <code>tools/list</code>, so this list always matches what agents see.</p></div></div>
        <div class="tool-grid" id="tool-grid"><p class="mut">Loading tools…</p></div>
      </section>

      <section class="card doc-card" style="--i:4">
        <h2 class="h2">Try it</h2>
        <p class="chart-sub">Each button sends a real MCP <code>tools/call</code> to <code>/mcp</code> and shows what an agent receives.</p>
        <div class="chips try-chips">${EXAMPLES.map(([tool, args, label], i) =>
          `<button type="button" class="pill" data-try="${i}">${E(label)}</button>`).join('')}</div>
        <div id="try-out" class="try-out" aria-live="polite" hidden></div>
      </section>

      <section class="card doc-card" style="--i:5">
        <h2 class="h2">What agents are told</h2>
        <ul class="doc-list">
          <li>Report the numbers and their limits; never present them as a reason to deposit, withdraw, buy or sell.</li>
          <li>Reserves are assets only, not solvency. "Sellable" is this site's best-case calculation from CoinMarketCap data, not a CoinMarketCap metric.</li>
          <li>Token names are CoinMarketCap's; the data doesn't describe what a token is. Missing values are spelled out ("not reported") so agents don't fill gaps.</li>
        </ul>
        <p class="doc-note">These rules come from testing with a real agent, which invented a token description and a supply share whenever the tool text left a gap.</p>
      </section>
    </article>`;
  }

  // ---- MCP calls from the page (same origin, so the Origin check passes) ----
  let rpcId = 0;
  async function rpc(method, params) {
    const r = await fetch('/mcp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-06-18' },
      body: JSON.stringify({ jsonrpc: '2.0', id: ++rpcId, method, params }),
    });
    const j = await r.json();
    if (j.error) throw new Error(j.error.message);
    return j.result;
  }

  async function loadTools() {
    const grid = document.getElementById('tool-grid'); if (!grid) return;
    try {
      const { tools } = await rpc('tools/list', {});
      if (!document.getElementById('tool-grid')) return;
      grid.innerHTML = tools.map(t => {
        const props = t.inputSchema.properties || {}, req = new Set(t.inputSchema.required || []);
        const args = Object.entries(props).map(([k, v]) => `<li><code>${E(k)}</code>${req.has(k) ? ' <span class="req">required</span>' : ''} <span class="mut">${E(v.description || (v.enum ? 'one of ' + v.enum.join(', ') : v.type))}</span></li>`).join('');
        return `<div class="tool pop"><div class="tool-top"><code class="tool-name">${E(t.name)}</code>${t.annotations?.readOnlyHint ? '<span class="tag-shared">read-only</span>' : ''}</div>
          <b>${E(t.title || '')}</b><p>${E(t.description)}</p>${args ? `<ul class="args">${args}</ul>` : ''}</div>`;
      }).join('');
    } catch (e) {
      grid.innerHTML = `<p class="mut">Couldn't load tools: ${E(e.message)}</p>`;
    }
  }

  async function tryTool(i) {
    const [name, args] = EXAMPLES[i];
    const out = document.getElementById('try-out');
    out.hidden = false;
    out.innerHTML = `<p class="mut">Calling <code>${E(name)}</code>…</p>`;
    const req = { jsonrpc: '2.0', method: 'tools/call', params: { name, arguments: args } };
    try {
      const res = await rpc('tools/call', { name, arguments: args });
      out.innerHTML = `<div class="try-grid">
        <div><span class="eyebrow-sm">Request</span>${code(JSON.stringify(req, null, 2), 'request')}</div>
        <div><span class="eyebrow-sm">Text the agent reads</span><div class="try-text" tabindex="0" role="region" aria-label="Tool result text">${E(res.content.map(c => c.text).join('\n'))}</div></div>
      </div>
      <details class="chart-table"><summary>Structured result (JSON)</summary>${code(JSON.stringify(res.structuredContent, null, 2), 'structured result')}</details>`;
    } catch (e) {
      out.innerHTML = `<p class="mut">Call failed: ${E(e.message)}</p>`;
    }
  }

  function bind(view, screen, toast) {
    view.addEventListener('click', onClick);
    function onClick(ev) {
      const t = ev.target.closest('button, a');
      if (!t || !view.contains(t)) return;
      if (t.dataset.jump) { ev.preventDefault(); document.getElementById(t.dataset.jump)?.scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' }); return; }
      if (t.classList.contains('copy')) {
        navigator.clipboard.writeText(t.dataset.copy).then(() => toast('Copied'), () => toast('Copy failed: select the text instead'));
        return;
      }
      if (t.dataset.client) {
        const c = CLIENTS.find(x => x[0] === t.dataset.client);
        view.querySelectorAll('[data-client]').forEach(b => { const on = b === t; b.setAttribute('aria-selected', String(on)); b.tabIndex = on ? 0 : -1; });
        const panel = document.getElementById('panel-client');
        panel.setAttribute('aria-labelledby', t.id);
        panel.innerHTML = code(c[2](), 'command') + `<p class="doc-note">${E(CLIENT_NOTE[c[0]])}</p>`;
        return;
      }
      if (t.dataset.try) tryTool(+t.dataset.try);
    }
    // Tabs: arrow keys move between clients (WAI-ARIA tabs pattern).
    view.addEventListener('keydown', onKey);
    function onKey(ev) {
      const t = ev.target.closest('[role=tab]');
      if (!t || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(ev.key)) return;
      const tabs = [...view.querySelectorAll('[role=tab]')], i = tabs.indexOf(t);
      const next = ev.key === 'Home' ? 0 : ev.key === 'End' ? tabs.length - 1 : (i + (ev.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      ev.preventDefault(); tabs[next].focus(); tabs[next].click();
    }
    if (screen === 'mcp') loadTools();
    return () => { view.removeEventListener('click', onClick); view.removeEventListener('keydown', onKey); };
  }

  return { docsHTML, mcpHTML, bind };
})();
