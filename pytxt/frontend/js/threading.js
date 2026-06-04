/* PyTxT — threading page logic.
 *
 * Subscribes to the STATE:THREAD_* / RESULT:THREAD_RMS PVs, wires the Start
 * button to POST /api/v1/cmd/thread_start and Stop to thread_stop. The same
 * handler backs the CA path, so this UI is just one client of the command.
 */
(function () {
  'use strict';

  let PV_PREFIX = 'OSPREY:TEST:TXT:';

  const els = {
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
    connectionStatus: document.getElementById('connectionStatus'),
    connectionStatusLabel: document.getElementById('connectionStatusLabel'),
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

  connection.onStatusChange((status) => {
    els.connectionStatus.dataset.state = status;
    els.connectionStatusLabel.textContent = status;
  });

  function subscribeAll() {
    connection.subscribe(PV_PREFIX + 'STATE:THREAD_STATUS', (m) => {
      els.threadStatus.textContent = m.value || '—';
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

  // --- Bootstrap: fetch prefix, then subscribe ---
  fetch('/api/v1/config')
    .then((r) => r.json())
    .then((cfg) => { PV_PREFIX = cfg.pv_prefix || PV_PREFIX; })
    .catch((e) => console.warn('Could not fetch /api/v1/config; using default prefix', e))
    .finally(subscribeAll);
})();
