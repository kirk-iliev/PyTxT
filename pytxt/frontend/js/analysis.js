/* PyTxT — first-turn analysis strip (Phase 5 / U6).
 *
 * Subscribes to the RESULT:ANALYSIS:* PVs (orbit excursion + beam transmission,
 * computed per ACQUIRE) and renders them as a compact readout strip on the
 * Trajectory page. Pure CA client — same PVs Phoebus/agents see.
 */
(function () {
  'use strict';

  let PV_PREFIX = 'OSPREY:TEST:TXT:';
  const els = {
    xRms: document.getElementById('anXRms'),
    yRms: document.getElementById('anYRms'),
    xMax: document.getElementById('anXMax'),
    yMax: document.getElementById('anYMax'),
    live: document.getElementById('anLive'),
    reach: document.getElementById('anReach'),
  };
  // n_live / n_bpms / reach arrive on separate PVs; cache to compose.
  const st = { live: null, total: null, reachIdx: null, reachName: '' };

  function mm(v) { return Number.isFinite(v) ? v.toFixed(3) + ' mm' : '—'; }
  function pv(n) { return PV_PREFIX + n; }

  function renderTransmission() {
    els.live.textContent = (st.live === null) ? '—'
      : (st.total ? `${st.live} / ${st.total}` : String(st.live));
    if (st.reachIdx === null) { els.reach.textContent = '—'; return; }
    els.reach.textContent = st.reachIdx < 0 ? 'no beam'
      : (st.reachName ? `${st.reachName} (#${st.reachIdx})` : `#${st.reachIdx}`);
  }

  function subscribeAll() {
    connection.subscribe(pv('RESULT:ANALYSIS:X_RMS'), (m) => { els.xRms.textContent = mm(Number(m.value)); });
    connection.subscribe(pv('RESULT:ANALYSIS:Y_RMS'), (m) => { els.yRms.textContent = mm(Number(m.value)); });
    connection.subscribe(pv('RESULT:ANALYSIS:X_MAX_ABS'), (m) => { els.xMax.textContent = mm(Number(m.value)); });
    connection.subscribe(pv('RESULT:ANALYSIS:Y_MAX_ABS'), (m) => { els.yMax.textContent = mm(Number(m.value)); });
    connection.subscribe(pv('RESULT:ANALYSIS:N_LIVE_BPMS'), (m) => { st.live = Number(m.value); renderTransmission(); });
    connection.subscribe(pv('RESULT:ANALYSIS:REACH_INDEX'), (m) => { st.reachIdx = Number(m.value); renderTransmission(); });
    connection.subscribe(pv('RESULT:ANALYSIS:REACH_NAME'), (m) => { st.reachName = m.value || ''; renderTransmission(); });
    // total BPMs: derive from the names waveform length.
    connection.subscribe(pv('RESULT:BPM:NAMES'), (m) => {
      const arr = Array.isArray(m.value) ? m.value : [m.value];
      st.total = arr.filter((s) => s && s.length).length;
      renderTransmission();
    });
  }

  fetch('/api/v1/config').then((r) => r.json())
    .then((c) => { PV_PREFIX = c.pv_prefix || PV_PREFIX; })
    .catch(() => {})
    .finally(subscribeAll);
})();
