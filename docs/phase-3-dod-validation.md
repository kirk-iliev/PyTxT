# Phase 3 DoD — control-room validation runbook

**Goal:** confirm the reference-trajectory workflow works end-to-end on the
real ALS ring (appsdev2), satisfying design-spec §12 (Phase 3 Definition of
Done). Pick this up at the lab and work top to bottom.

**Spec:** `docs/superpowers/specs/2026-05-29-phase-3-reference-trajectory-design.md` §12
**Status going in:** DoD item **6** (full pytest + Playwright suite green) is
already done — 256/256 pytest + 6/6 e2e on 2026-06-01. Items **1–5** below need
the real ring and are what you're validating here.

All commands run **on appsdev2** unless noted. Check off each box as you go;
record outcomes in the **Results log** at the bottom.

---

## Step 0 — Bring up PyTxT in production mode

- [ ] **0a. Pull the latest main** (includes the writable-library deploy fix `b695746`):
  ```bash
  cd <repo root on appsdev2>
  git pull
  git log --oneline -1     # expect b695746 or later
  ```

- [ ] **0b. Create the prod `.env`** in the repo root:
  ```bash
  cat > .env <<'EOF'
  PYTXT_PV_PREFIX=TxT:
  PYTXT_IOC_PORT=5064
  PYTXT_IOC_REPEATER_PORT=5065
  PYTXT_API_HOST=0.0.0.0
  PYTXT_REFERENCE_DIR=data/references
  EOF
  ```

- [ ] **0c. Seed the reference library** with the legacy MATLAB GUI files (so
  there's something to load in DoD #1):
  ```bash
  mkdir -p data/references
  cp /home/als/physbase/users/thellert/automated_startup/GUI/*.mat data/references/
  ls -la data/references/      # expect 2025-03-23_*_reference_trajectory.mat
  ```

- [ ] **0d. Build + start** (host networking so CA reaches Phoebus/archiver/
  Osprey; the `data/references` subdir is mounted `:rw`):
  ```bash
  docker compose -f docker/docker-compose.yml -f docker/docker-compose.host.yml up -d --build
  ```

- [ ] **0e. Liveness sanity:**
  ```bash
  curl -fsS http://localhost:8008/health && echo OK
  caget TxT:HEALTH:HEARTBEAT          # should increase if you run it twice
  curl -s http://localhost:8008/api/v1/references | python3 -m json.tool
  ```
  Expect the legacy files listed.
  > If `caget`/`caput` can't find the PVs: `export EPICS_CA_ADDR_LIST=127.0.0.1`
  > (you're on the same host as the IOC).

---

## DoD #1 — Browser: load a legacy reference → ΔX/ΔY populate → re-acquire updates

Open **`http://appsdev2:8008/trajectory.html`** in a browser.

- [ ] Connection dot reads **connected**.
- [ ] Click **▶ Acquire** → status goes **OK**, X/Y trajectory renders (2-panel).
- [ ] Sidebar **Load…** → pick `2025-03-23_12:43:16_reference_trajectory.mat`.
- [ ] **Expect:** layout switches to **4 panels** (X, Y, ΔX, ΔY); sidebar shows
  the filename + source **file**; status header shows a **Δ rms: X=… · Y=… mm** row.
- [ ] Click **▶ Acquire** again.
- [ ] **Expect:** ΔX/ΔY panels + Δrms row **update** to the new deviation.
- [ ] Hover a BPM → tooltip shows X/Y **and** ΔX/ΔY.

---

## DoD #2 — Save a reference; the legacy MATLAB GUI can load it back

This is the cross-tool migration guarantee. **Only MATLAB can confirm it** —
the most likely thing to flag.

- [ ] Sidebar **Save current…** → accept the default name → **Save**. Sidebar
  shows "Saved …".
- [ ] Confirm the file landed:
  ```bash
  ls -la data/references/*reference_trajectory.mat     # new file, ~14 MB
  ```
- [ ] In MATLAB on appsdev2, open `legacy/TxT_GUI/TxT_GUI.mlapp` → click
  **Load Reference from file** → select the file PyTxT just saved.
- [ ] **Expect:** the GUI loads it without error and renders the reference
  trajectory.
  > If MATLAB rejects it, capture the exact error — the save format lives in
  > `save_reference_mat` (`pytxt/domain/reference.py`) and is designed for
  > round-trip compat, but only the real GUI proves it.

---

## DoD #3 — CA-only agent path: load by name → acquire → read diff arrays

Stand-in for an Osprey CA agent (pure `caput`/`caget`):

```bash
caput TxT:CMD:LOAD_REF 2025-03-23_12:43:16_reference_trajectory.mat
caget TxT:STATE:REF_LOADED                 # expect 1
caget TxT:STATE:REF_SOURCE                 # expect "file"
caget TxT:STATE:REF_NAME                   # expect the filename
caput TxT:CMD:ACQUIRE 1
caget TxT:RESULT:BPM:X_DIFF_FIRST_TURN     # expect finite floats (not all NaN)
caget TxT:RESULT:BPM:Y_DIFF_FIRST_TURN
```

- [ ] `REF_LOADED=1`, source `file`, name correct.
- [ ] Both `*_DIFF_FIRST_TURN` waveforms come alive with finite values after acquire.

---

## DoD #4 — REST agent path: list → upload → load → acquire → download round-trip

```bash
# list
curl -s http://localhost:8008/api/v1/references | python3 -m json.tool

# upload a fresh copy under a new name (multipart)
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8008/api/v1/references \
  -F "file=@data/references/2025-03-23_12:43:16_reference_trajectory.mat;filename=agent_upload.mat"
# expect 201

# load it by name
curl -s -X POST http://localhost:8008/api/v1/cmd/load_ref \
  -H 'Content-Type: application/json' -d '{"name":"agent_upload.mat"}'
# expect {"loaded":true,"source":"file", ...}

# acquire
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8008/api/v1/cmd/acquire -d '{}'
# expect 200

# download the bytes back + verify identical
curl -s http://localhost:8008/api/v1/references/agent_upload.mat -o /tmp/dl.mat
cmp data/references/agent_upload.mat /tmp/dl.mat && echo "BYTE-IDENTICAL ROUND-TRIP"
```

- [ ] 201 upload, `loaded:true` load, 200 acquire, `cmp` reports byte-identical.

**Bonus — the new waveform drill-down** (`/result/ref/raw`): PyTxT-saved refs
carry waveforms (→ 200); MATLAB-only legacy files don't (→ 404 with an
explanatory detail). Both behaviors are correct:
```bash
# PyTxT-saved ref currently loaded → 200 with waveforms
curl -s "http://localhost:8008/api/v1/result/ref/raw?bpm=SR01C:BPM1" | head -c 120; echo
# load a legacy MATLAB-only ref, then the same call → 404 explanatory detail
curl -s -X POST http://localhost:8008/api/v1/cmd/load_ref \
  -H 'Content-Type: application/json' -d '{"name":"2025-03-23_12:43:16_reference_trajectory.mat"}' >/dev/null
curl -s "http://localhost:8008/api/v1/result/ref/raw?bpm=SR01C:BPM1"
# expect 404 + "Reference has no full waveforms (loaded from MATLAB-only schema)"
```
- [ ] PyTxT-saved ref → 200; legacy MATLAB-only ref → 404 explanatory detail.

---

## DoD #5 — `/state` reflects the loaded reference + latest diff

```bash
curl -s http://localhost:8008/api/v1/state | python3 -m json.tool
```

- [ ] A `reference` block (`loaded:true`, `source`, `name`, `loaded_at`,
  `n_aligned`) and a `last_diff` block (`x_rms_mm`, `y_rms_mm`, `x_max_abs_mm`,
  `y_max_abs_mm`, `n_valid`) — and the rms values match the browser's Δrms row.

---

## Cleanup

```bash
caput TxT:CMD:CLEAR_REF 1
rm -f data/references/agent_upload.mat /tmp/dl.mat
# delete any throwaway saves you made during DoD #2 if you don't want them kept
```

---

## Results log

Record outcomes here so we can close (or chase) each item.

| DoD item | Pass? | Notes / output / errors |
|---|---|---|
| 0 — bring-up + liveness | ☐ | |
| 1 — browser load → ΔX/ΔY → re-acquire | ☐ | |
| 2 — save → MATLAB GUI loads it back | ☐ | |
| 3 — CA-only load → acquire → diff arrays | ☐ | |
| 4 — REST list/upload/load/acquire/download | ☐ | |
| 5 — /state reflects reference + diff | ☐ | |
| 6 — full test suite green | ✅ | 256 pytest + 6 Playwright, 2026-06-01 (pre-validated) |

**When done:** if 1–5 all pass, Phase 3 is operationally closed — tell me and
I'll mark roadmap DoD §12 complete. If anything fails, paste the row's output
and I'll dig in. The likeliest snag is #2 (MATLAB schema interop).
