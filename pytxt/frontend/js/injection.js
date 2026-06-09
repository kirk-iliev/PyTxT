/* PyTxT injection control (Phase 5 / U4).
 *
 * Safety-gated one-shot fire over CMD:INJECT_ONESHOT. The gun-fire path
 * (inhibit=0) is made deliberately hard to reach: the whole panel turns danger,
 * a separate "allow gun fire" opt-in must be checked, and only then does the
 * FIRE button enable — mirroring the backend's allow_gun_fire guard (403).
 * Last shot is read live from STATE:INJ_LAST_* PVs.
 */
(function () {
  'use strict';

  let PV_PREFIX = 'OSPREY:TEST:TXT:';

  const els = {
    panel: document.getElementById('injPanel'),
    inhibit: document.getElementById('injInhibit'),
    gunWarn: document.getElementById('injGunWarn'),
    allow: document.getElementById('injAllow'),
    bucket: document.getElementById('injBucket'),
    gunBunches: document.getElementById('injGunBunches'),
    mode: document.getElementById('injMode'),
    force: document.getElementById('injForce'),
    fireBtn: document.getElementById('injFireBtn'),
    msg: document.getElementById('injMsg'),
    lastStatus: document.getElementById('injLastStatus'),
    lastBucket: document.getElementById('injLastBucket'),
    lastMode: document.getElementById('injLastMode'),
    lastInhibit: document.getElementById('injLastInhibit'),
    lastSeq: document.getElementById('injLastSeq'),
    lastTime: document.getElementById('injLastTime'),
  };

  function pv(n) { return PV_PREFIX + n; }
  function fmtTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour12: false });
  }

  function gunFireSelected() { return els.inhibit.value === '0'; }

  // Reflect the gun-mode choice into the panel's danger state + fire button.
  function syncMode() {
    const gun = gunFireSelected();
    els.gunWarn.hidden = !gun;
    els.panel.classList.toggle('is-danger', gun);
    els.fireBtn.classList.toggle('btn--danger', gun);
    els.fireBtn.classList.toggle('btn--primary', !gun);
    if (gun) {
      els.fireBtn.textContent = '‼ FIRE GUN';
      els.fireBtn.disabled = !els.allow.checked;
    } else {
      els.fireBtn.textContent = '▶ Fire (bumps only)';
      els.fireBtn.disabled = false;
      els.allow.checked = false;
    }
  }

  async function fire() {
    const gun = gunFireSelected();
    const body = {
      bucket: parseInt(els.bucket.value, 10),
      gun_bunches: parseInt(els.gunBunches.value, 10),
      mode: parseInt(els.mode.value, 10),
      inhibit: gun ? 0 : 1,
      allow_gun_fire: gun && els.allow.checked,
      force: els.force.checked,
    };
    els.msg.textContent = 'firing…';
    els.fireBtn.disabled = true;
    try {
      const r = await connection.command('inject_oneshot', body);
      els.msg.textContent = `FIRED — bucket ${r.bucket} · seq ${r.seq_num} · fine-delay ${r.fine_delay_counts}`;
    } catch (e) {
      // 403 = gun-fire guard; 409 = top-off precondition; 503 = no trigger.
      const m = e.message;
      els.msg.textContent =
        /403/.test(m) ? 'refused: gun fire not permitted (allow_gun_fire required)' :
        /409/.test(m) ? 'refused: bucket loading / top-off active (use Force to override)' :
        /503/.test(m) ? 'injection trigger not configured' :
        `fire failed: ${m}`;
    } finally {
      syncMode();   // restore correct enabled/disabled state
    }
  }

  function subscribeLast() {
    connection.subscribe(pv('STATE:INJ_LAST_STATUS'), (m) => {
      const s = m.value || 'NEVER';
      els.lastStatus.dataset.tone = s === 'FIRED' ? 'ok' : 'idle';
      els.lastStatus.textContent = s;
    });
    connection.subscribe(pv('STATE:INJ_LAST_BUCKET'), (m) => { els.lastBucket.textContent = m.value; });
    connection.subscribe(pv('STATE:INJ_LAST_MODE'), (m) => { els.lastMode.textContent = m.value; });
    connection.subscribe(pv('STATE:INJ_LAST_INHIBIT'), (m) => {
      els.lastInhibit.textContent = Number(m.value) === 0 ? 'FIRED (inhibit=0)' : 'blocked (inhibit=1)';
    });
    connection.subscribe(pv('STATE:INJ_LAST_SEQ_NUM'), (m) => { els.lastSeq.textContent = m.value; });
    connection.subscribe(pv('STATE:INJ_LAST_TIMESTAMP'), (m) => { els.lastTime.textContent = fmtTime(m.value); });
  }

  els.inhibit.addEventListener('change', syncMode);
  els.allow.addEventListener('change', syncMode);
  els.fireBtn.addEventListener('click', fire);

  fetch('/api/v1/config').then((r) => r.json())
    .then((c) => { PV_PREFIX = c.pv_prefix || PV_PREFIX; })
    .catch(() => {})
    .finally(() => { subscribeLast(); syncMode(); });
})();
