# PyTxT Phase 4 — First-Turn Threading (Response-Matrix Correction + Injection Firing)

**Status:** Design (drafted from source-traced investigation; awaiting Kirk's review)
**Date:** 2026-06-01
**Scope:** Phase 4 of 6 (per `PyTxT-project-plan.html`)
**Owner:** Kirk
**Drafted with:** Claude (Opus 4.8)
**Builds on:** [Phase 3 spec](2026-05-29-phase-3-reference-trajectory-design.md)
**Source investigation:** [`docs/phase-4-injection-notes.md`](../../phase-4-injection-notes.md) — the de-boxed `srinjectoneshot`/`steppv`, the threading algorithm (§7), live PV metadata, and corrector envelope. **Read that first; this spec assumes it.**

---

## 1. Purpose

Phase 4 delivers the **correct** half of the operator workflow. Phase 2 reads the first-turn trajectory `B`; Phase 3 compares it to a reference `R0` and publishes `ΔX/ΔY`. Phase 4 closes the loop: given `ΔR = B − R0`, compute corrector-magnet steps via the inverse orbit response matrix and apply them, iterating until the first turn threads onto the reference.

Two capabilities, deliberately separable:

1. **Threading correction** (the analysis half) — pure-domain math: `dΦ = M⁺ · ΔR`, with first-turn-specific downstream-zeroing, applied as incremental HCM/VCM setpoint steps. This is the heart of Phase 4 and is **entirely greenfield** (no pySC/SVD/corrector code exists in PyTxT today).
2. **Injection firing** (the machine-commanding half) — an optional, safety-gated one-shot injection trigger (`CMD:INJECT_ONESHOT`) so PyTxT can drive the arm→fire→read→correct loop itself, rather than relying on top-off or an operator firing externally. **Firing was optional in the legacy GUI** and remains optional here.

This is a faithful port of the legacy `FirstTurnThreading.m` + `SCexp_ALS_*.m` workflow (in `legacy/automated_startup/`), restructured onto PyTxT's domain/adapter architecture.

Phase 4 does **not** introduce closed-orbit (multi-turn) correction, LOCO, or BBA — those are out of scope (§12).

---

## 2. North-star principles binding this design

The five north-star principles (`CLAUDE.md`) continue to apply. Phase 4's concrete obligations — and where it raises the stakes:

- **Agent-callable first** — The two new machine-commanding operations (`CMD:INJECT_ONESHOT`, `CMD:STEP_CM`) and the loop control (`CMD:THREAD_START`/`THREAD_STOP` or `THREAD_STEP`) exist as both CA PVs and REST endpoints through one canonical handler each. The keystone parity test grows accordingly.
- **PVs are the canonical state interface** — Correction state (`STATE:THREAD_*`, last `dΦ` waveforms, last applied setpoints, iteration count, convergence metric) and the injection confirm signal are published as PVs.
- **REST/WS handles only what PVs can't** — The cached response-matrix `M⁺` and the corrector channel catalog are bulk artifacts (REST download / committed files), not PVs. Live commanding stays on PVs.
- **Forward-looking package layout** — New domain modules (`domain/threading.py`, `domain/correctors.py`) and a new `ca_client` writer surface; everything else extends existing packages.
- **Domain logic is I/O-free** — `M⁺ · ΔR`, the downstream-zeroing, the unit/limit clamp math all live in `domain/` with numpy only. The pySC dependency is confined to an **offline** matrix-generation tool, never the runtime path (see Decision D1).

**New stakes:** Phase 4 is the first phase that *commands the accelerator* (writes `TimInjReq`; moves corrector magnets). Every write is gated, idempotent where possible, and confirmed by a state PV. The `OSPREY:TEST:TXT:*` prefix + port isolation (CLAUDE.md) is the hard safety boundary.

---

## 3. What already exists (Phase 1–3, verified 2026-06-01)

From the codebase audit (`docs/phase-4-injection-notes.md` §7):

- **Read path** (`pytxt/ca_client/bpm_reader.py`) is **passive** — reads `wfr:TBT:{c0,c1,c3,armed}`, nm→mm `/1e6`, injection-turn detect. It captures `armed` but does **not** arm, configure triggers, or wait. Phase 4 must add the active acquisition control.
- **Reference + diff** (`pytxt/domain/reference.py`) — `compute_diff(B, R0) → (dx, dy)` already computes the `ΔR` that threading consumes. **Phase 4 builds directly on this.**
- **CMD infrastructure** — handler + REST route + CA putter, with REST↔CA parity tests. New gated commands plug in cleanly.
- **Greenfield:** no pySC, SVD, response matrix, HCM/VCM, or correction math anywhere.

---

## 4. The threading algorithm (ported)

From `legacy/automated_startup/` (full trace in injection-notes §7):

```
# Setup (once):
M  = response matrix          # MODELED via pySC SCgetModelRM(ideal ring, nTurns=1)
Mplus = pinv(M, alpha, damping)   # Tikhonov + damping (SCgetPinv: alpha=1, nSVcut=0, damping=0.5)
R0 = reference first turn          # from Phase 3 reference (measured or loaded)

# Loop (per iteration, legacy maxsteps=6):
B  = acquire first turn            # Phase 2 read path (after arm + optional fire)
dR = stack(B.x, B.y) - stack(R0.x, R0.y);  dR[isnan] = 0
dphi = Mplus @ dR                  # the entire correction — one matmul
# first-turn-specific: zero correctors downstream of the last BPM that saw beam
last = index of last non-NaN BPM;  dphi[correctors beyond last] = 0
dPhiHCM, dPhiVCM = split(dphi)
apply: HCM/VCM setpoint += -dPhi   # incremental, clamped to limits
```

Key facts that shape the design:
- **`M⁺` is computed once and reused** across iterations → it can be generated offline and cached (Decision D1). The runtime loop is a numpy matmul — no pySC needed at runtime.
- **`ΔR` already exists** as Phase 3's diff.
- **Downstream-zeroing** is the one threading-specific nuance — you cannot steer beam past where it was lost.
- **Apply is incremental and in physics units** in the legacy (`steppv('HCM', -dΦ, 'Physics')`). PyTxT folds units into `M⁺` so the runtime works in hardware amps (Decision D2).

---

## 5. Components

### 5.1 Active acquisition (`ca_client`, domain)
Upgrade the read path from passive to active:
- **Setup** (idempotent, once per session/run): write `wfr:TBT:triggerMask`, `EVR:event48trig`, `wfr:TBT:acqCount`, `wfr:TBT:pretrigCount`.
- **Arm**: write `wfr:TBT:arm = 1` per BPM.
- **Wait**: poll `wfr:TBT:armed → 0` (the legacy completion signal; CA monitor preferred over busy-poll) with a timeout.
- Existing read of `c0/c1/c3` + nm→mm + injection-turn detect is unchanged.

### 5.2 Response matrix + pseudo-inverse (offline tool + cached artifact)
- `tools/gen_response_matrix.py` (offline, pySC + AT): load the LOCO lattice (`legacy/automated_startup/lattice/alslat_…124bpms.m`), `SCgetModelRM`, `SCgetPinv` → write `M⁺` (and `M`) to a committed/cached artifact (`.npy` + metadata: lattice id, BPM/CM ordering, alpha/damping/nSVcut, units).
- `domain/threading.py` loads `M⁺` and exposes `calc_cm_step(B, R0, Mplus, bpm_order, hcm_order, vcm_order) → (dPhiHCM, dPhiVCM)` — pure numpy (matmul + downstream-zeroing).

### 5.3 Corrector channel map + envelope (`domain/correctors.py`)
- Ported from `getname_als` corrector branch → `tools/gen_corrector_channels.py` (DONE this session; validates to 96 HCM + 72 VCM). Emits committed `config/hcm_channels.txt` / `vcm_channels.txt` (mirrors `bpm_prefixes.txt`).
- Limits (`local_maxsp`, amps): HCM 35/17/20, VCM 36/14.5/19.98 by position. Clamp applied app-side; record `DRVH/DRVL` is the IOC backstop.
- **Residual to confirm** (read-only `family2dev` dump): the SR01-HCM1 device-list quirk (§ injection-notes §7).

### 5.4 `CMD:STEP_CM` (corrector apply)
- Params `{family: HCM|VCM, deltas: float[], device_list, dry_run}`. Handler: per channel `caget(setpoint_A) + Δ_A → clamp [−max,+max] → caput`. Confirm via `STATE:CM_LAST_APPLIED` readback. Idempotent only in the trivial sense (incremental writes are *not* idempotent — see Decision D5 on retry safety).

### 5.5 `CMD:INJECT_ONESHOT` (optional firing)
- Params `{bucket, gun_bunches, mode, inhibit}`. Handler (from de-boxed `srinjectoneshot`):
  1. **Precondition** (mandatory, new finding): refuse if bucket-loading/top-off active (`bucket:control:cmd == 1`) unless explicitly overridden — `TimInjReq` has a live competing writer.
  2. Read `TimInjReq` (DBF_LONG×7), bump seq#, set `[bucket, gunBunches, mode, inhibit]`.
  3. Sync: wait `EVG:E1:seqBusy` 1→0.
  4. caput `TimInjReq` (7 longs).
  5. caput fine delay `B0215:EVR1-Out:UDC0:Delay-SP` (computed count, clamp 0–1023).
  6. Confirm via the per-shot counter (TBD which — `Evt48Cnt-I`; see §commissioning).
- **`inhibit` default = 1** for the *command* (bumps fire, gun blocked, no new charge) so a casual/agent fire can't dump beam. **But note (Decision D3):** `inhibit=1` perturbs *stored* beam and produces no injected first turn — it is a commissioning/measurement mode. **Real first-turn threading requires `inhibit=0`** (gun fires → fresh bunch → a first turn to steer), which is a separate, harder gate.

### 5.6 Threading loop controller (`handlers`)
- `CMD:THREAD_START {max_steps, gain, fire_each_step, dry_run}` / `CMD:THREAD_STOP`. Orchestrates: (arm → optional fire → read → diff → calc_cm_step → apply) × N. Publishes per-iteration `STATE:THREAD_ITER`, `RESULT:THREAD_RMS`, `dΦ` waveforms. Stop on max_steps and/or convergence (Decision D4).
- Also a single-shot `CMD:THREAD_STEP` for manual/agent-paced operation.

### 5.7 Frontend
- Threading panel: start/stop/step, live RMS-vs-iteration, `dΦ` bar plots (mirror legacy `plotCMstep`), dry-run toggle, prominent safety state.

---

## 6. External surface (PV + REST parity)

| Operation | CA PV | REST | Payload |
|---|---|---|---|
| Step correctors | `CMD:STEP_CM` | `POST /api/v1/cmd/step_cm` | family, deltas, devices, dry_run |
| Fire injection | `CMD:INJECT_ONESHOT` | `POST /api/v1/cmd/inject_oneshot` | bucket, gun_bunches, mode, inhibit |
| Start loop | `CMD:THREAD_START` | `POST /api/v1/cmd/thread_start` | max_steps, gain, fire_each_step, dry_run |
| Stop loop | `CMD:THREAD_STOP` | `POST /api/v1/cmd/thread_stop` | — |
| Single step | `CMD:THREAD_STEP` | `POST /api/v1/cmd/thread_step` | (uses loaded config) |
| State | `STATE:THREAD_ACTIVE`, `STATE:THREAD_ITER`, `STATE:CM_LAST_APPLIED`, `STATE:INJECT_LAST_SEQ` | (mirrored) | — |
| Results | `RESULT:THREAD_RMS`, `RESULT:CM:{H,V}_LAST_STEP` (waveforms) | (mirrored) | — |

---

## 7. Safety model

- **All commanding behind the test prefix** (`OSPREY:TEST:TXT:*`) + port isolation until explicitly promoted to production `TxT:*`. Config-driven from day 1 (already the pattern).
- **`dry_run` everywhere** — every commanding CMD supports a dry-run that computes + publishes the intended writes without issuing them. Default for the first frontend cut.
- **Hard preconditions**: injection refuses during active top-off; CM steps clamp to limits and refuse out-of-range device lists.
- **Default to no-beam for the command**: `inhibit=1` / Mode 42 (stored-beam bump response; commission the pipeline here first). Real threading (`inhibit=0`) is separately gated — see D3.
- **Confirm-before-trust**: every write has a state-PV readback; the loop verifies each apply landed before the next iteration.

---

## 8. Open design decisions (to resolve in review → logged in decisions file)

- **D1 — `M⁺` runtime source:** cache an offline-generated matrix (recommended; no runtime pySC) vs. integrate pySC at runtime. *Recommendation: cache.*
- **D2 — units convention:** fold amps↔kick into the offline `M⁺` so runtime is hardware-amps end-to-end (recommended) vs. port `amp2k`/`k2amp` to runtime. *Recommendation: fold into M⁺.*
- **D3 — firing mode:** `inhibit=1` and real threading are *different modes* (correction to an earlier conflation). `inhibit=1` = bumps on stored beam, no first turn → commissioning/measurement only. `inhibit=0` = gun fires → the injected first turn that threading actually steers. *Recommendation: `CMD:INJECT_ONESHOT` defaults to `inhibit=1`; commission the whole pipeline in `inhibit=1`; real threading uses `inhibit=0` behind explicit operator sign-off + test→prod prefix promotion.*
- **D4 — loop termination:** keep legacy fixed `max_steps=6` vs. add an RMS-convergence/divergence stop. *Recommendation: max_steps + divergence guard + optional convergence early-exit.*
- **D5 — retry safety:** incremental CM steps are not idempotent; define the retry contract (e.g. each CMD carries an expected-prior-setpoint or a step-id to reject double-apply).
- **D6 — bucket default:** 308 (legacy TxT) vs 1 (`bpm_check_tbt`). *Needs operator input.*

---

## 9. Operator/control-room inputs still needed

1. One-shot `camonitor` capture (commissioning) — confirm `seqBusy` toggles and which counter is the per-shot confirm signal.
2. Read-only `family2dev('HCM')`/`('VCM')` dump — confirm SR01-HCM1 device list.
3. Interlock/precondition list for firing (gun permit, shutters, mode) beyond `bucket:control:cmd`.
4. Sign-off on `inhibit=1` default and corrector limit authority.

---

## 10. Testing strategy

- **Domain (ms-fast, numpy only):** `calc_cm_step` correctness incl. downstream-zeroing edge cases (beam lost at BPM k → correctors > k zeroed); clamp math; unit folding. Golden-vector test against a saved legacy `dΦ` if available.
- **Fake-IOC integration:** extend `tests/fixtures/fake_bpm_ioc.py` with `TimInjReq`, `seqBusy`, corrector setpoint records → test arm/wait, INJECT_ONESHOT sequence (incl. seqBusy sync + precondition refusal), STEP_CM clamp + readback.
- **Parity:** every new CMD in the REST↔CA parity test.
- **Loop:** dry-run loop over synthetic injected error converges RMS downward over iterations.

---

## 11. Milestone breakdown (proposed)

- **M1** — Active acquisition (arm/setup/wait) + offline `M⁺` generator + cached artifact + `calc_cm_step` domain (dry-run only, no commanding).
- **M2** — `CMD:STEP_CM` (corrector apply + clamp + confirm) behind test prefix; corrector channel catalog committed.
- **M3** — `CMD:INJECT_ONESHOT` (de-boxed sequence + precondition + confirm).
- **M4** — Threading loop controller + frontend panel + e2e.

---

## 12. Out of scope

Closed-orbit (multi-turn) correction; LOCO; BBA; bunch cleaning; gun-bias/fill-pattern automation; real-injection (`inhibit=0`) as a default path (it remains an explicitly separate, hard-gated capability if added at all).

---

## 13. Provenance

Every machine-facing fact in this spec is sourced and recorded in `docs/phase-4-injection-notes.md` (de-boxed via the `mml-audit` MCP server + live `caget` on appsdev + the local `legacy/` tree). No fact here is assumed; the residuals are explicitly listed in §9.
