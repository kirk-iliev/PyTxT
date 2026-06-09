const { test, expect } = require('@playwright/test');

// Phase 5 / U6 — first-turn analysis strip (RESULT:ANALYSIS:* PVs).

test.describe('first-turn analysis', () => {
  test('strip populates from analysis PVs after an acquire', async ({ page }) => {
    await page.goto('/trajectory.html');
    await expect(page.locator('.panel__title:has-text("First-turn analysis")')).toHaveCount(1);

    await page.locator('#acquireButton').click();
    await expect(page.locator('#acquireMeta')).toContainText(/OK|PARTIAL|FAIL/, { timeout: 5000 });

    // RMS readouts leave the placeholder and carry mm units.
    await expect(page.locator('#anXRms')).toContainText('mm', { timeout: 5000 });
    await expect(page.locator('#anYRms')).toContainText('mm');
    // Transmission: "<live> / <total>" form.
    await expect(page.locator('#anLive')).toContainText('/', { timeout: 5000 });
    // Reach names a BPM (synthetic reader: all 12 live → reaches the last one).
    await expect(page.locator('#anReach')).not.toHaveText('—');
  });

  test('analysis is in the REST /state snapshot', async ({ page }) => {
    await page.request.post('/api/v1/cmd/acquire', { data: {} });
    const r = await page.request.get('/api/v1/state');
    const body = await r.json();
    expect(body.analysis).toBeTruthy();
    expect(body.analysis).toHaveProperty('x_rms_mm');
    expect(body.analysis).toHaveProperty('n_live_bpms');
    expect(body.analysis).toHaveProperty('reach_name');
  });
});
