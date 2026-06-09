const { test, expect } = require('@playwright/test');

// Phase 5 / U0 — the shared application shell + tab navigation.

const LIVE_TABS = ['Dashboard', 'Trajectory', 'Threading', 'Diagnostics'];
const DISABLED_TABS = ['Correctors', 'Injection'];

test.describe('app shell', () => {
  test('header + 6-tab nav render on every live page', async ({ page }) => {
    for (const path of ['/', '/trajectory.html', '/threading.html']) {
      await page.goto(path);
      await expect(page.locator('.app-header .app-brand__name')).toHaveText('PyTxT');
      // All six tabs present (live links + disabled placeholders).
      await expect(page.locator('.nav-tab')).toHaveCount(6);
      for (const label of LIVE_TABS) {
        await expect(page.locator(`a.nav-tab:has-text("${label}")`)).toHaveCount(1);
      }
      for (const label of DISABLED_TABS) {
        await expect(page.locator(`span.nav-tab.is-disabled:has-text("${label}")`)).toHaveCount(1);
      }
    }
  });

  test('active tab reflects the current page', async ({ page }) => {
    const cases = [
      { path: '/', label: 'Dashboard' },
      { path: '/trajectory.html', label: 'Trajectory' },
      { path: '/threading.html', label: 'Threading' },
    ];
    for (const { path, label } of cases) {
      await page.goto(path);
      const active = page.locator('.nav-tab.is-active');
      await expect(active).toHaveCount(1);
      await expect(active).toHaveText(label);
      await expect(active).toHaveAttribute('aria-current', 'page');
    }
  });

  test('disabled tabs are not navigable', async ({ page }) => {
    await page.goto('/');
    const correctors = page.locator('.nav-tab.is-disabled:has-text("Correctors")');
    await expect(correctors).toHaveAttribute('aria-disabled', 'true');
    // Rendered as <span>, so it carries no href to navigate to.
    await expect(correctors).toHaveJSProperty('tagName', 'SPAN');
  });

  test('clicking a live tab navigates', async ({ page }) => {
    await page.goto('/');
    await page.locator('a.nav-tab:has-text("Trajectory")').click();
    await expect(page).toHaveURL(/\/trajectory\.html$/);
    await expect(page.locator('.page-title')).toHaveText('Trajectory');
  });

  test('no capability regression — key page content still present', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('#heartbeat')).toBeVisible();
    await expect(page.locator('#connectionStatus')).toBeVisible();

    await page.goto('/trajectory.html');
    await expect(page.locator('#canvasX')).toBeVisible();
    await expect(page.locator('#acquireButton')).toBeVisible();

    await page.goto('/threading.html');
    await expect(page.locator('#threadStatus')).toBeVisible();
    await expect(page.locator('#threadStartBtn')).toBeVisible();
  });
});
