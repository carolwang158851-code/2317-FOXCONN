// Actual Edge button-click acceptance. All non-GET traffic is blocked.
// Usage: node tests/p1008_launcher_refresh_browser_check.js URL PRODUCTION_ROOT
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

async function main() {
  const base = process.argv[2];
  const root = process.argv[3];
  assert(base && root, 'URL and read-only runtime root required');
  const identity = () => Object.fromEntries([
    '2317_daily_market_activity.csv', '2317_daily_price.csv', 'CSV_AUTHORITY_MANIFEST.json',
    'fx_trend_observations.csv', 'macro_event_observations.csv', 'macro_snapshot.csv',
  ].map(name => {
    const bytes = fs.readFileSync(path.join(root, 'data', name));
    return [name, [bytes.length, crypto.createHash('sha256').update(bytes).digest('hex')]];
  }));
  const before = identity();
  const currentJob = JSON.parse(fs.readFileSync(path.join(root, 'runtime/p1008_app_state.json'), 'utf8'));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage();
    await page.addInitScript(() => {
      window.refreshTrace = { bindings: [], clicks: 0 };
      const add = EventTarget.prototype.addEventListener;
      EventTarget.prototype.addEventListener = function (type, listener, ...rest) {
        if (this.id === 'refresh' && type === 'click') {
          refreshTrace.bindings.push(listener.name);
          const original = listener;
          listener = function (...args) { refreshTrace.clicks++; return original.apply(this, args); };
        }
        return add.call(this, type, listener, ...rest);
      };
      // Isolate manual clicks from the periodic poll for exact request counts.
      window.setInterval = () => 0;
    });
    const requests = [], consoleErrors = [], pageErrors = [], responses = [];
    let fault = '', nonGet = 0;
    page.on('request', r => requests.push({ method: r.method(), url: r.url() }));
    page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', e => pageErrors.push(e.stack));
    page.on('response', async r => {
      if (new URL(r.url()).pathname === '/api/p1008/refresh' && r.status() === 200) {
        responses.push(await r.json());
      }
    });
    await page.route('**/*', async route => {
      const request = route.request();
      if (request.method() !== 'GET') { nonGet++; return route.abort(); }
      if (new URL(request.url()).origin !== new URL(base).origin) return route.abort();
      if (new URL(request.url()).pathname === '/api/p1008/refresh') {
        await new Promise(resolve => setTimeout(resolve, 350));
        if (fault === 'backend') return route.fulfill({ status: 409, contentType: 'application/json',
          body: JSON.stringify({ error: 'REFRESH_TEST_BACKEND_FAILURE' }) });
      }
      return route.continue();
    });
    await page.goto(new URL('/launcher.html?stay=1', base).href);
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    assert.deepEqual(await page.evaluate(() => refreshTrace.bindings), ['refreshAll']);
    console.log('PASS 1: exactly one bound refresh handler');
    const initial = responses[responses.length - 1];
    assert(initial && initial.app.serverInstanceId);
    // Give the existing visible job text a stale value, without changing disk or server.
    await page.locator('#job-id').evaluate(el => { el.textContent = 'STALE_VISIBLE_JOB'; });
    requests.length = 0;
    await page.locator('#refresh').click();
    assert.equal(await page.locator('#refresh').isDisabled(), true);
    assert.match(await page.locator('#refresh-feedback').innerText(), /正在重新讀取/);
    await page.waitForFunction(() => document.getElementById('refresh-feedback').textContent.startsWith('已刷新狀態'));
    assert.equal(requests.filter(r => new URL(r.url).pathname === '/api/p1008/refresh').length, 1);
    assert.equal(requests.filter(r => r.url.includes('/api/')).length, 1);
    console.log('PASS 2: one click sends one GET refresh request');
    assert.equal(await page.locator('#job-id').innerText(), currentJob.jobId);
    assert.equal(await page.locator('#formal-boundary').innerText(), 'Owner 已發布');
    console.log('PASS 3: fresh response updates displayed state with visible loading/success feedback');
    const first = responses[responses.length - 1];
    assert.equal(first.app.serverInstanceId, initial.app.serverInstanceId);
    assert.equal(first.stateSource, 'DISK');
    assert.equal(first.app.jobId, currentJob.jobId);
    assert.equal(first.app.jobType, 'owner-publish');
    assert.equal(first.app.status, 'SUCCEEDED');
    assert.equal(first.review.generatedFiles.length, 0);
    assert.equal(first.review.readiness.noActionRequired, true);
    console.log('PASS 4: completed post-publish state visible without server restart');
    requests.length = 0;
    await page.locator('#refresh').click();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    assert.deepEqual(responses[responses.length - 1], first);
    assert.equal(requests.filter(r => new URL(r.url).pathname === '/api/p1008/refresh').length, 1);
    console.log('PASS 5: second click idempotent');
    assert.equal(requests.some(r => r.url.includes('/publish/')), false);
    console.log('PASS 6: no publish triggered');
    assert.equal(requests.some(r => r.url.includes('/run/')), false);
    assert.equal(nonGet, 0);
    console.log('PASS 7: no data update or non-GET action');
    assert.deepEqual(identity(), before);
    console.log('PASS 8: all six data files byte-identical');
    fault = 'backend';
    await page.locator('#refresh').click();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    assert.match(await page.locator('#refresh-feedback').innerText(), /刷新失敗.*REFRESH_TEST_BACKEND_FAILURE/);
    assert.equal(await page.locator('#job-badge').innerText(), 'ERROR');
    console.log('PASS 9: backend failure visibly reported, button restored');
    fault = '';
    // Inject a browser-only render exception, never modify production code/state.
    await page.evaluate(() => {
      window.savedRenderEditorial = renderEditorial;
      renderEditorial = () => { throw new Error('REFRESH_TEST_RENDER_FAILURE'); };
    });
    await page.locator('#refresh').click();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    assert.match(await page.locator('#refresh-feedback').innerText(), /刷新失敗.*REFRESH_TEST_RENDER_FAILURE/);
    assert(consoleErrors.some(e => e.includes('REFRESH_TEST_RENDER_FAILURE')));
    assert.equal(pageErrors.length, 0);
    await page.evaluate(() => { renderEditorial = window.savedRenderEditorial; });
    await page.locator('#refresh').click();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    assert.match(await page.locator('#refresh-feedback').innerText(), /已刷新狀態/);
    assert.deepEqual(identity(), before);
    console.log('PASS 10: runtime exception visibly reported, recovery succeeds');
    console.log('REAL_BROWSER_CLICK_ACCEPTANCE=PASS TARGETED_BROWSER_TESTS=10/10');
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error); process.exit(1); });
