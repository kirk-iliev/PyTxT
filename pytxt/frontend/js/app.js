/* PyTxT — page logic.
 *
 * Subscribes to the phase-1 PVs, updates DOM elements, wires the Ping
 * button to a REST POST, and writes a rolling event log.
 */
(function () {
  'use strict';

  // PV prefix is fetched from the server's /api/v1/config endpoint on load,
  // so the same JS works in dev (OSPREY:TEST:TXT:) and prod (TxT:) without
  // a code change.
  let PV_PREFIX = 'OSPREY:TEST:TXT:'; // fallback if config fetch fails

  // --- DOM refs ---
  const els = {
    version: document.getElementById('version'),
    heartbeat: document.getElementById('heartbeat'),
    uptime: document.getElementById('uptime'),
    lastPingAt: document.getElementById('lastPingAt'),
    pingCount: document.getElementById('pingCount'),
    pingButton: document.getElementById('pingButton'),
    eventLog: document.getElementById('eventLog'),
    connectionStatus: document.getElementById('connectionStatus'),
    connectionStatusLabel: document.getElementById('connectionStatusLabel'),
  };

  const MAX_LOG_ENTRIES = 10;

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

  function fmtUptime(s) {
    const sec = Math.floor(s);
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const r = sec % 60;
    return `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
  }

  // --- Connection status indicator ---
  connection.onStatusChange((status) => {
    els.connectionStatus.dataset.state = status;
    els.connectionStatusLabel.textContent = status;
    if (status === 'connected') logEvent('connected');
    if (status === 'disconnected') logEvent('disconnected');
  });

  function subscribeAll() {
    connection.subscribe(PV_PREFIX + 'STATE:VERSION', (m) => {
      els.version.textContent = m.value || '—';
    });
    connection.subscribe(PV_PREFIX + 'HEALTH:HEARTBEAT', (m) => {
      els.heartbeat.textContent = m.value;
    });
    connection.subscribe(PV_PREFIX + 'HEALTH:UPTIME_S', (m) => {
      els.uptime.textContent = fmtUptime(m.value);
    });
    connection.subscribe(PV_PREFIX + 'STATE:LAST_PING_AT', (m) => {
      els.lastPingAt.textContent = m.value || '—';
    });
    connection.subscribe(PV_PREFIX + 'STATE:PING_COUNT', (m) => {
      els.pingCount.textContent = m.value;
      if (m.value > 0) logEvent(`ping count → ${m.value}`);
    });
  }

  // --- Bootstrap: fetch prefix, then subscribe ---
  fetch('/api/v1/config')
    .then((r) => r.json())
    .then((cfg) => {
      PV_PREFIX = cfg.pv_prefix || PV_PREFIX;
      subscribeAll();
    })
    .catch(() => subscribeAll()); // best-effort; fall back to default

  // --- Ping button ---
  els.pingButton.addEventListener('click', async () => {
    els.pingButton.disabled = true;
    try {
      const result = await connection.command('ping', {});
      logEvent(`ping sent (${result.acknowledged_at})`);
    } catch (e) {
      logEvent(`ping failed: ${e.message}`);
    } finally {
      els.pingButton.disabled = false;
    }
  });
})();
