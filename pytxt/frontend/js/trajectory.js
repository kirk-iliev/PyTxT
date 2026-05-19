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

    if (!data.length) return;
    // Auto-range (symmetric around 0, padded)
    let maxAbs = 0;
    for (const v of data) {
      if (Number.isFinite(v) && Math.abs(v) > maxAbs) maxAbs = Math.abs(v);
    }
    if (maxAbs === 0) maxAbs = 1;  // avoid div-by-zero
    const yScale = (h / 2 - 8) / maxAbs;

    // Plot
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let pendingMove = true;
    for (let i = 0; i < data.length; i++) {
      const v = data[i];
      if (!Number.isFinite(v)) { pendingMove = true; continue; }
      const x = data.length === 1
        ? w / 2
        : (i * (w - 20) / (data.length - 1)) + 10;
      const y = cy - v * yScale;
      if (pendingMove) { ctx.moveTo(x, y); pendingMove = false; }
      else { ctx.lineTo(x, y); }
      // Point marker (especially useful for N=1)
      ctx.fillRect(x - 1.5, y - 1.5, 3, 3);
    }
    ctx.stroke();
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
