// Read-only acceptance: blocks every non-GET request and every external host.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');

(async () => {
  const port = Number(process.argv[2] || 8769);
  const base = `http://127.0.0.1:${port}`;
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const context = await browser.newContext();
    await context.route('**/*', route => {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() !== 'GET' || url.origin !== base) return route.abort();
      return route.continue();
    });
    const page = await context.newPage();
    const launcher = await page.goto(`${base}/launcher.html?stay=1`);
    assert.equal(launcher.status(), 200);
    await page.waitForFunction(() => document.getElementById('readiness-score').textContent === '98%');
    const visible = await page.locator('#review-panel').innerText();
    assert.match(visible, /台股例行休市/);
    assert.match(visible, /NOT_APPLICABLE_MARKET_CLOSED/);
    assert.doesNotMatch(visible, /Candidate inspection failed|Trade-date publish plan failed|Saturday\/Sunday/);
    assert.equal(await page.locator('#readiness-badge').innerText(), 'PUBLISH READY');
    assert.equal(await page.locator('#candidate-count').innerText(), '3');
    assert.equal(await page.locator('#publish-badge').innerText(), '可正式發布');
    // No Owner approval is supplied: a ready review is not an executed publish.
    assert.equal(await page.locator('#owner-publish').isDisabled(), true);
    const review = await page.evaluate(async () => (await fetch('/api/p1008/review-package?date=2026-10-04')).json());
    assert.equal(review.readiness.twseRequirement.marketState, 'TWSE_NON_TRADING_DAY');
    assert.equal(review.readiness.twseRequirement.dailyPriceRequirement, 'NOT_APPLICABLE_MARKET_CLOSED');
    assert.deepEqual(review.readiness.blockers, []);
    assert.equal(review.launcherGate.code, 'OWNER_REVIEW_REQUIRED');
    assert.equal(review.launcherGate.canEnterNewUi, false);
    assert.equal(review.eventReview.ownerAckRequired, true);
    const dashboard = await page.goto(`${base}/ui/P1008_WARROOM_COMMAND_CENTER_v24.html`);
    assert.equal(dashboard.status(), 200);
    const status = await page.evaluate(async () => {
      const response = await fetch('/api/p1008/status');
      return { code: response.status, state: await response.json() };
    });
    assert.equal(status.code, 200);
    assert.equal(status.state.reviewPackage.readiness.score, 98);
    console.log(JSON.stringify({ port, launcher: 200, dashboard: 200, status: 200, review: 200,
      readiness: review.readiness.score, activeFormalBlockers: review.readiness.blockers,
      launcherGate: review.launcherGate.code, ownerAckRequired: review.eventReview.ownerAckRequired,
      formalPublishAllowed: review.formalPublishAllowed, publishExecuted: false,
      visibleNonTradingSemantics: 'PASS' }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
