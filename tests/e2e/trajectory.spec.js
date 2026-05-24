const { test, expect } = require('@playwright/test');

test.describe('PyTxT trajectory page', () => {
  test('acquire → render → hover tooltip flow', async ({ page }) => {
    await page.goto('/trajectory.html');

    // Step 1: page loaded and WS connected
    const connStatus = page.locator('#connectionStatus');
    await expect(connStatus).toHaveAttribute('data-state', 'connected', { timeout: 5000 });

    // Step 2: click Acquire, wait for OK status
    await page.locator('#acquireButton').click();
    await expect(page.locator('#trajectoryStatus')).toContainText('OK', { timeout: 10000 });

    // Step 3: confirm both canvases drew something (non-zero pixel content)
    for (const id of ['canvasX', 'canvasY']) {
      const hasContent = await page.evaluate((canvasId) => {
        const c = document.getElementById(canvasId);
        const ctx = c.getContext('2d');
        const data = ctx.getImageData(0, 0, c.width, c.height).data;
        // Skip the dark background (RGB ~10/10/13 ≈ 0a0a0a). Look for any
        // pixel whose green channel is > 50 (polyline is bright green
        // #4ade80) or whose blue channel is > 100 (polyline is bright blue
        // #60a5fa). Tick labels at #888 also count.
        for (let i = 0; i < data.length; i += 4) {
          if (data[i + 1] > 50 || data[i + 2] > 100) return true;
        }
        return false;
      }, id);
      expect(hasContent, `${id} should have rendered pixel content`).toBe(true);
    }

    // Step 4: hover over canvasX centre, expect tooltip to show "SRxx"
    const canvasX = page.locator('#canvasX');
    const box = await canvasX.boundingBox();
    expect(box).not.toBeNull();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);

    const tooltip = page.locator('#trajectoryTooltip');
    await expect(tooltip).toBeVisible({ timeout: 2000 });
    const txt = await tooltip.textContent();
    expect(txt).toMatch(/SR\d{2}/);
  });
});
