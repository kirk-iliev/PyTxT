/* PyTxT diagnostics page (Phase 5 / U1).
 *
 * Adds a raw GET /api/v1/state inspector on top of the health/ping panel
 * (which is driven by the shared app.js). Read-only.
 */
(function () {
  'use strict';

  const dump = document.getElementById('stateDump');
  const btn = document.getElementById('stateRefreshBtn');

  async function refresh() {
    btn.disabled = true;
    dump.textContent = 'fetching…';
    try {
      const r = await fetch('/api/v1/state');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = await r.json();
      dump.textContent = JSON.stringify(json, null, 2);
    } catch (e) {
      dump.textContent = `error: ${e.message}`;
    } finally {
      btn.disabled = false;
    }
  }

  btn.addEventListener('click', refresh);
  refresh();  // populate on load
})();
