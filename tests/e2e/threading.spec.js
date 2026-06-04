const { test, expect } = require('@playwright/test');

test.describe('PyTxT threading page', () => {
  test('panel loads and subscribes to live STATE:THREAD_* PVs', async ({ page }) => {
    await page.goto('/threading.html');

    // Status comes from the live IOC PV (STATE:THREAD_STATUS), proving the WS
    // subscription is wired. Before any run it reads NEVER.
    const status = page.locator('#threadStatus');
    await expect(status).not.toHaveText('—', { timeout: 4000 });
    await expect(status).toHaveText('NEVER');

    await expect(page.locator('#threadRunning')).toHaveText('no');
    await expect(page.locator('#threadStartBtn')).toBeVisible();
    await expect(page.locator('#dryRun')).toBeChecked();
  });

  test('Start surfaces the backend response (round-trip)', async ({ page }) => {
    await page.goto('/threading.html');
    await expect(page.locator('#threadStatus')).toHaveText('NEVER', { timeout: 4000 });

    await page.locator('#threadStartBtn').click();

    // The dev app runs with the synthetic reader and no response matrix /
    // reference loaded, so thread_start returns an error — the UI shows it.
    // Either way the message updates from empty, proving the full POST round-trip.
    const msg = page.locator('#threadMsg');
    await expect(msg).not.toHaveText('', { timeout: 4000 });
    await expect(msg).toContainText(/error|CONVERGED|MAX_STEPS|STOPPED|DIVERGED/);
  });

  test('Stop requests a stop via the command endpoint', async ({ page }) => {
    await page.goto('/threading.html');
    await expect(page.locator('#threadStatus')).toHaveText('NEVER', { timeout: 4000 });

    await page.locator('#threadStopBtn').click();
    await expect(page.locator('#threadMsg')).toHaveText('stop requested', { timeout: 3000 });
  });

  test('nav links to threading page', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.app-nav a[href="/threading.html"]')).toBeVisible();
  });
});
