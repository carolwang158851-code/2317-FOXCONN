// Real browser acceptance against the disposable current-data snapshot only.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const http = require('node:http');
const fetch = url => new Promise((resolve, reject) => {
  http.get(url, response => {
    let body = '';
    response.setEncoding('utf8');
    response.on('data', chunk => { body += chunk; });
    response.on('end', () => resolve({ status: response.statusCode, json: async () => JSON.parse(body) }));
    response.on('error', reject);
  }).on('error', reject);
});

(async () => {
  const base = 'http://127.0.0.1:8768';
  const production = 'http://127.0.0.1:8767';
  for (const route of ['/index_p1008_v7.html', '/api/p1008/status', '/api/p1008/review-package']) {
    assert.equal((await fetch(base + route)).status, 200);
    assert.equal((await fetch(production + route)).status, 200);
  }
  const state = await (await fetch(base + '/api/p1008/scoring-state')).json();
  const status = await (await fetch(base + '/api/p1008/status')).json();
  assert.deepEqual(status.scoringState, state);
  assert.equal(state.current_period, '2026Q2');
  assert.equal(state.formal_score, null);
  assert.equal(state.formal_scoring_coverage.eligible_count, 0);
  assert.equal(state.data_coverage.research_model_count, 2);
  assert.equal(state.ic_readiness.score_count, 0);
  assert.equal(state.research_kpi_values.historical_quality.value, 78);
  assert.equal(state.research_kpi_values.cloud_networking_share_pct, 51);
  assert.equal(state.research_kpi_values.ai_specific_share_pct, null);
  assert.equal(state.decision_actionable, false);
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
    page.on('pageerror', error => errors.push(error.message));
    // Test only local assets; no external AI, search or remote asset requests.
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      return url.hostname === '127.0.0.1' ? route.continue() : route.abort();
    });
    await page.goto(base + '/index_p1008_v7.html');
    await page.waitForFunction(() => window.__p1008ScoringState?.current_period === '2026Q2');
    assert.deepEqual(await page.evaluate(() => window.__p1008ScoringState), state);
    // The observation-centre panel is tabbed; open it before checking rendered text.
    const controls = await page.getByRole('button').allTextContents();
    const observation = controls.find(text => text.includes('觀察中心'));
    if (observation) await page.getByRole('button', { name: observation, exact: true }).click();
    await page.getByText('當期研究模型資料覆蓋：', { exact: false }).first().waitFor();
    let text = await page.locator('body').innerText();
    assert.ok(text.includes('正式評分資格'));
    assert.ok(text.includes('歷史品質研究值：78（2026Q1'));
    assert.ok(text.includes('未啟用（不套權重）'));
    assert.ok(!text.includes('78 × 0.35'));
    assert.ok(!text.includes('正式可評分'));
    assert.ok(text.includes('數值映射與正規化'));
    await page.goto(base + '/ui/P1008_WARROOM_COMMAND_CENTER_v24.html');
    await page.waitForFunction(() => window.__p1008DynamicState?.scoringState?.current_period === '2026Q2');
    assert.deepEqual(await page.evaluate(() => window.__p1008ScoringState), state);
    text = await page.locator('body').innerText();
    assert.ok(text.includes('未形成正式評等'));
    assert.ok(!text.includes('HOLD / 觀察'));
    assert.ok(text.includes('當期研究模型資料覆蓋：2 / 5'));
    assert.ok(text.includes('正式 IC 分數：0 / 6'));
    assert.ok(text.includes('Cloud & Networking 51%'));
    assert.ok(text.includes('數值映射與正規化'));
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
  assert.equal((await fetch(production + '/index_p1008_v7.html')).status, 200);
  console.log('CANDIDATE_RUNTIME_8768=PASS; rendered legacy/new UI + status/review=200; identical scoring state; PRODUCTION_8767=200');
})().catch(error => { console.error(error); process.exitCode = 1; });
