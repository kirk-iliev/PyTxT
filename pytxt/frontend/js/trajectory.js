/* PyTxT trajectory page — phase 2 read-path UI.
 *
 * Subscribes to RESULT:BPM:{X,Y}_FIRST_TURN, INJECTION_TURN, NAMES, and
 * STATE:LAST_ACQUIRE_{STATUS, OK_COUNT, FAIL_COUNT, TIMESTAMP}. Renders
 * stacked X/Y polylines on Canvas. Ignores NaN entries (drawn as gaps).
 *
 * Phase 2 M1: data is length-1, so the "polyline" is one point per panel.
 * Same code handles length-N for M2; no changes needed beyond data flowing.
 */
(function () {
  'use strict';

  const statusEl = document.getElementById('connectionStatus');
  const statusLabelEl = document.getElementById('connectionStatusLabel');
  const trajectoryStatusEl = document.getElementById('trajectoryStatus');
  const trajectoryCountsEl = document.getElementById('trajectoryCounts');
  const acquireButton = document.getElementById('acquireButton');
  const acquireMetaEl = document.getElementById('acquireMeta');
  const canvasX = document.getElementById('canvasX');
  const canvasY = document.getElementById('canvasY');

  const state = {
    prefix: 'OSPREY:TEST:TXT:',  // overridden by /api/v1/config
    x: [], y: [], injectionTurn: [], names: [],
    status: 'NEVER', okCount: 0, failCount: 0, timestamp: '',
  };

  function statusName(code) {
    return ['NEVER', 'ACQUIRING', 'OK', 'PARTIAL', 'FAILED'][code] || 'UNKNOWN';
  }

  function trimTrailingNonFinite(data) {
    // The IOC pads waveform PVs to a fixed max length (128) with NaN. Plot
    // only the live prefix so the polyline spans the full canvas width.
    let end = data.length;
    while (end > 0 && !Number.isFinite(data[end - 1])) end--;
    return end === data.length ? data : data.slice(0, end);
  }

  /**
   * Group consecutive BPM names by ALS sector. Returns an array of
   * { label, start, end } where label is e.g. "SR01" and start/end are
   * inclusive indices into `names`. Names not matching /^SR\d{2}/ are
   * grouped under label "?".
   */
  function sectorGroups(names) {
    const groups = [];
    let current = null;
    for (let i = 0; i < names.length; i++) {
      const m = /^SR\d{2}/.exec(names[i] || '');
      const label = m ? m[0] : '?';
      if (!current || current.label !== label) {
        if (current) groups.push(current);
        current = { label, start: i, end: i };
      } else {
        current.end = i;
      }
    }
    if (current) groups.push(current);
    return groups;
  }

  function render(canvas, data, color) {
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    // Background
    ctx.fillStyle = getComputedStyle(canvas).getPropertyValue('--canvas-bg').trim() || '#0a0a0a';
    ctx.fillRect(0, 0, w, h);
    // Zero line
    const cy = h / 2;
    ctx.strokeStyle = getComputedStyle(canvas).getPropertyValue('--canvas-grid').trim() || '#333';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(w, cy); ctx.stroke();
    ctx.setLineDash([]);

    data = trimTrailingNonFinite(data);
    if (!data.length) return;
    // Auto-range (symmetric around 0, padded)
    let maxAbs = 0;
    for (const v of data) {
      if (Number.isFinite(v) && Math.abs(v) > maxAbs) maxAbs = Math.abs(v);
    }
    if (maxAbs === 0) maxAbs = 1;  // avoid div-by-zero
    // Reserve 24 px at the bottom for sector labels; polyline + Y-ticks
    // share the upper area. cy stays at h/2 so the dashed zero line and
    // both canvases' vertical alignment are unchanged.
    const labelBandH = 24;
    const yScale = (Math.min(cy - 8, h - cy - labelBandH - 4)) / maxAbs;

    function xFor(i) {
      return data.length === 1 ? w / 2 : (i * (w - 20) / (data.length - 1)) + 10;
    }

    // Connecting polyline (interior NaN entries break the line into segments)
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let pendingMove = true;
    for (let i = 0; i < data.length; i++) {
      const v = data[i];
      if (!Number.isFinite(v)) { pendingMove = true; continue; }
      const x = xFor(i), y = cy - v * yScale;
      if (pendingMove) { ctx.moveTo(x, y); pendingMove = false; }
      else { ctx.lineTo(x, y); }
    }
    ctx.stroke();

    // Per-BPM dot overlay — separate pass so the line doesn't paint over
    // the dots. Filled disc, radius 2.5, gives a visible "beaded line"
    // even at 107 points across ~660px (~6 px spacing).
    ctx.fillStyle = color;
    for (let i = 0; i < data.length; i++) {
      const v = data[i];
      if (!Number.isFinite(v)) continue;
      const x = xFor(i), y = cy - v * yScale;
      ctx.beginPath();
      ctx.arc(x, y, 2.5, 0, Math.PI * 2);
      ctx.fill();
    }

    // Sector ticks: faint vertical line + label below the plot area.
    const groups = sectorGroups(state.names.slice(0, data.length));
    if (groups.length > 0) {
      ctx.strokeStyle = getComputedStyle(canvas).getPropertyValue('--canvas-grid').trim() || '#2a2a2a';
      ctx.lineWidth = 1;
      ctx.fillStyle = '#888';
      ctx.font = '10px ' + (getComputedStyle(canvas).getPropertyValue('--monospace').trim() || 'ui-monospace, Menlo, monospace');
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      const labelY = h - 18;
      const tickTop = h - labelBandH;
      const tickBot = h - labelBandH + 6;
      for (const g of groups) {
        const xStart = xFor(g.start);
        const xEnd = xFor(g.end);
        // Tick at the start boundary
        ctx.beginPath();
        ctx.moveTo(xStart, tickTop);
        ctx.lineTo(xStart, tickBot);
        ctx.stroke();
        // Label centered between start and end
        const xMid = (xStart + xEnd) / 2;
        ctx.fillText(g.label, xMid, labelY);
      }
    }

    // Y-axis numeric ticks: +maxAbs / 0 / -maxAbs, two decimals, mm on top.
    ctx.fillStyle = '#888';
    ctx.font = '10px ' + (getComputedStyle(canvas).getPropertyValue('--monospace').trim() || 'ui-monospace, Menlo, monospace');
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'left';
    const fmtTick = (v, withUnit) => {
      const abs = Math.abs(v).toFixed(2);
      if (v === 0) return '0.00';
      const sign = v > 0 ? '+' : '−';  // unicode minus for visual width parity
      return sign + abs + (withUnit ? ' mm' : '');
    };
    const tickValues = [maxAbs, 0, -maxAbs];
    const tickYs = [8, cy, h - 8];
    for (let k = 0; k < 3; k++) {
      const label = fmtTick(tickValues[k], k === 0);
      ctx.fillText(label, 4, tickYs[k]);
    }
  }

  function redraw() {
    render(canvasX, state.x, getComputedStyle(canvasX).getPropertyValue('--canvas-x').trim() || '#4ade80');
    render(canvasY, state.y, getComputedStyle(canvasY).getPropertyValue('--canvas-y').trim() || '#60a5fa');

    trajectoryStatusEl.textContent = `Status: ${state.status} · turn ${
      Number.isFinite(state.medianTurn) ? state.medianTurn : '—'}`;
    trajectoryCountsEl.textContent =
      `${state.okCount} OK · ${state.failCount} FAIL${state.timestamp ? ' · ' + state.timestamp : ''}`;
  }

  function pv(name) { return state.prefix + name; }

  async function bootstrap() {
    try {
      const cfg = await fetch('/api/v1/config').then(r => r.json());
      state.prefix = cfg.pv_prefix;
    } catch (e) {
      console.warn('Could not fetch /api/v1/config; using default prefix', e);
    }

    connection.onStatusChange((s) => {
      statusEl.dataset.state = s;
      statusLabelEl.textContent = s === 'connected' ? 'connected' : s;
    });

    connection.subscribe(pv('RESULT:BPM:X_FIRST_TURN'), (msg) => {
      state.x = Array.isArray(msg.value) ? msg.value : [msg.value];
      redraw();
    });
    connection.subscribe(pv('RESULT:BPM:Y_FIRST_TURN'), (msg) => {
      state.y = Array.isArray(msg.value) ? msg.value : [msg.value];
      redraw();
    });
    connection.subscribe(pv('RESULT:BPM:INJECTION_TURN'), (msg) => {
      const arr = Array.isArray(msg.value) ? msg.value : [msg.value];
      const valid = arr.filter(v => v >= 0);
      state.medianTurn = valid.length
        ? valid.slice().sort((a, b) => a - b)[Math.floor(valid.length / 2)]
        : null;
      redraw();
    });
    connection.subscribe(pv('RESULT:BPM:NAMES'), (msg) => {
      state.names = Array.isArray(msg.value) ? msg.value : [msg.value];
    });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_STATUS'), (msg) => {
      state.status = statusName(msg.value);
      redraw();
    });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_OK_COUNT'), (msg) => {
      state.okCount = msg.value; redraw();
    });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_FAIL_COUNT'), (msg) => {
      state.failCount = msg.value; redraw();
    });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_TIMESTAMP'), (msg) => {
      state.timestamp = msg.value || ''; redraw();
    });

    acquireButton.addEventListener('click', async () => {
      acquireButton.disabled = true;
      acquireMetaEl.textContent = 'acquiring…';
      try {
        const r = await connection.command('acquire', {});
        acquireMetaEl.textContent = `${r.status} (${r.ok_count} OK · ${r.fail_count} FAIL)`;
      } catch (e) {
        acquireMetaEl.textContent = `error: ${e.message}`;
      } finally {
        acquireButton.disabled = false;
      }
    });
  }

  bootstrap();
})();
