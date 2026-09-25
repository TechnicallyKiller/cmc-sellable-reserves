/* End-to-end browser checks: flows, keyboard access, and an axe-core WCAG 2.2 AA
   audit of every screen in light and dark. Exits non-zero on any failure.

   Setup (once):  cd tests/e2e && npm install && npx playwright-core install chromium
   Run:           python3 server.py --replay &   (or live with CMC_KEY)
                  node tests/e2e/run.js [http://localhost:8000]
   CHROMIUM_PATH can point at an existing Chromium/headless-shell binary. */
const { chromium } = require('playwright-core');
const fs = require('fs');
const assert = require('assert/strict');

const BASE = process.argv[2] || 'http://localhost:8000';
const AXE = fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');
const wait = ms => new Promise(r => setTimeout(r, ms));
let failures = 0;

async function check(name, fn) {
  try { await fn(); console.log('  ok  ', name); }
  catch (e) { failures++; console.log('  FAIL', name, '\n       ', e.message.split('\n')[0]); }
}

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const errors = [];
  async function page(opts = {}) {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, ...opts });
    const p = await ctx.newPage();
    p.on('pageerror', e => errors.push(e.message));
    p.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
    return p;
  }

  console.log('flows');
  const p = await page({ colorScheme: 'light' });
  await p.goto(BASE + '/#/'); await wait(1500);
  const listed = await p.evaluate(() => fetch('/api/exchanges').then(r => r.json()));
  const withData = listed.exchanges.filter(x => x.has_data);
  assert.ok(withData.length > 0, 'server has no data yet');
  const sample = withData[0];

  await check('search finds an exchange and opens it with Enter', async () => {
    await p.click('#q'); await p.keyboard.type(sample.name.slice(0, 4)); await wait(300);
    const names = await p.$$eval('#suggest [role=option] .nm', els => els.map(e => e.textContent));
    assert.ok(names.includes(sample.name), `suggestions ${names}`);
    await p.keyboard.press('ArrowDown'); await p.keyboard.press('Enter'); await wait(1500);
    assert.match(await p.textContent('h1'), /\S/);
  });
  await check('exchange page: headline, curve and table agree with the API', async () => {
    await p.goto(`${BASE}/#/exchange/${sample.slug}`); await wait(2000);
    const d = await p.evaluate(s => fetch('/api/exchange/' + s).then(r => r.json()), sample.slug);
    const big = await p.textContent('[data-bind=big] .n');
    const want = d.sellable_share['7'] === 0 ? '0' : d.sellable_share['7'] < 0.01 ? '<1' : d.sellable_share['7'] >= 0.995 && d.sellable_share['7'] < 1 ? '99' : String(Math.round(d.sellable_share['7'] * 100));
    assert.equal(big, want);
    assert.ok(await p.$('#curve svg'), 'curve not drawn');
    assert.equal(await p.$$eval('#curve ~ .chart-table tbody tr', r => r.length), 6);
  });
  await check('history chart (when enabled) survives navigating away', async () => {
    const before = errors.length;
    await p.goto(`${BASE}/#/exchange/${sample.slug}`); await wait(2500);
    await p.goto(BASE + '/#/compare'); await wait(1500);
    await p.setViewportSize({ width: 1000, height: 900 }); await wait(500);
    await p.setViewportSize({ width: 1280, height: 900 });
    await p.goto(`${BASE}/#/exchange/${sample.slug}`); await wait(1500);
    assert.deepEqual(errors.slice(before), []);
  });
  await check('horizon toggle updates number and URL', async () => {
    await p.click('[data-hz="30"]'); await wait(900);
    assert.match(await p.textContent('[data-bind=sellWithin]'), /30 days/);
    assert.match(p.url(), /hz=30/);
    await p.click('[data-hz="7"]'); await wait(300);
  });
  await check('receipt opens with raw-response links that resolve', async () => {
    await p.click('[data-rc="total"]'); await wait(500);
    const href = await p.$eval('#receipt-files a', a => a.href);
    const r = await p.request.get(href);
    assert.equal(r.status(), 200);
    assert.ok((await r.json()).status, 'raw CMC response has a status block');
    await p.keyboard.press('Escape'); await wait(400);
    assert.equal(await p.$eval('#receipt', d => d.open), false);
  });
  await check('ask panel answers (LLM or rule-based fallback)', async () => {
    await p.click('#ask-fab'); await p.fill('#ask-input', `Summarize ${sample.name}`); await p.press('#ask-input', 'Enter');
    await p.waitForFunction(() => document.querySelectorAll('.msg.b').length >= 2, null, { timeout: 30000 });
    assert.ok((await p.$$eval('.msg.b span', e => e.at(-1).textContent)).length > 20);
    await p.keyboard.press('Escape');
  });
  await check('advice questions get the fixed refusal', async () => {
    await p.click('#ask-fab'); await p.fill('#ask-input', `Should I withdraw from ${sample.name}?`); await p.press('#ask-input', 'Enter');
    await wait(1200);
    assert.match(await p.$$eval('.msg.b', e => e.at(-1).textContent), /can't tell you whether to buy, sell or move money/);
    await p.keyboard.press('Escape');
  });
  await check('compare: scatter, filters in URL, row opens exchange', async () => {
    await p.goto(BASE + '/#/compare'); await wait(2000);
    assert.equal(await p.$$eval('#scatter .bubble', b => b.length), withData.length);
    await p.click('[data-filter="low"]'); await wait(400);
    assert.match(p.url(), /filter=low/);
    await p.click('[data-filter="all"]'); await wait(300);
    await p.click('.row'); await wait(1500);
    assert.match(p.url(), /#\/exchange\//);
  });
  await check('share link page carries preview tags', async () => {
    const html = await (await p.request.get(`${BASE}/e/${sample.slug}`)).text();
    assert.match(html, /<meta property="og:title" content="[^"]*sold within a week">/);
  });

  console.log('keyboard');
  const k = await page({ colorScheme: 'light' });
  await k.goto(BASE + '/#/'); await wait(1500);
  await check('first Tab reaches the skip link, which moves focus to main', async () => {
    await k.keyboard.press('Tab');
    assert.equal(await k.evaluate(() => document.activeElement.className), 'skip');
    await k.keyboard.press('Enter');
    assert.equal(await k.evaluate(() => document.activeElement.id), 'view');
  });
  await check('curve is keyboard-explorable', async () => {
    await k.goto(`${BASE}/#/exchange/${sample.slug}`); await wait(2000);
    await k.focus('#curve svg'); await k.keyboard.press('ArrowRight'); await wait(150);
    assert.match(await k.textContent('#curve .chart-tip'), /sellable within/);
  });
  await check('receipt dialog returns focus to its opener on close', async () => {
    await k.focus('[data-rc="total"]'); await k.keyboard.press('Enter'); await wait(400);
    await k.keyboard.press('Escape'); await wait(400);
    assert.equal(await k.evaluate(() => document.activeElement.dataset.rc), 'total');
  });

  console.log('accessibility (axe-core, WCAG 2.2 AA + best practice)');
  for (const scheme of ['light', 'dark']) {
    const a = await page({ colorScheme: scheme, reducedMotion: 'reduce' });
    for (const [label, url, setup] of [
      ['home', '/#/'], ['exchange', `/#/exchange/${sample.slug}`], ['compare', '/#/compare'],
      ['receipt open', `/#/exchange/${sample.slug}`, () => a.click('[data-rc="total"]')],
      ['ask open', '/#/compare', () => a.click('#ask-fab')],
    ]) {
      await check(`${scheme} ${label}: no violations`, async () => {
        await a.goto(BASE + url); await wait(1500);
        if (setup) { await setup(); await wait(500); }
        await a.addScriptTag({ content: AXE });
        const v = await a.evaluate(async () => (await axe.run(document, { runOnly: ['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa', 'best-practice'] }))
          .violations.map(x => `${x.id} (${x.nodes.length}): ${x.nodes[0].target.join(' ')}`));
        assert.deepEqual(v, []);
      });
    }
  }

  await check('no page errors during the run', async () => assert.deepEqual(errors, []));
  await browser.close();
  console.log(failures ? `\n${failures} failed` : '\nall passed');
  process.exit(failures ? 1 : 0);
})();
