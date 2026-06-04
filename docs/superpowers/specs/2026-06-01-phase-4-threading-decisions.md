# Phase 4 — Implementation Decisions Log

Companion to: [`2026-06-01-phase-4-threading-design.md`](2026-06-01-phase-4-threading-design.md)

Append-only log of implementation-time decisions: choices made during coding that weren't in the spec, deviations from the spec, surprises discovered, and tradeoffs taken. Read this alongside the spec for the full picture of what was actually built and why.

## How to use this log

- **One entry per non-trivial decision.** Skip decisions fully covered by the spec; this log is for the deltas.
- **Add entries chronologically**, newest at the bottom.
- **Each entry uses the template below.** Keep entries terse — the goal is a quick read, not exhaustive prose.
- **If a decision invalidates a spec section, update the spec too** (not just log it here). The log is for context; the spec is authoritative.
- **When in doubt, log it.** Future you (and future agents) will thank present you.

## What counts as a non-trivial decision worth logging

- A choice made because the spec was silent on it (filled a gap).
- A deviation from what the spec said (with reason).
- A tradeoff taken (we chose X over Y because Z, where the spec didn't pick).
- A surprise from real code, real CA traffic, real data shapes, or real upstream APIs.
- A library or dependency choice made during implementation.
- An ergonomic refactor extracted during the work (a helper, a shared utility, a pattern).
- A test infrastructure shortcut or workaround.

## What does NOT need to be logged

- Pure bug fixes inside spec'd code.
- Decisions explicitly documented in the spec.
- Style preferences and formatting.
- One-off renames or trivial code shape changes.

---

## Entry template (copy when adding)

```markdown
## YYYY-MM-DD — <short title>

**Context:** What was being implemented when this came up (file/function/milestone).

**Decision:** The choice made (one or two sentences).

**Why:** Rationale, alternatives considered, tradeoffs.

**Spec relationship:** Extends §X / Deviates from §X / Fills gap (spec was silent on this).

**Forward impact:** Does the spec need updating? Does later code need to know? Any follow-ups? Tag with `[needs-spec-update]` if the spec is now out of sync.
```

---

## 2026-06-01 — Pre-implementation: open design decisions carried from the spec

**Context:** Spec drafted from the source-traced investigation (`docs/phase-4-injection-notes.md`). These are the design choices the spec §8 flags as needing resolution before/during M1–M4. Logged here so the resolutions land in one place as implementation proceeds.

**Decision:** Recommendations recorded; final calls pending Kirk's review:
- **D1 (M⁺ runtime source):** cache an offline-generated matrix; no pySC at runtime. *Recommended.*
- **D2 (units):** fold amps↔kick into offline M⁺; runtime is hardware-amps. *Recommended.*
- **D3 (firing mode):** *Corrected from an earlier conflation.* `inhibit=1` (bumps on stored beam, no first turn) = commissioning/measurement only; **real first-turn threading needs `inhibit=0`** (gun fires). Rec: command defaults to `inhibit=1`; commission pipeline in `inhibit=1`; real threading uses `inhibit=0` behind operator sign-off + prefix promotion. Spec §5.5/§7/§8 + injection-notes updated 2026-06-01.
- **D4 (loop termination):** `max_steps` + divergence guard + optional RMS-convergence early-exit. *Recommended.*
- **D5 (retry safety):** incremental CM steps are non-idempotent — retry contract TBD (step-id or expected-prior-setpoint guard).
- **D6 (bucket default):** 308 vs 1 — needs operator input.

**Why:** Captured up front because each materially shapes M1–M4 code structure (esp. D1/D2 determine whether pySC is a runtime dependency at all).

**Spec relationship:** Mirrors design §8.

**Forward impact:** Convert each to a dated resolution entry when decided. D5 must be resolved before M2 (STEP_CM). D6 and the §9 operator inputs gate M3 (INJECT_ONESHOT).

---

## 2026-06-01 — Corrector channel-name port (pre-M2)

**Context:** Needed the literal SR HCM/VCM setpoint PV names; `getname_als.m` builds them programmatically (no static catalog upstream).

**Decision:** Ported the corrector branch of `getname_als.m` (Setpoint/'AC' type) to `tools/gen_corrector_channels.py` rather than depend on a MATLAB dump.

**Why:** No-MATLAB, reproducible in-repo, mirrors how `config/bpm_prefixes.txt` was produced. The port self-validates: it emits exactly 96 HCM + 72 VCM, matching `mml-audit get_family` device counts (a wrong formula wouldn't).

**Spec relationship:** Implements design §5.3.

**Forward impact:** One residual — `local_maxsp` errors "Sector 1, HCM1 missing" yet the count is 96 with dev1-8×12. Confirm the SR01 device list via a read-only `family2dev('HCM')` dump before committing `config/hcm_channels.txt`. `[needs operator input]`

---

## 2026-06-04 — D1–D6 resolved (Kirk)

**Context:** Open design decisions from the 2026-06-01 pre-implementation entry, ratified before M1 starts.

**Decision:** All six closed:
- **D1 (M⁺ runtime source): RESOLVED — cache an offline-generated matrix; pySC has zero runtime footprint.** pySC is a **dev-only/offline** tool that generates the matrix to a file; it is never in the deployed app, container, or runtime requirements. The runtime thread loop is a pure numpy matmul against the cached matrix. *How the matrix is generated (modeled via pySC vs. measured empirically) is deferred* — the lattice-modeling decision is not needed yet; only the runtime contract (load a cached file, no pySC) is locked.
- **D2 (units): RESOLVED — fold amps↔kick into the offline M⁺.** Cached matrix maps BPM-mm → corrector-amps directly; runtime CM-apply is `caget(setpoint_A) + delta_A → clamp → caput`, no energy-dependent conversion in the hot path.
- **D3 (firing mode): RESOLVED — default `inhibit=1`, with `inhibit=0` (real gun fire) a first-class supported path behind operator sign-off + prefix promotion.** The gun-fire capability is explicitly wanted, not deferred; it is gated, not omitted.
- **D4 (loop termination): RESOLVED — `max_steps` (hard cap) + divergence guard (bail if RMS worsens) + optional RMS-convergence early-exit.**
- **D5 (retry safety): RESOLVED — Option B, expected-prior-setpoint guard (compare-and-set).** `CMD:STEP_CM` carries the expected current setpoint per channel; the handler applies the incremental delta only if the live readback matches within tolerance, else refuses loudly. Stateless (survives IOC restart) and guards against *all* competing writers (top-off, operators, other agents), not just self-retry — the live-competing-writer hazard from the injection notes is the deciding factor. A step-id *may* additionally be carried for dedup/logging ergonomics, but CAS is the safety mechanism.
- **D6 (bucket default): RESOLVED — default bucket 308** (the value the legacy TxT GUI uses; PyTxT is its port). The bucket-1 calls in `bpm_check_tbt.m`/`gettune_kicker.m` are *different* tools (BPM-check, tune meas.), not the threading workflow, and the live `caget` values (57/260) were just top-off in flight — neither is a counter-argument to 308. Residual: a one-line operator confirmation that 308 still matches current TBT-BPM timing (folds into the §9 control-room confirms), not an open choice.

**Why:** D1 keeps the deployed app small and dependency-light (pySC is heavy); the generation-method choice is genuinely separable and not yet needed. D2 makes the runtime CM-apply trivial and unit-safe. D3 keeps the dangerous path available but un-fireable by accident. D5 Option B beats the step-id ledger because the real hazard is competing writers, which only compare-and-set catches, and it's stateless. D6 had no real ambiguity once the bucket-1 sources were identified as unrelated tools.

**Spec relationship:** Resolves design §8 (D1–D6). `[needs-spec-update]` — fold these resolutions into §5.5 (M⁺ runtime contract), §6 (CM-apply units + CAS guard on `CMD:STEP_CM`), §7 (firing modes), and the §8 decision table so the spec reads as decided rather than open.

**Forward impact:** M1 can proceed (runtime = cached-matrix numpy, no pySC). M2 (`CMD:STEP_CM`) implements the CAS guard from D5. M3 (`CMD:INJECT_ONESHOT`) defaults bucket 308 + `inhibit=1`. Remaining operator confirms (D6 timing check, §9 one-shot `camonitor`, SR01 HCM1 device list) are independent of these and still pending.

---

## 2026-06-04 — M1 implementation (domain + artifact + active acquisition)

**Context:** Built M1 — `pytxt/domain/threading.py` (pinv + calc_cm_step),
`pytxt/domain/response_matrix.py` (artifact I/O), and the active-acquisition path
in `pytxt/ca_client/bpm_reader.py`. 28 new tests, all green; full suite 284 passed.

**Decisions / gap-fills / deviations:**
- **Loop gain lives in the loop, not the cached matrix (deviation from spec §4/§5.2).**
  `tikhonov_pinv` defaults `damping=1.0` so the cached M⁺ is a *pure* regularized
  inverse; the runtime loop gain (legacy `damping=0.5`) is applied at call time via
  `calc_cm_step(..., gain=)`. Spec/legacy folded 0.5 into M⁺. Reason: keeps one cached
  artifact reusable across gain choices and makes the D4 loop-gain knob authoritative.
  Pass `damping=0.5` to `tikhonov_pinv` to reproduce legacy exactly.
- **Downstream-zeroing needs s-positions → artifact carries `bpm_s`/`cm_s` (gap-fill).**
  Spec named downstream-zeroing but not how the ordering reaches the runtime. The
  `ResponseMatrix` artifact now stores monotone s-positions; `calc_cm_step` zeroes
  correctors with `cm_s > s(last BPM that saw beam)`. `beam_seen_mask` is an explicit
  arg (inferred from non-NaN dx if omitted).
- **Artifact format = single `.npz` (gap-fill).** Spec said "cache the matrix" without
  a format. Chose one `np.savez` archive (mplus + s-positions + name arrays + units +
  energy + provenance) with shape-consistency validation on load (fails loudly).
- **pySC generation deferred → synthetic generator stands in.**
  `tools/gen_synthetic_response_matrix.py` builds a format-identical artifact from a
  random plant so the runtime/loop are exercisable now without pySC (per D1; "lattice
  modeling later" per Kirk). Provenance string marks synthetic matrices unmistakably.
- **`BpmReader` gains an active path; control PVs resolve lazily (gap-fill, keeps passive
  path intact).** Added `setup()`/`arm()`/`wait_until_ready()` porting
  `SCexp_ALS_{setupBPMs,armBPMs,readoutBPMs}.m`. Control PVs (`wfr:TBT:arm`,
  `:triggerMask`, `:acqCount`, `EVR:event48trig`) are resolved on first active use so
  the existing read-only callers/tests never touch them. Trigger mask + event-48 =
  `0b01000000`, acqCount 100000 — verbatim from legacy.
- **`setup()` does NOT write `attenuation`/`buttonDSP` (deviation from legacy
  setupBPMs.m).** Those change BPM gain state; deferred until an operator confirms the
  desired attenuation policy (control-room checklist). Easy to add as a setup() kwarg.
- **Fake IOC extended** with the four control records + a `stuck_armed` fixture option
  (armed=1 forever) to exercise the `wait_until_ready` timeout path. Also removed three
  pre-existing unused imports flagged by ruff while editing the file.

**Spec relationship:** Implements §5.1, §5.2; the damping/gain split refines §4/§5.2
(loop owns gain). `[needs-spec-update]` minor: note the artifact carries s-positions and
that damping defaults to 1.0 in the generator.

**Forward impact:** M2 (`CMD:STEP_CM`) and M4 (loop controller) consume `calc_cm_step`
+ `ResponseMatrix` directly. Real-machine arm validation + the attenuation policy are
control-room items (checklist B3). Real modeled/measured matrix generation (pySC) remains
the one deferred M1-adjacent piece.
