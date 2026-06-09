const { test, expect } = require('@playwright/test');

// Phase 5 / U4 — injection control (CMD:INJECT_ONESHOT + gun-fire guard).
// Exercised against the synthetic injection trigger (PYTXT_USE_SYNTHETIC_READER=1).

test.describe('injection panel', () => {
  test('safe shot (inhibit=1) fires and updates the last-shot pill', async ({ page }) => {
    await page.goto('/injection.html');
    await expect(page.locator('#injFireBtn')).toBeEnabled();
    await expect(page.locator('#injFireBtn')).toContainText('bumps only');
    await page.locator('#injFireBtn').click();
    await expect(page.locator('#injMsg')).toContainText('FIRED', { timeout: 5000 });
    await expect(page.locator('#injLastStatus')).toHaveText('FIRED', { timeout: 5000 });
  });

  test('gun fire is gated behind the explicit allow opt-in', async ({ page }) => {
    await page.goto('/injection.html');
    // Switch to real gun fire → panel goes danger, FIRE disabled until opt-in.
    await page.locator('#injInhibit').selectOption('0');
    await expect(page.locator('#injPanel')).toHaveClass(/is-danger/);
    await expect(page.locator('#injGunWarn')).toBeVisible();
    await expect(page.locator('#injFireBtn')).toBeDisabled();
    await expect(page.locator('#injFireBtn')).toContainText('FIRE GUN');

    // Opt in → enabled; fire → FIRED with inhibit=0 echoed.
    await page.locator('#injAllow').check();
    await expect(page.locator('#injFireBtn')).toBeEnabled();
    await page.locator('#injFireBtn').click();
    await expect(page.locator('#injMsg')).toContainText('FIRED', { timeout: 5000 });
    await expect(page.locator('#injLastInhibit')).toContainText('inhibit=0', { timeout: 5000 });
  });

  test('switching back to inhibit clears the danger state', async ({ page }) => {
    await page.goto('/injection.html');
    await page.locator('#injInhibit').selectOption('0');
    await expect(page.locator('#injPanel')).toHaveClass(/is-danger/);
    await page.locator('#injInhibit').selectOption('1');
    await expect(page.locator('#injPanel')).not.toHaveClass(/is-danger/);
    await expect(page.locator('#injFireBtn')).toBeEnabled();
  });
});
