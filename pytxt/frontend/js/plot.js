/* PyTxT — shared line-plot canvas renderer (Phase 5 / U2).
 *
 * A small, framework-free, DPI-aware renderer for value-vs-index line plots.
 * Built for the raw turn-by-turn viewer (100k-sample waveforms) but general:
 *   plot.draw(canvas, { series, yUnit, xLabel, zeroLine, symmetric })
 *
 * Design notes vs. the Phase-2 trajectory renderer (which stays bespoke,
 * being tooltip-coupled): this one
 *   - sizes the backing store to clientSize × devicePixelRatio (crisp on 4K),
 *   - reserves a left gutter for Y labels + a bottom strip for X labels so
 *     axis text never overlaps the trace (the bug U2 was asked to fix), and
 *   - min/max-decimates dense arrays to one vertical envelope bar per pixel
 *     column, so a 100k-sample trace renders fast and preserves spikes.
 */
(function () {
  'use strict';

  const GUTTER_L = 52;   // px reserved for Y-axis labels
  const GUTTER_B = 18;   // px reserved for X-axis labels
  const PAD_T = 10;
  const PAD_R = 10;

  function cssVar(el, name, fallback) {
    const v = getComputedStyle(el).getPropertyValue(name).trim();
    return v || fallback;
  }

  function finiteExtent(series) {
    let lo = Infinity, hi = -Infinity, n = 0;
    for (const s of series) {
      const d = s.data;
      for (let i = 0; i < d.length; i++) {
        const v = d[i];
        if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
      }
      if (d.length > n) n = d.length;
    }
    if (lo === Infinity) { lo = -1; hi = 1; }
    return { lo, hi, n };
  }

  /**
   * Decimate `data` (length n) into `cols` columns, each as {min,max} over its
   * sample window — preserves envelope/spikes. Skips NaN. Returns array of
   * {min,max} or null (column had no finite samples).
   */
  function minMaxColumns(data, cols) {
    const n = data.length;
    const out = new Array(cols);
    for (let c = 0; c < cols; c++) {
      const start = Math.floor((c * n) / cols);
      const end = Math.max(start + 1, Math.floor(((c + 1) * n) / cols));
      let lo = Infinity, hi = -Infinity;
      for (let i = start; i < end && i < n; i++) {
        const v = data[i];
        if (Number.isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
      }
      out[c] = lo === Infinity ? null : { min: lo, max: hi };
    }
    return out;
  }

  function fmtTick(v) {
    const a = Math.abs(v);
    if (a !== 0 && (a < 0.01 || a >= 1e5)) return v.toExponential(1);
    if (a >= 100) return v.toFixed(0);
    if (a >= 1) return v.toFixed(2);
    return v.toFixed(3);
  }

  function draw(canvas, opts) {
    const series = (opts.series || []).filter((s) => s && s.data && s.data.length);
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 600;
    const cssH = canvas.clientHeight || 180;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const bg = cssVar(canvas, '--canvas-bg', '#0a0a0a');
    const grid = cssVar(canvas, '--canvas-grid', '#2a2a2a');
    const muted = cssVar(canvas, '--fg-dim', '#6f757c');
    const mono = cssVar(canvas, '--monospace', 'ui-monospace, Menlo, monospace');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, cssW, cssH);

    const px0 = GUTTER_L, py0 = PAD_T;
    const pw = Math.max(1, cssW - GUTTER_L - PAD_R);
    const ph = Math.max(1, cssH - PAD_T - GUTTER_B);

    if (!series.length) {
      ctx.fillStyle = muted;
      ctx.font = `12px ${mono}`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(opts.empty || 'no data', px0 + pw / 2, py0 + ph / 2);
      return;
    }

    let { lo, hi, n } = finiteExtent(series);
    if (opts.symmetric) { const m = Math.max(Math.abs(lo), Math.abs(hi)) || 1; lo = -m; hi = m; }
    if (lo === hi) { lo -= 1; hi += 1; }
    const pad = (hi - lo) * 0.08;
    lo -= pad; hi += pad;
    const yOf = (v) => py0 + ph * (1 - (v - lo) / (hi - lo));
    const xOf = (i) => px0 + (n <= 1 ? pw / 2 : (i * pw) / (n - 1));

    // Zero line (if in range)
    if (opts.zeroLine && lo < 0 && hi > 0) {
      ctx.strokeStyle = grid; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
      ctx.beginPath(); ctx.moveTo(px0, yOf(0)); ctx.lineTo(px0 + pw, yOf(0)); ctx.stroke();
      ctx.setLineDash([]);
    }
    // Plot-area border
    ctx.strokeStyle = grid; ctx.lineWidth = 1;
    ctx.strokeRect(px0 + 0.5, py0 + 0.5, pw, ph);

    // Series — min/max envelope when dense, polyline when sparse.
    const cols = Math.max(2, Math.floor(pw));
    for (const s of series) {
      ctx.strokeStyle = s.color;
      ctx.fillStyle = s.color;
      ctx.lineWidth = 1.25;
      if (s.data.length > pw * 2) {
        const colsData = minMaxColumns(s.data, cols);
        ctx.beginPath();
        for (let c = 0; c < cols; c++) {
          const col = colsData[c];
          if (!col) continue;
          const x = px0 + (c / (cols - 1)) * pw;
          ctx.moveTo(x, yOf(col.min));
          ctx.lineTo(x, yOf(col.max));
        }
        ctx.stroke();
      } else {
        ctx.beginPath();
        let move = true;
        for (let i = 0; i < s.data.length; i++) {
          const v = s.data[i];
          if (!Number.isFinite(v)) { move = true; continue; }
          const x = xOf(i), y = yOf(v);
          if (move) { ctx.moveTo(x, y); move = false; } else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
    }

    // Axis labels (in gutters — never over the trace).
    ctx.fillStyle = muted;
    ctx.font = `10px ${mono}`;
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'right';
    for (const v of [hi, (hi + lo) / 2, lo]) {
      ctx.fillText(fmtTick(v), px0 - 6, yOf(v));
    }
    if (opts.yUnit) {
      ctx.save();
      ctx.translate(11, py0 + ph / 2); ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center';
      ctx.fillText(opts.yUnit, 0, 0);
      ctx.restore();
    }
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
    ctx.fillText('0', px0, cssH - 5);
    ctx.textAlign = 'right';
    ctx.fillText(String(n - 1), px0 + pw, cssH - 5);
    if (opts.xLabel) {
      ctx.textAlign = 'center';
      ctx.fillText(opts.xLabel, px0 + pw / 2, cssH - 5);
    }
  }

  /**
   * Vertical bar chart from a zero baseline (range symmetric around 0 so ± bars
   * read fairly). For the corrector-step plot (manual step 16). DPI-aware, same
   * gutter convention as draw().
   */
  function bars(canvas, opts) {
    const values = (opts.values || []).map((v) => (Number.isFinite(v) ? v : 0));
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 600;
    const cssH = canvas.clientHeight || 140;
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);

    const bg = cssVar(canvas, '--canvas-bg', '#0a0a0a');
    const grid = cssVar(canvas, '--canvas-grid', '#2a2a2a');
    const muted = cssVar(canvas, '--fg-dim', '#6f757c');
    const mono = cssVar(canvas, '--monospace', 'ui-monospace, Menlo, monospace');
    ctx.fillStyle = bg; ctx.fillRect(0, 0, cssW, cssH);

    const px0 = GUTTER_L, py0 = PAD_T;
    const pw = Math.max(1, cssW - GUTTER_L - PAD_R);
    const ph = Math.max(1, cssH - PAD_T - GUTTER_B);

    if (!values.length) {
      ctx.fillStyle = muted; ctx.font = `12px ${mono}`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(opts.empty || 'no step', px0 + pw / 2, py0 + ph / 2);
      return;
    }

    const m = Math.max(...values.map(Math.abs), 1e-9);
    const hi = m, lo = -m;
    const yOf = (v) => py0 + ph * (1 - (v - lo) / (hi - lo));
    const zeroY = yOf(0);

    ctx.strokeStyle = grid; ctx.lineWidth = 1;
    ctx.strokeRect(px0 + 0.5, py0 + 0.5, pw, ph);
    ctx.beginPath(); ctx.moveTo(px0, zeroY); ctx.lineTo(px0 + pw, zeroY); ctx.stroke();

    const n = values.length;
    const slot = pw / n;
    const bw = Math.max(1, Math.min(slot * 0.8, 14));
    ctx.fillStyle = opts.color || '#4f8cff';
    for (let i = 0; i < n; i++) {
      const v = values[i];
      const x = px0 + i * slot + (slot - bw) / 2;
      const y = yOf(v);
      ctx.fillRect(x, Math.min(y, zeroY), bw, Math.abs(y - zeroY) || 1);
    }

    // axis labels
    ctx.fillStyle = muted; ctx.font = `10px ${mono}`;
    ctx.textBaseline = 'middle'; ctx.textAlign = 'right';
    ctx.fillText(fmtTick(hi), px0 - 6, yOf(hi));
    ctx.fillText('0', px0 - 6, zeroY);
    ctx.fillText(fmtTick(lo), px0 - 6, yOf(lo));
    if (opts.yUnit) {
      ctx.save(); ctx.translate(11, py0 + ph / 2); ctx.rotate(-Math.PI / 2);
      ctx.textAlign = 'center'; ctx.fillText(opts.yUnit, 0, 0); ctx.restore();
    }
    ctx.textBaseline = 'alphabetic'; ctx.textAlign = 'left';
    ctx.fillText('0', px0, cssH - 5);
    ctx.textAlign = 'right'; ctx.fillText(String(n - 1), px0 + pw, cssH - 5);
    if (opts.xLabel) { ctx.textAlign = 'center'; ctx.fillText(opts.xLabel, px0 + pw / 2, cssH - 5); }
  }

  window.plot = { draw, bars };
})();
