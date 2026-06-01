/* PyTxT trajectory page — reference sidebar (Phase 3 M4).
 *
 * Owns the reference-library sidebar and its dialogs. Subscribes to the
 * STATE:REF_* PVs to render the loaded-reference status, and drives the five
 * reference commands:
 *
 *   Promote current  → POST /api/v1/cmd/promote_ref   (CA parity: CMD:PROMOTE_REF)
 *   Load…            → GET  /api/v1/references + POST /api/v1/cmd/load_ref
 *   Save current…    → POST /api/v1/cmd/save_ref
 *   Upload .mat      → POST /api/v1/references (multipart — the one REST-only
 *                      action; a file's bytes can't be a PV, design §15)
 *   Clear            → POST /api/v1/cmd/clear_ref      (CA parity: CMD:CLEAR_REF)
 *
 * Success needs no manual state-poke: every command's effect comes back over
 * the STATE:REF_* PV subscriptions, which re-render the sidebar (CLAUDE.md §1
 * observability — the PV is the confirmation).
 */
(function () {
  'use strict';

  const refStatusEl = document.getElementById('refStatus');
  const refMsgEl = document.getElementById('refMsg');
  const promoteBtn = document.getElementById('promoteRefBtn');
  const loadBtn = document.getElementById('loadRefBtn');
  const saveBtn = document.getElementById('saveRefBtn');
  const uploadBtn = document.getElementById('uploadRefBtn');
  const clearBtn = document.getElementById('clearRefBtn');
  const uploadInput = document.getElementById('uploadRefInput');

  const loadDialog = document.getElementById('loadRefDialog');
  const refListEl = document.getElementById('refList');
  const loadCancel = document.getElementById('loadRefCancel');

  const saveDialog = document.getElementById('saveRefDialog');
  const saveNameInput = document.getElementById('saveRefName');
  const saveConfirm = document.getElementById('saveRefConfirm');
  const saveCancel = document.getElementById('saveRefCancel');

  const ref = {
    prefix: 'OSPREY:TEST:TXT:',  // overridden by /api/v1/config
    loaded: false, name: '', source: '', loadedAt: '',
    okCount: 0,  // last-acquire ok count → gates Promote/Save
  };

  function pad2(n) { return String(n).padStart(2, '0'); }

  function defaultSaveName() {
    // Mirrors the MATLAB GUI timestamp default; if the user keeps it we POST
    // this name, otherwise an empty name lets the backend stamp its own.
    const d = new Date();
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}_` +
      `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}_reference_trajectory.mat`;
  }

  function fmtTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return isNaN(d.getTime()) ? iso : d.toLocaleTimeString([], { hour12: false });
  }

  function setMsg(text, kind) {
    refMsgEl.textContent = text || '';
    refMsgEl.className = 'ref-msg' + (kind ? ' ' + kind : '');
  }

  function renderStatus() {
    if (ref.loaded) {
      const when = fmtTime(ref.loadedAt);
      refStatusEl.innerHTML =
        `<span class="ref-name"></span><br>` +
        `<span class="ref-meta"></span>`;
      refStatusEl.querySelector('.ref-name').textContent = ref.name || '(unnamed)';
      refStatusEl.querySelector('.ref-meta').textContent =
        `${ref.source || '?'}${when ? ' · ' + when : ''}`;
    } else {
      refStatusEl.textContent = 'No reference loaded';
    }
    // Promote/Save need a successful acquire to source from.
    const noAcquire = ref.okCount <= 0;
    promoteBtn.disabled = noAcquire;
    saveBtn.disabled = noAcquire;
    clearBtn.disabled = !ref.loaded;
  }

  function pv(name) { return ref.prefix + name; }

  // --- REST helpers ---------------------------------------------------------

  async function detailFrom(resp) {
    try { const j = await resp.json(); if (j && j.detail) return j.detail; } catch (e) { /* ignore */ }
    return `HTTP ${resp.status}`;
  }

  async function fetchReferences() {
    const r = await fetch('/api/v1/references');
    if (!r.ok) throw new Error(await detailFrom(r));
    return (await r.json()).references || [];
  }

  async function uploadReference(file) {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/v1/references', { method: 'POST', body: fd });
    if (!r.ok) throw new Error(await detailFrom(r));
    return r.json();
  }

  // --- Load picker dialog ---------------------------------------------------

  async function openLoadDialog() {
    setMsg('');
    refListEl.innerHTML = '<li class="ref-list-empty">Loading…</li>';
    loadDialog.hidden = false;
    try {
      const entries = await fetchReferences();
      refListEl.innerHTML = '';
      if (!entries.length) {
        refListEl.innerHTML = '<li class="ref-list-empty">Library is empty</li>';
        return;
      }
      for (const e of entries) {
        const li = document.createElement('li');
        const name = document.createElement('span');
        name.className = 'ref-list-name';
        name.textContent = e.name;
        const meta = document.createElement('span');
        meta.className = 'ref-list-meta';
        meta.textContent = fmtTime(e.modified_at);
        li.appendChild(name);
        li.appendChild(meta);
        li.addEventListener('click', () => loadByName(e.name));
        refListEl.appendChild(li);
      }
    } catch (err) {
      refListEl.innerHTML = '';
      const li = document.createElement('li');
      li.className = 'ref-list-empty';
      li.textContent = 'Error: ' + err.message;
      refListEl.appendChild(li);
    }
  }

  function closeLoadDialog() { loadDialog.hidden = true; }

  async function loadByName(name) {
    closeLoadDialog();
    try {
      await connection.command('load_ref', { name });
      setMsg(`Loaded ${name}`, 'ok');
    } catch (err) {
      setMsg('Load failed: ' + err.message, 'error');
    }
  }

  // --- Save dialog ----------------------------------------------------------

  function openSaveDialog() {
    setMsg('');
    saveNameInput.value = defaultSaveName();
    saveDialog.hidden = false;
    saveNameInput.focus();
    saveNameInput.select();
  }

  function closeSaveDialog() { saveDialog.hidden = true; }

  async function confirmSave() {
    const name = saveNameInput.value.trim();
    closeSaveDialog();
    try {
      // Empty → let the backend stamp the timestamp default.
      const body = name ? { name } : {};
      const res = await connection.command('save_ref', body);
      setMsg(`Saved ${res.name}`, 'ok');
    } catch (err) {
      setMsg('Save failed: ' + err.message, 'error');
    }
  }

  // --- Wiring ---------------------------------------------------------------

  function wire() {
    promoteBtn.addEventListener('click', async () => {
      setMsg('');
      try {
        await connection.command('promote_ref', {});
        setMsg('Promoted current trajectory', 'ok');
      } catch (err) {
        setMsg('Promote failed: ' + err.message, 'error');
      }
    });

    clearBtn.addEventListener('click', async () => {
      setMsg('');
      try {
        await connection.command('clear_ref', {});
        setMsg('Reference cleared', 'ok');
      } catch (err) {
        setMsg('Clear failed: ' + err.message, 'error');
      }
    });

    loadBtn.addEventListener('click', openLoadDialog);
    loadCancel.addEventListener('click', closeLoadDialog);

    saveBtn.addEventListener('click', openSaveDialog);
    saveCancel.addEventListener('click', closeSaveDialog);
    saveConfirm.addEventListener('click', confirmSave);
    saveNameInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') confirmSave();
      if (e.key === 'Escape') closeSaveDialog();
    });

    uploadBtn.addEventListener('click', () => uploadInput.click());
    uploadInput.addEventListener('change', async () => {
      const file = uploadInput.files && uploadInput.files[0];
      uploadInput.value = '';  // allow re-selecting the same file later
      if (!file) return;
      setMsg(`Uploading ${file.name}…`);
      try {
        const entry = await uploadReference(file);
        setMsg(`Uploaded ${entry.name}`, 'ok');
      } catch (err) {
        setMsg('Upload failed: ' + err.message, 'error');
      }
    });

    // Click on the dialog backdrop (outside the box) dismisses it.
    loadDialog.addEventListener('click', (e) => { if (e.target === loadDialog) closeLoadDialog(); });
    saveDialog.addEventListener('click', (e) => { if (e.target === saveDialog) closeSaveDialog(); });
  }

  async function bootstrap() {
    try {
      const cfg = await fetch('/api/v1/config').then((r) => r.json());
      ref.prefix = cfg.pv_prefix;
    } catch (e) {
      console.warn('reference.js: could not fetch /api/v1/config; using default prefix', e);
    }

    wire();
    renderStatus();

    connection.subscribe(pv('STATE:REF_LOADED'), (msg) => {
      ref.loaded = Boolean(msg.value);
      renderStatus();
    });
    connection.subscribe(pv('STATE:REF_NAME'), (msg) => {
      ref.name = msg.value || '';
      renderStatus();
    });
    connection.subscribe(pv('STATE:REF_SOURCE'), (msg) => {
      ref.source = msg.value || '';
      renderStatus();
    });
    connection.subscribe(pv('STATE:REF_LOADED_AT'), (msg) => {
      ref.loadedAt = msg.value || '';
      renderStatus();
    });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_OK_COUNT'), (msg) => {
      ref.okCount = Number(msg.value) || 0;
      renderStatus();
    });
  }

  bootstrap();
})();
