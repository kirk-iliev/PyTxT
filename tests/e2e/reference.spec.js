const { test, expect } = require('@playwright/test');

/**
 * Phase 3 M4 e2e — reference workflow happy path (design spec §10.4).
 *
 * Runs against the synthetic reader (PYTXT_USE_SYNTHETIC_READER=1, set by
 * playwright.config.js), which varies per-BPM amplitude per acquire so the
 * post-promote diff is ~zero and the next acquire's diff is non-zero
 * somewhere. The diff assertion is "non-zero somewhere", not exact values.
 */

// Sample the canvas for any bright (non-background) pixel — same heuristic as
// trajectory.spec.js. The diff polylines use amber (#f59e0b: high R, mid G) and
// purple (#c084fc: high R+B), so "red channel bright" catches both, while the
// X/Y green/blue check still applies to the position panels.
async function canvasHasContent(page, canvasId) {
  return page.evaluate((id) => {
    const c = document.getElementById(id);
    const ctx = c.getContext('2d');
    const data = ctx.getImageData(0, 0, c.width, c.height).data;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i] > 120 || data[i + 1] > 50 || data[i + 2] > 100) return true;
    }
    return false;
  }, canvasId);
}

test.describe('PyTxT reference workflow', () => {
  test('acquire → promote → diff → save → clear → load', async ({ page }) => {
    // 1. Page loads, no reference, 2-panel layout.
    await page.goto('/trajectory.html');
    await expect(page.locator('#connectionStatus')).toHaveAttribute('data-state', 'connected', { timeout: 5000 });
    await expect(page.locator('#panelGrid')).toHaveClass(/panels-2/);
    await expect(page.locator('#refStatus')).toContainText('No reference loaded');

    // 2. Acquire → trajectory renders.
    await page.locator('#acquireButton').click();
    await expect(page.locator('#trajectoryStatus')).toContainText('OK', { timeout: 10000 });
    expect(await canvasHasContent(page, 'canvasX')).toBe(true);

    // 3. Promote current → layout switches to 4-panel; ΔX/ΔY panels drawn.
    await expect(page.locator('#promoteRefBtn')).toBeEnabled();
    await page.locator('#promoteRefBtn').click();
    await expect(page.locator('#panelGrid')).toHaveClass(/panels-4/, { timeout: 5000 });
    await expect(page.locator('#refStatus')).toContainText('promoted');
    await expect(page.locator('#canvasDX')).toBeVisible();
    // Right after promote the diff is ~zero; the panel still draws its grid +
    // Y-tick labels, so it has content.
    expect(await canvasHasContent(page, 'canvasDX')).toBe(true);

    // 4. Acquire again → ΔX/ΔY now show real (non-zero) deviation somewhere.
    await page.locator('#acquireButton').click();
    // Wait for the Δrms readout to report a non-zero X or Y.
    await expect.poll(async () => {
      const txt = await page.locator('#trajectoryDiffRms').textContent();
      const nums = (txt || '').match(/\d+\.\d+/g) || [];
      return nums.some((n) => parseFloat(n) > 0);
    }, { timeout: 10000 }).toBe(true);

    // 5. Save current… → accept the default name → success.
    await page.locator('#saveRefBtn').click();
    await expect(page.locator('#saveRefDialog')).toBeVisible();
    const savedName = await page.locator('#saveRefName').inputValue();
    expect(savedName).toMatch(/_reference_trajectory\.mat$/);
    await page.locator('#saveRefConfirm').click();
    await expect(page.locator('#refMsg')).toContainText('Saved', { timeout: 5000 });

    // 6. Clear → layout returns to 2-panel.
    await page.locator('#clearRefBtn').click();
    await expect(page.locator('#panelGrid')).toHaveClass(/panels-2/, { timeout: 5000 });
    await expect(page.locator('#refStatus')).toContainText('No reference loaded');

    // 7. Load… → pick the just-saved file → 4-panel returns, source=file.
    await page.locator('#loadRefBtn').click();
    await expect(page.locator('#loadRefDialog')).toBeVisible();
    await expect(page.locator('#refList')).toContainText(savedName, { timeout: 5000 });
    await page.locator('#refList li', { hasText: savedName }).first().click();
    await expect(page.locator('#panelGrid')).toHaveClass(/panels-4/, { timeout: 5000 });
    await expect(page.locator('#refStatus')).toContainText('file');
    expect(await canvasHasContent(page, 'canvasDY')).toBe(true);
  });
});
