const { test, expect } = require('@playwright/test');

// Phase 5 / U2 — raw turn-by-turn viewer on the Trajectory page.

test.describe('raw TBT viewer', () => {
  test('panel renders and the BPM selector populates', async ({ page }) => {
    await page.goto('/trajectory.html');
    await expect(page.locator('.panel__title:has-text("Raw turn-by-turn signal")')).toHaveCount(1);
    // Selector filled from /api/v1/state bpm_prefixes. (<option>s aren't
    // "visible" to Playwright in a closed <select>, so poll the count.)
    await expect.poll(
      () => page.locator('#tbtBpmSelect option').count(),
      { timeout: 3000 }
    ).toBeGreaterThan(0);
    // Three trace canvases present.
    for (const id of ['#tbtSum', '#tbtX', '#tbtY']) {
      await expect(page.locator(id)).toBeVisible();
    }
  });

  test('selecting a BPM after acquire renders its traces', async ({ page }) => {
    await page.goto('/trajectory.html');
    // Drive an acquisition so raw waveforms exist.
    await page.locator('#acquireButton').click();
    await expect(page.locator('#acquireMeta')).toContainText(/OK|PARTIAL|FAIL/, { timeout: 5000 });
    // Re-fetch the current BPM's raw waveforms.
    await page.locator('#tbtRefreshBtn').click();
    await expect(page.locator('#tbtMeta')).toContainText('samples', { timeout: 5000 });
  });

  test('missing raw data is reported, not a hard error', async ({ page }) => {
    // Fresh page load before any acquire in this context: the viewer auto-loads
    // the first BPM and should report no-data gracefully (or samples if a prior
    // test on the shared server already acquired). Either way: never "error:".
    await page.goto('/trajectory.html');
    await expect(page.locator('#tbtMeta')).not.toHaveText('', { timeout: 5000 });
    await expect(page.locator('#tbtMeta')).not.toContainText('error:');
  });
});
