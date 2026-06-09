const { test, expect } = require('@playwright/test');

// Phase 5 / U1 — dashboard home + diagnostics page.

test.describe('dashboard', () => {
  test('/ is the dashboard with the four state tiles', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.page-title')).toHaveText('Dashboard');
    for (const title of ['Machine / liveness', 'Last acquisition', 'Reference', 'Threading loop']) {
      await expect(page.locator(`.panel__title:has-text("${title}")`)).toHaveCount(1);
    }
  });

  test('liveness tile updates from PVs', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#heartbeat')).not.toHaveText('—', { timeout: 3000 });
    // IOC prefix comes from /api/v1/config
    await expect(page.locator('#dashPrefix')).not.toHaveText('—', { timeout: 3000 });
  });

  test('Acquire quick action drives an acquisition', async ({ page }) => {
    await page.goto('/');
    await page.locator('#dashAcquireBtn').click();
    // Meta echoes the command result, and the status pill leaves NEVER.
    await expect(page.locator('#dashAcquireMeta')).toContainText(/OK|FAIL|PARTIAL/, { timeout: 5000 });
    await expect(page.locator('#dashAcqStatus')).not.toHaveText('NEVER', { timeout: 5000 });
  });
});

test.describe('diagnostics', () => {
  test('page loads and the state snapshot populates', async ({ page }) => {
    await page.goto('/diagnostics.html');
    await expect(page.locator('.page-title')).toHaveText('Diagnostics');
    // Ping/health still works (shared app.js).
    await expect(page.locator('#heartbeat')).not.toHaveText('—', { timeout: 3000 });
    // The inspector fetches /api/v1/state on load → valid JSON containing "version".
    await expect(page.locator('#stateDump')).toContainText('"version"', { timeout: 5000 });
  });

  test('Ping button increments the ping count', async ({ page }) => {
    await page.goto('/diagnostics.html');
    await page.locator('#pingButton').click();
    await expect(page.locator('#pingCount')).not.toHaveText('—', { timeout: 3000 });
  });
});
