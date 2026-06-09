/* PyTxT — threading page logic.
 *
 * Wires CMD:THREAD_START / THREAD_STOP and renders the run observability (U5):
 * per-iteration RMS history (plot.js line), outcome status + next-action
 * guidance, and the last computed corrector step as HCM/VCM bar charts
 * (plot.js bars). Live loop state comes from STATE:THREAD_* PVs.
 */
(function () {
  'use strict';

  let PV_PREFIX = 'OSPREY:TEST:TXT:';
  let lastRes = null;   // last THREAD_START response, kept for resize re-render

  const els = {
    pill: document.getElementById('threadPill'),
    threadStatus: document.getElementById('threadStatus'),
    threadRunning: document.getElementById('threadRunning'),
    threadIteration: document.getElementById('threadIteration'),
    threadRms: document.getElementById('threadRms'),
    maxSteps: document.getElementById('maxSteps'),
    gain: document.getElementById('gain'),
    convRms: document.getElementById('convRms'),
    dryRun: document.getElementById('dryRun'),
    fireEachStep: document.getElementById('fireEachStep'),
    startBtn: document.getElementById('threadStartBtn'),
    stopBtn: document.getElementById('threadStopBtn'),
    msg: document.getElementById('threadMsg'),
    eventLog: document.getElementById('eventLog'),
    resultPill: document.getElementById('threadResultPill'),
    guidance: document.getElementById('threadGuidance'),
    rmsCanvas: document.getElementById('threadRmsCanvas'),
    stepHcm: document.getElementById('threadStepHcm'),
    stepVcm: document.getElementById('threadStepVcm'),
    stepMeta: document.getElementById('threadStepMeta'),
  };

  const STATUS_TONE = {
    RUNNING: 'active', CONVERGED: 'ok', DIVERGED: 'danger', FAILED: 'danger',
    STOPPED: 'warn', MAX_STEPS: 'warn', NEVER: 'idle',
  };
  const GUIDANCE = {
    CONVERGED: 'Converged — orbit RMS reached the threshold. Save the corrected trajectory as the new reference if it looks good.',
    DIVERGED: 'Diverged — RMS grew between iterations. Lower the gain, re-check the reference (R0), or verify the response matrix.',
    MAX_STEPS: 'Reached max steps without converging. Increase max steps, raise the gain a little, or set a convergence threshold.',
    STOPPED: 'Stopped by request after the current iteration. Adjust parameters and start again.',
    FAILED: 'Failed — acquisition returned no usable diff. Check BPM acquisition before retrying.',
  };

  const MAX_LOG_ENTRIES = 12;
  function logEvent(text) {
    const li = document.createElement('li');
    const t = document.createElement('time');
    t.textContent = new Date().toLocaleTimeString();
    li.appendChild(t);
    li.appendChild(document.createTextNode(text));
    els.eventLog.insertBefore(li, els.eventLog.firstChild);
    while (els.eventLog.children.length > MAX_LOG_ENTRIES) {
      els.eventLog.removeChild(els.eventLog.lastChild);
    }
  }

  function css(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function renderResult() {
    if (!lastRes) return;
    const s = lastRes.status;
    els.resultPill.dataset.tone = STATUS_TONE[s] || 'idle';
    els.resultPill.textContent = s;
    els.guidance.textContent = GUIDANCE[s] || '—';

    plot.draw(els.rmsCanvas, {
      series: [{ data: lastRes.rms_history_mm, color: css('--accent', '#4f8cff') }],
      yUnit: 'mm', xLabel: 'iteration', zeroLine: false, empty: 'no iterations',
    });
    plot.bars(els.stepHcm, { values: lastRes.step_hcm_a, color: css('--canvas-x', '#4ade80'), yUnit: 'A', xLabel: 'HCM index', empty: 'no step computed' });
    plot.bars(els.stepVcm, { values: lastRes.step_vcm_a, color: css('--canvas-dy', '#c084fc'), yUnit: 'A', xLabel: 'VCM index', empty: 'no step computed' });
    const nh = lastRes.step_hcm_a.length, nv = lastRes.step_vcm_a.length;
    els.stepMeta.textContent = (nh || nv) ? `${nh} HCM · ${nv} VCM` : '';
  }

  function subscribeAll() {
    connection.subscribe(PV_PREFIX + 'STATE:THREAD_STATUS', (m) => {
      const s = m.value || 'NEVER';
      els.threadStatus.textContent = s;
      els.pill.dataset.tone = STATUS_TONE[s] || 'idle';
      els.pill.textContent = s;
    });
    connection.subscribe(PV_PREFIX + 'STATE:THREAD_RUNNING', (m) => {
      const running = Number(m.value) === 1;
      els.threadRunning.textContent = running ? 'yes' : 'no';
      els.startBtn.disabled = running;
    });
    connection.subscribe(PV_PREFIX + 'STATE:THREAD_ITERATION', (m) => {
      els.threadIteration.textContent = m.value;
    });
    connection.subscribe(PV_PREFIX + 'RESULT:THREAD_RMS', (m) => {
      const v = Number(m.value);
      els.threadRms.textContent = Number.isFinite(v) ? v.toFixed(4) + ' mm' : '—';
    });
  }

  function buildRequest() {
    const body = {
      max_steps: parseInt(els.maxSteps.value, 10),
      gain: parseFloat(els.gain.value),
      dry_run: els.dryRun.checked,
      fire_each_step: els.fireEachStep.checked,
    };
    const conv = parseFloat(els.convRms.value);
    if (Number.isFinite(conv)) body.conv_rms_mm = conv;
    return body;
  }

  els.startBtn.addEventListener('click', async () => {
    els.msg.textContent = 'running…';
    els.startBtn.disabled = true;
    try {
      const res = await connection.command('thread_start', buildRequest());
      lastRes = res;
      renderResult();
      els.msg.textContent =
        `${res.status} after ${res.iterations} step(s), RMS ${res.final_rms_mm.toFixed(4)} mm`;
      logEvent(`thread_start → ${res.status} (${res.iterations} steps)`);
    } catch (e) {
      els.msg.textContent = `error: ${e.message}`;
      logEvent(`thread_start error: ${e.message}`);
    } finally {
      els.startBtn.disabled = false;
    }
  });

  els.stopBtn.addEventListener('click', async () => {
    try {
      await connection.command('thread_stop', {});
      els.msg.textContent = 'stop requested';
      logEvent('thread_stop requested');
    } catch (e) {
      els.msg.textContent = `error: ${e.message}`;
    }
  });

  let resizeTimer = null;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderResult, 150);
  });

  fetch('/api/v1/config')
    .then((r) => r.json())
    .then((cfg) => { PV_PREFIX = cfg.pv_prefix || PV_PREFIX; })
    .catch((e) => console.warn('Could not fetch /api/v1/config; using default prefix', e))
    .finally(subscribeAll);
})();
