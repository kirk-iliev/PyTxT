/* PyTxT — connection helper.
 *
 * Encapsulates the WebSocket subscription protocol and the REST POST
 * helper for issuing commands. Exposes a small public API on `window`:
 *
 *   connection.subscribe(pvName, callback)        // call callback({pv, value, ts})
 *   connection.unsubscribe(pvName, callback)
 *   connection.command(name, body)                 // POST /api/v1/cmd/<name>
 *   connection.status                              // 'connecting' | 'connected' | 'disconnected'
 *   connection.onStatusChange(callback)
 *
 * Auto-reconnect with exponential backoff (1s → 2s → 4s → max 30s).
 * On reconnect, re-subscribes to all previously-subscribed PVs.
 */
(function () {
  'use strict';

  const WS_PATH = '/api/v1/pvs';
  const REST_BASE = '/api/v1/cmd';
  const BACKOFF_INITIAL_MS = 1000;
  const BACKOFF_MAX_MS = 30000;

  const subscribers = new Map();   // pvName -> Set<callback>
  const statusListeners = new Set();
  let ws = null;
  let backoff = BACKOFF_INITIAL_MS;
  let reconnectTimer = null;
  let currentStatus = 'connecting';

  function setStatus(s) {
    if (currentStatus === s) return;
    currentStatus = s;
    statusListeners.forEach((cb) => { try { cb(s); } catch (e) { console.error(e); } });
  }

  function wsUrl() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}${WS_PATH}`;
  }

  function connect() {
    setStatus('connecting');
    ws = new WebSocket(wsUrl());

    ws.addEventListener('open', () => {
      setStatus('connected');
      backoff = BACKOFF_INITIAL_MS;
      // Re-subscribe to everything
      const allPvs = Array.from(subscribers.keys());
      if (allPvs.length) {
        ws.send(JSON.stringify({ action: 'subscribe', pvs: allPvs }));
      }
    });

    ws.addEventListener('message', (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); }
      catch (e) { console.warn('WS bad JSON', ev.data); return; }
      if (msg.error) {
        console.warn(`PV error: ${msg.pv} — ${msg.error}`);
        return;
      }
      const cbs = subscribers.get(msg.pv);
      if (!cbs) return;
      cbs.forEach((cb) => { try { cb(msg); } catch (e) { console.error(e); } });
    });

    ws.addEventListener('close', () => {
      setStatus('disconnected');
      scheduleReconnect();
    });

    ws.addEventListener('error', () => {
      // 'close' will fire too; reconnect is handled there
    });
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      backoff = Math.min(backoff * 2, BACKOFF_MAX_MS);
      connect();
    }, backoff);
  }

  function subscribe(pvName, callback) {
    if (!subscribers.has(pvName)) {
      subscribers.set(pvName, new Set());
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'subscribe', pvs: [pvName] }));
      }
    }
    subscribers.get(pvName).add(callback);
  }

  function unsubscribe(pvName, callback) {
    const set = subscribers.get(pvName);
    if (!set) return;
    set.delete(callback);
    if (set.size === 0) {
      subscribers.delete(pvName);
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ action: 'unsubscribe', pvs: [pvName] }));
      }
    }
  }

  async function command(name, body) {
    const r = await fetch(`${REST_BASE}/${name}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) throw new Error(`Command ${name} failed: HTTP ${r.status}`);
    return r.json();
  }

  function onStatusChange(callback) {
    statusListeners.add(callback);
    callback(currentStatus);
  }

  window.connection = {
    subscribe, unsubscribe, command, onStatusChange,
    get status() { return currentStatus; },
  };

  connect();
})();
