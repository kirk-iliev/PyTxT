const { test, expect } = require('@playwright/test');

test.describe('PyTxT smoke', () => {
  test('page loads and heartbeat updates within 3 seconds', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle('PyTxT');

    const heartbeatEl = page.locator('#heartbeat');
    // Initial render shows "—"; wait for the WS subscription to deliver a number
    await expect(heartbeatEl).not.toHaveText('—', { timeout: 3000 });

    const text = await heartbeatEl.textContent();
    const value = parseInt(text || '0', 10);
    expect(value).toBeGreaterThan(0);
  });

  test('connection status indicator turns green when WS connects', async ({ page }) => {
    await page.goto('/');
    const status = page.locator('#connectionStatus');
    await expect(status).toHaveAttribute('data-state', 'connected', { timeout: 3000 });
  });
});
