/* PyTxT dashboard (Phase 5 / U1).
 *
 * The operator home: at-a-glance machine, acquisition, reference, and
 * threading state, fully PV-driven (no polling). Δrms and reference
 * coverage are computed client-side from the diff waveforms + names,
 * mirroring trajectory.js, so the dashboard needs no REST poll.
 */
(function () {
  'use strict';

  let PV_PREFIX = 'OSPREY:TEST:TXT:';

  const els = {
    heartbeat: document.getElementById('heartbeat'),       // id kept for smoke spec
    uptime: document.getElementById('dashUptime'),
    version: document.getElementById('dashVersion'),
    prefix: document.getElementById('dashPrefix'),

    acqStatus: document.getElementById('dashAcqStatus'),
    acqBpms: document.getElementById('dashAcqBpms'),
    injTurn: document.getElementById('dashInjTurn'),
    acqWhen: document.getElementById('dashAcqWhen'),
    acqFailed: document.getElementById('dashAcqFailed'),

    refStatus: document.getElementById('dashRefStatus'),
    refName: document.getElementById('dashRefName'),
    refSource: document.getElementById('dashRefSource'),
    refRms: document.getElementById('dashRefRms'),
    refCoverage: document.getElementById('dashRefCoverage'),

    threadStatus: document.getElementById('dashThreadStatus'),
    threadIter: document.getElementById('dashThreadIter'),
    threadRms: document.getElementById('dashThreadRms'),

    acquireBtn: document.getElementById('dashAcquireBtn'),
    acquireMeta: document.getElementById('dashAcquireMeta'),
  };

  // --- shared state for client-computed values ---
  const st = {
    dx: [], dy: [], names: [], refLoaded: false,
  };

  // --- formatters ---
  function fmtUptime(s) {
    const sec = Math.floor(s);
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const r = sec % 60;
    return `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
  }
  function fmtTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour12: false });
  }
  function acquireStatusName(code) {
    return ['NEVER', 'ACQUIRING', 'OK', 'PARTIAL', 'FAILED'][code] || 'UNKNOWN';
  }
  function rms(data) {
    let sum = 0, n = 0;
    for (const v of data) { if (Number.isFinite(v)) { sum += v * v; n++; } }
    return n ? Math.sqrt(sum / n) : NaN;
  }
  function fmtMm(v) { return Number.isFinite(v) ? v.toFixed(2) : '—'; }

  // --- pill helper: set tone + text on a .state-pill ---
  function pill(el, tone, text) {
    if (!el) return;
    el.dataset.tone = tone;
    el.textContent = text;
  }
  const ACQ_TONE = { OK: 'ok', ACQUIRING: 'active', PARTIAL: 'warn', FAILED: 'danger', NEVER: 'idle' };
  const THREAD_TONE = {
    RUNNING: 'active', CONVERGED: 'ok', DIVERGED: 'danger', FAILED: 'danger',
    STOPPED: 'warn', MAX_STEPS: 'warn', NEVER: 'idle',
  };

  function pv(name) { return PV_PREFIX + name; }

  function recomputeReference() {
    if (!st.refLoaded) {
      els.refRms.textContent = '—';
      els.refCoverage.textContent = '—';
      return;
    }
    const xr = rms(st.dx), yr = rms(st.dy);
    els.refRms.textContent =
      (Number.isFinite(xr) || Number.isFinite(yr))
        ? `X ${fmtMm(xr)} · Y ${fmtMm(yr)}` : '—';
    // Coverage: BPMs with a finite diff on both planes, vs. total BPMs.
    const total = st.names.length;
    let valid = 0;
    for (let i = 0; i < total; i++) {
      if (Number.isFinite(st.dx[i]) && Number.isFinite(st.dy[i])) valid++;
    }
    els.refCoverage.textContent = total ? `${valid} / ${total} BPMs` : '—';
  }

  function subscribeAll() {
    // Machine / liveness
    connection.subscribe(pv('HEALTH:HEARTBEAT'), (m) => { els.heartbeat.textContent = m.value; });
    connection.subscribe(pv('HEALTH:UPTIME_S'), (m) => { els.uptime.textContent = fmtUptime(m.value); });
    connection.subscribe(pv('STATE:VERSION'), (m) => { els.version.textContent = m.value || '—'; });

    // Last acquisition
    connection.subscribe(pv('STATE:LAST_ACQUIRE_STATUS'), (m) => {
      const name = acquireStatusName(m.value);
      pill(els.acqStatus, ACQ_TONE[name] || 'idle', name);
    });
    let ok = 0, fail = 0;
    connection.subscribe(pv('STATE:LAST_ACQUIRE_OK_COUNT'), (m) => { ok = m.value; els.acqBpms.textContent = `${ok} ok · ${fail} fail`; });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_FAIL_COUNT'), (m) => { fail = m.value; els.acqBpms.textContent = `${ok} ok · ${fail} fail`; });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_TIMESTAMP'), (m) => { els.acqWhen.textContent = fmtTime(m.value); });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_FAILED_BPM_NAMES'), (m) => {
      const arr = Array.isArray(m.value) ? m.value : (m.value ? [m.value] : []);
      const names = arr.filter((s) => s && s.length);
      els.acqFailed.textContent = names.length ? names.join(', ') : 'none';
      els.acqFailed.dataset.tone = names.length ? 'warn' : 'idle';
    });
    connection.subscribe(pv('RESULT:BPM:INJECTION_TURN'), (m) => {
      const arr = Array.isArray(m.value) ? m.value : [m.value];
      const valid = arr.filter((v) => v >= 0).sort((a, b) => a - b);
      els.injTurn.textContent = valid.length ? `median ${valid[Math.floor(valid.length / 2)]}` : '—';
    });

    // Reference
    connection.subscribe(pv('STATE:REF_LOADED'), (m) => {
      st.refLoaded = Boolean(m.value);
      pill(els.refStatus, st.refLoaded ? 'ok' : 'idle', st.refLoaded ? 'loaded' : 'none');
      recomputeReference();
    });
    connection.subscribe(pv('STATE:REF_NAME'), (m) => { els.refName.textContent = m.value || '—'; });
    connection.subscribe(pv('STATE:REF_SOURCE'), (m) => { els.refSource.textContent = m.value || '—'; });
    connection.subscribe(pv('RESULT:BPM:X_DIFF_FIRST_TURN'), (m) => {
      st.dx = Array.isArray(m.value) ? m.value : [m.value]; recomputeReference();
    });
    connection.subscribe(pv('RESULT:BPM:Y_DIFF_FIRST_TURN'), (m) => {
      st.dy = Array.isArray(m.value) ? m.value : [m.value]; recomputeReference();
    });
    connection.subscribe(pv('RESULT:BPM:NAMES'), (m) => {
      st.names = Array.isArray(m.value) ? m.value : [m.value]; recomputeReference();
    });

    // Threading loop
    connection.subscribe(pv('STATE:THREAD_STATUS'), (m) => {
      const s = m.value || 'NEVER';
      pill(els.threadStatus, THREAD_TONE[s] || 'idle', s);
    });
    connection.subscribe(pv('STATE:THREAD_ITERATION'), (m) => { els.threadIter.textContent = m.value; });
    connection.subscribe(pv('RESULT:THREAD_RMS'), (m) => {
      els.threadRms.textContent = Number.isFinite(m.value) ? `${Number(m.value).toFixed(4)} mm` : '—';
    });
  }

  // --- quick action: acquire ---
  els.acquireBtn.addEventListener('click', async () => {
    els.acquireBtn.disabled = true;
    els.acquireMeta.textContent = 'acquiring…';
    try {
      const r = await connection.command('acquire', {});
      els.acquireMeta.textContent = `${r.status} (${r.ok_count} OK · ${r.fail_count} FAIL)`;
    } catch (e) {
      els.acquireMeta.textContent = `error: ${e.message}`;
    } finally {
      els.acquireBtn.disabled = false;
    }
  });

  // --- bootstrap: prefix then subscribe ---
  fetch('/api/v1/config')
    .then((r) => r.json())
    .then((cfg) => {
      PV_PREFIX = cfg.pv_prefix || PV_PREFIX;
      els.prefix.textContent = PV_PREFIX;
      subscribeAll();
    })
    .catch(() => { els.prefix.textContent = PV_PREFIX; subscribeAll(); });
})();
