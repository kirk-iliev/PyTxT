const { test, expect } = require('@playwright/test');

test.describe('PyTxT threading page', () => {
  test('panel loads and subscribes to live STATE:THREAD_* PVs', async ({ page }) => {
    await page.goto('/threading.html');
    // Status comes from the live IOC PV — proves the WS subscription is wired.
    // (Value may be NEVER or a terminal status if a prior run touched the
    // shared dev server; we only assert it left the placeholder.)
    await expect(page.locator('#threadStatus')).not.toHaveText('—', { timeout: 4000 });
    await expect(page.locator('#threadStartBtn')).toBeVisible();
    await expect(page.locator('#dryRun')).toBeChecked();
  });

  test('a dry run renders outcome, RMS history, and the corrector-step bars (U5)', async ({ page }) => {
    // Set up R0 so the loop has a reference (acquire + promote via REST).
    await page.request.post('/api/v1/cmd/acquire', { data: {} });
    await page.request.post('/api/v1/cmd/promote_ref', { data: {} });

    await page.goto('/threading.html');
    await page.locator('#maxSteps').fill('8');
    await page.locator('#threadStartBtn').click();

    // Outcome pill leaves the placeholder and shows a terminal status.
    await expect(page.locator('#threadResultPill')).not.toHaveText('no run yet', { timeout: 8000 });
    await expect(page.locator('#threadResultPill'))
      .toContainText(/CONVERGED|DIVERGED|MAX_STEPS|STOPPED|FAILED/);
    // The corrector-step bars got data (HCM count in the meta).
    await expect(page.locator('#threadStepMeta')).toContainText('HCM', { timeout: 8000 });
    // Status message round-trips the response.
    await expect(page.locator('#threadMsg')).toContainText('RMS');
  });

  test('Stop requests a stop via the command endpoint', async ({ page }) => {
    await page.goto('/threading.html');
    await page.locator('#threadStopBtn').click();
    await expect(page.locator('#threadMsg')).toHaveText('stop requested', { timeout: 3000 });
  });

  test('nav links to threading page', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app-nav a[href="/threading.html"]')).toBeVisible();
  });
});
