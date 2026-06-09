/* PyTxT — raw turn-by-turn viewer (Phase 5 / U2).
 *
 * Manual step 5: the raw Sum / Horizontal / Vertical BPM signal over the full
 * ~100k-sample acquisition window, for one selectable BPM. Bulk waveforms come
 * over REST (GET /api/v1/result/bpm/raw) — never PVs (CLAUDE.md §3) — and are
 * rendered with the shared DPI-aware plot.js (min/max-decimated).
 */
(function () {
  'use strict';

  const sel = document.getElementById('tbtBpmSelect');
  const refreshBtn = document.getElementById('tbtRefreshBtn');
  const meta = document.getElementById('tbtMeta');
  const canvases = {
    sum: document.getElementById('tbtSum'),
    x: document.getElementById('tbtX'),
    y: document.getElementById('tbtY'),
  };

  // Last-rendered waveforms, kept so we can re-draw on resize without re-fetch.
  let last = null;  // { sum:[], x:[], y:[] } in display units

  function css(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function renderAll() {
    if (!last) {
      for (const c of Object.values(canvases)) plot.draw(c, { series: [], empty: 'no data — run Acquire' });
      return;
    }
    plot.draw(canvases.sum, {
      series: [{ data: last.sum, color: css('--accent', '#4f8cff') }],
      yUnit: 'AU', xLabel: 'sample', zeroLine: false,
    });
    plot.draw(canvases.x, {
      series: [{ data: last.x, color: css('--canvas-x', '#4ade80') }],
      yUnit: 'mm', xLabel: 'sample', zeroLine: true, symmetric: true,
    });
    plot.draw(canvases.y, {
      series: [{ data: last.y, color: css('--canvas-y', '#60a5fa') }],
      yUnit: 'mm', xLabel: 'sample', zeroLine: true, symmetric: true,
    });
  }

  async function loadBpm(bpm) {
    if (!bpm) return;
    meta.textContent = 'loading…';
    try {
      const r = await fetch(`/api/v1/result/bpm/raw?bpm=${encodeURIComponent(bpm)}`);
      if (r.status === 404) {
        // 404 = BPM has no stored waveform yet (no acquire) or was in the
        // failed-set on the last acquire.
        last = null; renderAll();
        meta.textContent = `no raw data for ${bpm} yet — run Acquire`;
        return;
      }
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      last = {
        sum: d.sum_au,
        x: d.x_nm.map((v) => v / 1e6),   // nm → mm
        y: d.y_nm.map((v) => v / 1e6),
      };
      renderAll();
      const n = d.sum_au.length;
      meta.textContent = `${bpm} · ${n.toLocaleString()} samples${d.read_timestamp ? ' · ' + new Date(d.read_timestamp).toLocaleTimeString([], { hour12: false }) : ''}`;
    } catch (e) {
      last = null; renderAll();
      meta.textContent = `error: ${e.message}`;
    }
  }

  async function populateSelector() {
    try {
      const state = await fetch('/api/v1/state').then((r) => r.json());
      const prefixes = state.bpm_prefixes || [];
      sel.innerHTML = '';
      for (const p of prefixes) {
        const opt = document.createElement('option');
        opt.value = p; opt.textContent = p;
        sel.appendChild(opt);
      }
      if (prefixes.length) loadBpm(sel.value);
      else { meta.textContent = 'no BPMs configured'; renderAll(); }
    } catch (e) {
      meta.textContent = `error loading BPM list: ${e.message}`;
      renderAll();
    }
  }

  sel.addEventListener('change', () => loadBpm(sel.value));
  refreshBtn.addEventListener('click', () => loadBpm(sel.value));

  // Re-render (re-fit to new canvas size) on resize; debounced.
  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderAll, 150);
  });

  renderAll();          // initial empty state
  populateSelector();   // then fill + load first BPM
})();
