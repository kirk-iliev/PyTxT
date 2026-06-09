const { test, expect } = require('@playwright/test');

// Phase 5 / U3 — manual corrector step panel (CMD:STEP_CM + compare-and-set).
// Exercised against the synthetic corrector writer (PYTXT_USE_SYNTHETIC_READER=1).

test.describe('correctors panel', () => {
  test('catalog loads and device picker populates', async ({ page }) => {
    await page.goto('/correctors.html');
    await expect(page.locator('#cmCatalog')).toContainText('96 HCM', { timeout: 3000 });
    await expect.poll(() => page.locator('#cmDevice option').count()).toBe(96);
    await expect(page.locator('#cmLimit')).toContainText('Limit:');
  });

  test('preview then apply, with the apply gated on a fresh preview', async ({ page }) => {
    await page.goto('/correctors.html');
    await expect.poll(() => page.locator('#cmDevice option').count()).toBeGreaterThan(0);

    // Apply is disabled until a preview captures the compare-and-set base.
    await expect(page.locator('#cmApplyBtn')).toBeDisabled();

    await page.locator('#cmPreviewBtn').click();
    await expect(page.locator('#cmMsg')).toContainText('previewed', { timeout: 5000 });
    await expect(page.locator('#cmResultBody tr')).toHaveCount(1);
    await expect(page.locator('#cmApplyBtn')).toBeEnabled();

    await page.locator('#cmApplyBtn').click();
    await expect(page.locator('#cmMsg')).toContainText('APPLIED', { timeout: 5000 });
    // Apply re-disables until the next preview.
    await expect(page.locator('#cmApplyBtn')).toBeDisabled();
    // Last-step PV pill reflects the apply.
    await expect(page.locator('#cmLastStatus')).toHaveText('APPLIED', { timeout: 5000 });
  });

  test('changing an input invalidates the preview', async ({ page }) => {
    await page.goto('/correctors.html');
    await expect.poll(() => page.locator('#cmDevice option').count()).toBeGreaterThan(0);
    await page.locator('#cmPreviewBtn').click();
    await expect(page.locator('#cmApplyBtn')).toBeEnabled({ timeout: 5000 });
    await page.locator('#cmDelta').fill('0.020');
    await expect(page.locator('#cmApplyBtn')).toBeDisabled();
  });
});
