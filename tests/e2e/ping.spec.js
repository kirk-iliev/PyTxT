const { test, expect } = require('@playwright/test');

test.describe('PyTxT ping flow', () => {
  test('clicking Ping increments ping count via full round-trip', async ({ page }) => {
    await page.goto('/diagnostics.html');

    // Wait for initial state to load
    const pingCountEl = page.locator('#pingCount');
    await expect(pingCountEl).not.toHaveText('—', { timeout: 3000 });

    const before = parseInt((await pingCountEl.textContent()) || '0', 10);

    await page.locator('#pingButton').click();

    await expect(pingCountEl).toHaveText(String(before + 1), { timeout: 2000 });

    // Last ping timestamp should now be populated
    const lastPing = await page.locator('#lastPingAt').textContent();
    expect(lastPing).not.toBe('—');
    expect(lastPing).toMatch(/\d{4}-\d{2}-\d{2}/);
  });

  test('multiple pings accumulate', async ({ page }) => {
    await page.goto('/diagnostics.html');
    const pingCountEl = page.locator('#pingCount');
    await expect(pingCountEl).not.toHaveText('—', { timeout: 3000 });

    const before = parseInt((await pingCountEl.textContent()) || '0', 10);

    for (let i = 0; i < 3; i++) {
      await page.locator('#pingButton').click();
      await page.waitForTimeout(200);
    }

    await expect(pingCountEl).toHaveText(String(before + 3), { timeout: 2000 });
  });
});
