# Phase 4 pre-design notes — injection, the two MML "black boxes", and scope

**Status:** scoping notes, not a spec. Captured 2026-06-01 while tracing how the
legacy MATLAB tool fires injection, because the source lives only in the
**gitignored** `legacy/` tree (the unpacked `TxT_GUI.mlapp` callbacks +
`automated_startup/SCexp_ALS_*.m`) and is therefore not recoverable from the
tracked repo. Read this before writing the Phase 4 design spec.

---

## TL;DR

- The legacy TxT GUI **can** fire a one-shot injection, but firing is an
  **optional, checkbox-toggled step** in an acquisition chain — not mandatory.
- Therefore `srinjectoneshot` (fire injection) and `steppv` (apply corrector
  steps) are **optional, machine-commanding conveniences**, not blockers for the
  core analysis workflow. PyTxT already implements the passive path.
- Both are **external MML toolbox functions** — their PV writes are not in the
  repo. De-boxing them is a Phase-4 task, and they are the only two operations
  that actually *command* the accelerator → hard safety gating required.

---

## 1. How the legacy GUI actually acquires

The main `TxT_GUI.mlapp` orchestrates acquisition through
`run_injection_chain_Pushed`, a loop of **independently enabled** steps:

```matlab
function run_injection_chain_Pushed(app, event)
   while 1
      fprintf('Injecting...\n')
      if app.enable_arm_BPMs.Value      % checkbox
         run_arm_bpmsButtonDown(app)    % → SCexp_ALS_armBPMs
      end
      if app.enable_inject.Value         % checkbox  ← FIRING IS OPTIONAL
         run_inject_beam(app)            % → SCexp_ALS_injectBeam → srinjectoneshot
      end
      if app.enable_bunch_clean.Value    % checkbox
         run_bunch_cleaning(app)         % → SCexp_ALS_setbunchcleaning_local
      end
      ...   % then readout + plot
```

Readout is a *separate* callback: `runButton_readout_BPMsPushed` →
`SCexp_ALS_readoutBPMs` → reads the TBT waveforms → `update_plot_trajectories`.

### Two operating modes

| Mode | `enable_inject` | What happens |
|---|---|---|
| **GUI-fires** | checked | GUI arms, fires one shot via `srinjectoneshot`, reads, analyzes. Self-contained. |
| **Passive / readout** | unchecked | GUI arms + reads + analyzes; **injection comes from elsewhere** (top-off, operator firing it another way). |

**PyTxT today already implements the passive mode end to end** — Phase 2 acquire
= read TBT + extract first turn; Phase 3 = reference overlay + ΔX/ΔY diff. An
operator can run PyTxT against an injecting ring right now and get the full
trajectory + deviation analysis with no injection-firing code.

---

## 2. The acquisition sequence, PV by PV (the parts we KNOW)

From `SCexp_ALS_setupBPMs.m`, `armBPMs.m`, `readoutBPMs.m`. BPM names carry a
`:SA:X`-style channel suffix in MML; the code strips the last 4 chars
(`Names{loop}(1:end-4)`) to get the `wfr:`/`EVR:` device root. (PyTxT's
`canonicalize_bpm_name` already handles the analogous suffix.)

1. **Setup / trigger config** (once):
   - `wfr:TBT:triggerMask = 0b01000000` (`bin2dec('01000000')`)
   - `EVR:event48trig    = 0b01000000` → **BPMs latch on timing event 48**
2. **Arm** (per shot): `wfr:TBT:arm = 1`
3. **Fire** (optional): `srinjectoneshot(...)` — black box (§3)
4. **Wait for completion**: poll `wfr:TBT:armed` until 0 (`while getpv(...armed)`)
5. **Read out** per BPM:
   - X: `wfr:TBT:c0` → `/1e6` (nm→mm) → minus `XGolden`
   - Y: `wfr:TBT:c1` → `/1e6` (nm→mm) → minus `YGolden`
   - Sum: `wfr:TBT:c3`

> Note: PyTxT's read path already consumes `c0/c1/c3` and the nm→mm `/1e6`
> convention (see Phase 2). The `XGolden`/`YGolden` golden-orbit subtraction is a
> Phase-4/5 concern — the reference-diff in Phase 3 is the PyTxT analogue done in
> the domain layer rather than at read time.

---

## 3. Black box #1 — `srinjectoneshot` (fire one injection pulse)

**Not defined anywhere in the repo** — an external ALS MML toolbox function. We
only have the call signature and operational comments.

```matlab
% from SCexp_ALS_injectBeam.m (reads SC.EXP.INJ.* set by the GUI options panel)
srinjectoneshot(nBucket, nBunches, injFlag, blockGun);
%                308       4         40       0
```

| Arg | Value | Meaning |
|---|---|---|
| `nBucket` | 308 | RF bucket to inject into; TBT BPMs are timed for bucket 308 |
| `nBunches` | 4 | Inject 4 bunches → larger BPM signal to thread on |
| `injFlag` | 40 | Injection mode; 40 = "all the way into the storage ring" |
| `blockGun` | 0 | 0 = let the gun fire; 1 = block it |

After firing, the legacy code `pause(1.4)` to let TBT acquisition finish.

The GUI exposes these via `options_injectBeam.mlapp` →
`update_SC_from_inj_options(...)` → `SC.EXP.INJ.*`.

**Strong clue to what it pokes:** the BPMs latch on **event 48**
(`EVR:event48trig`), so `srinjectoneshot` almost certainly arranges a **one-shot
event-48 fire** through the timing system / event generator (EVG), plus sets
bucket / fine-delay, bunch count, injection mode, and gun enable. Exact PV
names + values are unknown (hidden by the wrapper).

---

## 4. Black box #2 — `steppv` (apply a corrector-magnet step)

The Phase-4 *correction* primitive (used in `FirstTurnThreading*.m`). Also an
external MML function — PV writes not in the repo.

```matlab
steppv('VCM', 5,        [5 1]);     % step VCM #5 by 5 (units?)
steppv('HCM', -dPhiHCM, hcmlist);   % step a list of HCMs by computed amounts
steppv('VCM', -dPhiVCM, vcmlist);
```

Signature ≈ `steppv(family, amount, indexSpec)`. It wraps the corrector setpoint
PVs (HCM/VCM) so the threading loop can nudge magnets after the SVD pseudo-inverse
computes a correction. Same de-box problem as §3.

---

## 5. De-boxing plan (Phase 4 M1)

For each of `srinjectoneshot` / `steppv`, in rough order of confidence:

1. **`type srinjectoneshot` / `which srinjectoneshot`** in MATLAB on a
   control-room host → read the `setpv`/`caput` calls inside. Definitive.
2. **Cross-check with the timing/EVG group** on the event-48 one-shot path
   (bucket select, fine delay, bunch count, gun enable).
3. **`camonitor`** the injection/timing (or corrector) PVs while running one
   shot / one step → diff the writes.
4. Model in PyTxT as a **gated command** (e.g. `CMD:INJECT_ONESHOT` with
   bucket/bunches/mode/blockGun params; `CMD:STEP_CM` with family/amount/index)
   → handler does the CA write sequence → a state PV confirms → same
   agent-callable + parity pattern as every other CMD.

---

## 6. Scope implication for the Phase 4 spec

Phase 4 splits more cleanly than "port FirstTurnThreading wholesale":

- **Analysis half** (response matrix, SVD pseudo-inverse, the threading math via
  pySC) — pure-domain, I/O-free, testable without the machine. No black boxes.
- **Machine-commanding half** (`srinjectoneshot` fire + `steppv` apply) — the
  only operations that perturb the accelerator. Both were **optional** in the
  original GUI, so PyTxT can:
  - ship the analysis + the passive workflow first, and
  - put firing / CM-apply behind explicit, hard safety gating (the
    `OSPREY:TEST:TXT:*` test-prefix + port isolation in CLAUDE.md exists for
    exactly this), or even descope them for an initial Phase-4 cut.

This is the opposite of treating `srinjectoneshot` as a Phase-4 blocker. It's an
optional, well-bounded, safety-critical add — not a prerequisite for value.

---

## Sources (all gitignored — local only)

- `legacy/TxT_GUI/TxT_GUI.mlapp` (unpacked: `run_injection_chain_Pushed`,
  `run_inject_beam`, `runButton_readout_BPMsPushed`, `enable_*` toggles)
- `legacy/TxT_GUI/_unpacked/options_injectBeam.m`
- `legacy/automated_startup/SCexp_ALS_injectBeam.m` (the `srinjectoneshot` call)
- `legacy/automated_startup/SCexp_ALS_{setupBPMs,armBPMs,readoutBPMs}.m`
- `legacy/automated_startup/FirstTurnThreading*.m` (`steppv`, threading loop)
