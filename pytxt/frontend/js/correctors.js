/* PyTxT corrector panel (Phase 5 / U3).
 *
 * Manual HCM/VCM corrector step (manual steps 11/17) over CMD:STEP_CM, with the
 * Decision-D5 compare-and-set guard made visible:
 *   Preview (dry-run, tol=∞) reads the current setpoint and previews the clamped
 *   result, then Apply uses that previewed value as the compare-and-set base —
 *   so a competing writer between preview and apply is caught (409 → REFUSED).
 *
 * The corrector catalog (names + limits) comes from GET /api/v1/config/correctors;
 * last-step outcome is read live from STATE:CM_LAST_* PVs.
 */
(function () {
  'use strict';

  let PV_PREFIX = 'OSPREY:TEST:TXT:';
  let catalog = { HCM: [], VCM: [] };
  let previewedPrior = null;   // readback captured by the last successful preview

  const els = {
    family: document.getElementById('cmFamily'),
    device: document.getElementById('cmDevice'),
    delta: document.getElementById('cmDelta'),
    tol: document.getElementById('cmTol'),
    limit: document.getElementById('cmLimit'),
    catalog: document.getElementById('cmCatalog'),
    result: document.getElementById('cmResult'),
    resultBody: document.getElementById('cmResultBody'),
    danger: document.getElementById('cmDanger'),
    previewBtn: document.getElementById('cmPreviewBtn'),
    applyBtn: document.getElementById('cmApplyBtn'),
    msg: document.getElementById('cmMsg'),
    lastStatus: document.getElementById('cmLastStatus'),
    lastFamily: document.getElementById('cmLastFamily'),
    lastApplied: document.getElementById('cmLastApplied'),
    lastClamped: document.getElementById('cmLastClamped'),
    lastTime: document.getElementById('cmLastTime'),
  };

  const STATUS_TONE = { APPLIED: 'ok', DRY_RUN: 'active', REFUSED: 'danger', NEVER: 'idle' };

  function pv(n) { return PV_PREFIX + n; }
  function fmtTime(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour12: false });
  }

  function currentDevice() {
    const fam = els.family.value;
    const idx = parseInt(els.device.value, 10);
    return catalog[fam] && catalog[fam][idx] ? catalog[fam][idx] : null;
  }

  function repopulateDevices() {
    const fam = els.family.value;
    els.device.innerHTML = '';
    for (const c of catalog[fam] || []) {
      const opt = document.createElement('option');
      opt.value = c.index;
      opt.textContent = `${c.index}: ${c.name}`;
      els.device.appendChild(opt);
    }
    updateLimit();
    invalidatePreview();
  }

  function updateLimit() {
    const c = currentDevice();
    els.limit.textContent = c ? `Limit: ±${c.max_abs_a} A` : '';
  }

  // Any input change invalidates a prior preview (the apply base is stale).
  function invalidatePreview() {
    previewedPrior = null;
    els.applyBtn.disabled = true;
    els.danger.hidden = true;
  }

  function renderResult(applied) {
    els.resultBody.innerHTML = '';
    for (const a of applied) {
      const tr = document.createElement('tr');
      tr.innerHTML =
        `<td>${a.name}</td>` +
        `<td>${a.readback_a.toFixed(4)}</td>` +
        `<td>${a.delta_a >= 0 ? '+' : ''}${a.delta_a.toFixed(4)}</td>` +
        `<td>${a.new_value_a.toFixed(4)}</td>` +
        `<td>${a.clamped ? '<span class="cm-clamp">clamped</span>' : '—'}</td>`;
      els.resultBody.appendChild(tr);
    }
    els.result.hidden = false;
  }

  function buildRequest({ dryRun }) {
    const c = currentDevice();
    if (!c) return null;
    const delta = parseFloat(els.delta.value);
    const tol = parseFloat(els.tol.value);
    if (dryRun) {
      // tol=∞ + dummy prior so the dry-run never refuses; it returns the live
      // readback we'll use as the apply base.
      return { family: els.family.value, device_list: [c.index], deltas: [delta],
               expected_prior_a: [0], tol_a: 1e12, dry_run: true };
    }
    return { family: els.family.value, device_list: [c.index], deltas: [delta],
             expected_prior_a: [previewedPrior], tol_a: Number.isFinite(tol) ? tol : 0.05,
             dry_run: false };
  }

  async function preview() {
    const req = buildRequest({ dryRun: true });
    if (!req) return;
    els.msg.textContent = 'previewing…';
    try {
      const r = await connection.command('step_cm', req);
      renderResult(r.applied);
      previewedPrior = r.applied[0].readback_a;
      els.applyBtn.disabled = false;
      els.danger.hidden = false;
      els.msg.textContent = `previewed — current ${previewedPrior.toFixed(4)} A`;
    } catch (e) {
      invalidatePreview();
      els.msg.textContent = `preview failed: ${e.message}`;
    }
  }

  async function apply() {
    if (previewedPrior === null) return;
    const req = buildRequest({ dryRun: false });
    els.msg.textContent = 'applying…';
    els.applyBtn.disabled = true;
    try {
      const r = await connection.command('step_cm', req);
      renderResult(r.applied);
      els.msg.textContent = `APPLIED${r.n_clamped ? ` (${r.n_clamped} clamped)` : ''}`;
      invalidatePreview();   // require a fresh preview for the next apply
    } catch (e) {
      // 409 = compare-and-set refusal (live setpoint moved since preview).
      const refused = /409/.test(e.message);
      els.msg.textContent = refused
        ? 'REFUSED — live setpoint changed since preview; preview again'
        : `apply failed: ${e.message}`;
      invalidatePreview();
    }
  }

  function subscribeLast() {
    connection.subscribe(pv('STATE:CM_LAST_STATUS'), (m) => {
      const s = m.value || 'NEVER';
      els.lastStatus.dataset.tone = STATUS_TONE[s] || 'idle';
      els.lastStatus.textContent = s;
    });
    connection.subscribe(pv('STATE:CM_LAST_FAMILY'), (m) => { els.lastFamily.textContent = m.value || '—'; });
    connection.subscribe(pv('STATE:CM_LAST_N_APPLIED'), (m) => { els.lastApplied.textContent = m.value; });
    connection.subscribe(pv('STATE:CM_LAST_N_CLAMPED'), (m) => { els.lastClamped.textContent = m.value; });
    connection.subscribe(pv('STATE:CM_LAST_TIMESTAMP'), (m) => { els.lastTime.textContent = fmtTime(m.value); });
  }

  // wiring
  els.family.addEventListener('change', repopulateDevices);
  els.device.addEventListener('change', () => { updateLimit(); invalidatePreview(); });
  els.delta.addEventListener('input', invalidatePreview);
  els.tol.addEventListener('input', invalidatePreview);
  els.previewBtn.addEventListener('click', preview);
  els.applyBtn.addEventListener('click', apply);

  // bootstrap
  Promise.all([
    fetch('/api/v1/config').then((r) => r.json()).then((c) => { PV_PREFIX = c.pv_prefix || PV_PREFIX; }).catch(() => {}),
    fetch('/api/v1/config/correctors').then((r) => r.json()).then((c) => { catalog = c; }).catch(() => {}),
  ]).then(() => {
    els.catalog.textContent = `${(catalog.HCM || []).length} HCM · ${(catalog.VCM || []).length} VCM`;
    repopulateDevices();
    subscribeLast();
  });
})();
