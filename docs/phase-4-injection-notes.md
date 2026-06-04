# Phase 4 pre-design notes — injection, the two MML "black boxes", and scope

**Status:** scoping notes, not a spec. Originally captured 2026-06-01 while
tracing how the legacy MATLAB tool fires injection. **Updated 2026-06-01** after
reading the *actual* `srinjectoneshot` / `steppv` source via the **mml-audit MCP
server** (full live ALS Middle Layer tree, 2424 `.m` files) — both "black boxes"
are now fully de-boxed (§3, §4). Read this before writing the Phase 4 design spec.

---

## TL;DR

- The legacy TxT GUI **can** fire a one-shot injection, but firing is an
  **optional, checkbox-toggled step** in an acquisition chain — not mandatory.
  `srinjectoneshot` / `steppv` are **optional, machine-commanding conveniences**,
  not blockers. PyTxT already implements the passive path.
- **Both functions are now de-boxed from the live MML tree** and turn out to be
  thin wrappers over plain CA writes — **no MML magic, no MATLAB dependency**:
  - `srinjectoneshot` = caget `TimInjReq` waveform → bump seq# + set
    bucket/bunches/mode/inhibit → **sync on `EVG:E1:seqBusy` (1→0)** → caput
    `TimInjReq` → caput a fine-delay PV. **PyTxT's caproto CA client can
    reimplement this natively** (§3).
  - `steppv` = literally `setpv('Inc', varargin{:})` — an incremental setpoint
    write. Not a black box at all (§4).
- **Safety / commissioning mode (NOT the threading mode — see ⚠️):** firing with
  **`InhibitFlag = 1`** (or **Mode 42** = "just the SR bumps") runs the
  kicker/bump timing sequence **without triggering the gun → no new charge**. This
  is how `bpm_check_tbt.m` measures *stored-beam* bump response. It's the safe way
  to commission PyTxT's arm/read/apply/timing pipeline. ⚠️ **But it produces no
  injected first turn** — real first-turn threading needs `InhibitFlag = 0` (gun
  fires → fresh bunch → a first turn to steer). `inhibit=1` ≠ threading. (Note:
  `gettune_kicker.m` actually uses `inhibit=0`; only `bpm_check_tbt` uses 1.)
- These two are still the only operations that *command* the machine → keep the
  hard safety gating, but the de-box removes the "unknown PV writes" risk.

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

## 3. ~~Black box~~ #1 — `srinjectoneshot` (fire one injection pulse) — DE-BOXED

**Found in the live MML tree** at `machine/ALS/Common/srinjectoneshot.m` (120
lines, by Greg Portmann; comment: *"used for the topoff application, be careful
editing"*). Real signature:

```matlab
function Req = srinjectoneshot(BucketNumber, GunBunches, Mode, InhibitFlag)
```

So the legacy GUI's `srinjectoneshot(308, 4, 40, 0)` means bucket 308, 4 gun
bunches, **Mode** 40, **InhibitFlag** 0 — note arg 3 is the *mode*, arg 4 is the
*gun inhibit*:

| Arg | Meaning | Values |
|---|---|---|
| `BucketNumber` | SR RF bucket (1–328) | TBT BPMs timed for the chosen bucket |
| `GunBunches` | gun bunches (1–16) | more bunches → larger BPM signal |
| `Mode` | injection mode | 0 default · 10 LTB · 20 BR · 30 BTS · **40 SR injection** · 41 SR-inj prep · **42 just the SR bumps** |
| `InhibitFlag` | gun inhibit override | **0 = gun fires** (real injection) · **1 = gun blocked** (bumps/kickers fire, no new charge) |

### What it actually does (the whole body, paraphrased)

```matlab
Req = getpv('TimInjReq');            % current 7-element request waveform
Req(7) = Req(7)+1;  if Req(7)>20000, Req(7)=1; end   % bump sequence number
Req(1:4) = [BucketNumber GunBunches Mode InhibitFlag];

% --- sync to the timing sequencer's "read window" so the request isn't dropped ---
while ~getpv('EVG:E1:seqBusy'); end  % wait for seqBusy -> 1
while  getpv('EVG:E1:seqBusy'); end  % then wait for seqBusy -> 0  (Evt 38 window)

setpvonline('TimInjReq', Req(:)');   % <-- THE fire: load the request waveform
pause(.05);
BR_KE_FineDelay = 100*8*rem(31.25*rem(21*BucketNumber,328),1);  % 10 ps step
setpvonline('B0215:EVR1-Out:UDC0:Delay-SP', BR_KE_FineDelay);   % extraction fine delay
```

**Key insight:** it does **not** poke event 48 directly. It loads a request into
the **`TimInjReq`** waveform PV; the EPICS timing sequencer then runs the full
sequence (~0.88 s later), which *includes* event 48 (BR Extraction Kicker —
confirmed by `synctoevt.m`'s event table: `48 → 'B0215:EVR1:Evt48Cnt-I', 'BR
Extraction Kicker'`). The SR BPMs latch on that event-48 fire. So:

- **The injection-trigger PV PyTxT needs is `TimInjReq`** — a 7-element waveform:
  `[bucket, gunBunches, mode, inhibit, IFGD(unused), EFGD(unused), seqNum]`.
- **The gate is `EVG:E1:seqBusy`** — you must wait for a 1→0 transition before
  writing, or the request is dropped (timing-system sync requirement).
- The fine-delay write (`B0215:EVR1-Out:UDC0:Delay-SP`) is a deterministic
  function of bucket number — pure arithmetic, reproducible in Python.

All of this is plain CA — **PyTxT's caproto CA client can do every step
natively.** No MML / MATLAB runtime needed.

### Live record metadata — verified on appsdev 2026-06-01 (`cainfo`/`caget`)

The IOC record definitions (not in the MML repo — they live in the timing IOC's
EPICS db) were read directly off the live system:

| PV | Native type | Count | Notes |
|---|---|---|---|
| `TimInjReq` | **`DBF_LONG`** | **7** | write **7 integers** from caproto. No record clamping (ctrl limits 0/0) → bucket/mode validation is *our* responsibility. Live value `[57, 4, 40, 0, 0, 0, 19133]` confirms element order `[bucket, gunBunches, mode, inhibit, 0, 0, seqNum]`. |
| `EVG:E1:seqBusy` | `DBF_DOUBLE` | 1 | the gate; 0/1. Host `b04lx-dpsc.als.lbl.gov`. Source confirmed. |
| `EVG:E1:seqStatus` | `DBF_LONG` | 1 | bitfield (alt path) — not needed; `seqBusy` is the gate. |
| `B0215:EVR1-Out:UDC0:Delay-SP` | **`DBF_LONG`** | 1 | **raw counts 0–1023** (10 ps/count), **record clamps at 1023**. The `100*8*rem(...)` formula yields the integer count (range 0–800, in-range), *not* ps. |
| `B0215:EVR1:Evt48Cnt-I` | `DBF_DOUBLE` | 1 | confirm-signal candidate; live + incrementing. |
| `LI11:EVR1:Evt10Cnt-I` | `DBF_DOUBLE` | 1 | start-of-sequence counter (`synctoevt(10)`). |
| ~~`TimSeqState`~~ | — | — | **does not exist live** — stale name in `ReadMe_TimingSystem.m`; drop it. |

> ⚠️ **`TimInjReq` has a live competing writer.** During the read, element 1 went
> 260→57 and seqNum 19128→19133 in seconds, with `Evt48Cnt` climbing — i.e. the
> ring was **actively topping off** (mode 40, gun firing, inhibit 0). So a PyTxT
> caput to `TimInjReq` *races top-off*. This makes the precondition mandatory, not
> optional: `CMD:INJECT_ONESHOT` **must** check bucket-loading/top-off state
> (`bucket:control:cmd`) and refuse-or-coordinate, exactly as
> `Injection_MRF_Pulsed.m` stops bucket loading first. The `seqBusy` sync alone
> does not make two writers safe.

### Confirmed by two independent callers (the legacy analogue of PyTxT itself)

`machine/ALS/Common/BPM/bpm_check_tbt.m` and
`machine/ALS/StorageRing/gettune_kicker.m` both run *exactly* PyTxT's intended
loop: configure BPM `wfr:TBT` + `EVR:event48trig = 0b01000000` → `wfr:TBT:arm 1`
→ `srinjectoneshot(1, 1, 40, InhibitFlag)` → `synctoevt(48)` and/or poll
`wfr:TBT:armed` until 0 → `bpm_gettbt(...)`. `bpm_check_tbt` uses
**`InhibitFlag = 1`** (measure trajectory with no beam dump). This is the
turn-by-turn workflow PyTxT is porting, end to end.

> Simpler firing path also seen in `ReadMe_TimingSystem.m`: just
> `Req=getpv('TimInjReq'); Req(7)+=1; Req(1:4)=[...]; setpv('TimInjReq', Req)` —
> i.e. the seqBusy sync is a robustness nicety (avoid dropped requests), not
> strictly required to fire. PyTxT should still do the sync for reliability.

---

## 4. ~~Black box~~ #2 — `steppv` (apply a corrector-magnet step) — DE-BOXED

**Found at `mml/steppv.m` — 17 lines, and the body is one line:**

```matlab
function ErrorFlag = steppv(varargin)
%STEPPV - Incremental setpoint change of a process variable or simulated value
%  ErrorFlag = steppv(FamilyName, Field, DeltaSP, DeviceList, WaitFlag)
%  ErrorFlag = steppv(DataStructure, WaitFlag)
%  ErrorFlag = steppv('ChannelName', DeltaSP)
ErrorFlag = setpv('Inc', varargin{:});   % 'Inc' = incremental flag
```

So `steppv` is just `setpv` with an **incremental** flag — `NewSP = currentSP +
DeltaSP`. (The Phase-4 calls `steppv('HCM', -dPhiHCM, hcmlist)` /
`steppv('VCM', -dPhiVCM, vcmlist)` reduce to: read each corrector's current
setpoint, add the SVD-computed delta, write it back.) Note arg 2 in the
family-form is `Field` (e.g. `'Setpoint'`), not the delta — earlier guess of
`steppv(family, amount, indexSpec)` was missing the `Field` arg.

**For PyTxT:** a CM step is `caget(setpoint) + delta → caput(setpoint)` per
selected HCM/VCM channel. Pure CA, fully reproducible in the domain/adapter
layers. `setpv` itself resolves family+field+devicelist → channel names via the
AO (`family2channel`), then `setpvonline` (= caput) — PyTxT already owns the
BPM-name→channel mapping pattern and can hold an HCM/VCM channel map the same way.

---

## 5. ~~De-boxing plan~~ → Implementation notes (Phase 4 M1)

De-boxing is **done** (§3, §4 above, sourced from the live MML tree). What
remains is implementing the CA sequences in PyTxT and gating them. Open items
still worth a control-room check:

1. ✅ **DONE 2026-06-01** — PV names + record metadata verified live (see the
   "Live record metadata" table in §3). `TimInjReq` = `DBF_LONG`×7, gate
   `EVG:E1:seqBusy` = `DBF_DOUBLE` 0/1, fine delay = `DBF_LONG` counts 0–1023,
   `TimSeqState` does not exist.
2. **Still live-only — the one-shot `camonitor` capture** (needs an operator):
   fire one `srinjectoneshot(1,1,40,1)` while monitoring `TimInjReq`,
   `EVG:E1:seqBusy`, the delay-SP, `Evt48Cnt-I`, `Evt10Cnt-I`. Resolves: does
   `seqBusy` actually toggle 1→0, and **which counter reliably ticks per shot**
   (the confirm signal). Everything *static* is already pinned.
3. **Pick the safe default for PyTxT threading:** fire with `InhibitFlag = 1`
   (or Mode 42) for trajectory measurement without injecting charge; reserve
   `InhibitFlag = 0` (real injection) for an explicit, separately-gated path.
4. **Mandatory precondition (new finding):** the ring tops off on `TimInjReq`
   continuously, so `CMD:INJECT_ONESHOT` must check/stop bucket loading
   (`bucket:control:cmd`) before writing — `seqBusy` sync alone doesn't make two
   writers safe. Confirm the interlock/precondition list with an operator.
5. Model in PyTxT as **gated commands** with PV + REST parity (north-star #1):
   - `CMD:INJECT_ONESHOT` ← params `{bucket, gunBunches, mode, inhibit}` →
     handler runs the seqBusy-sync + `TimInjReq` caput + fine-delay caput →
     a state PV confirms the shot (e.g. echo seq# + timestamp).
   - `CMD:STEP_CM` ← params `{family, field, deltas, deviceList}` → handler does
     read-add-write per channel → state PV confirms applied setpoints.
   - Both behind the `OSPREY:TEST:TXT:*` test-prefix / port isolation gating.

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

## 7. The threading algorithm (analysis half) — traced 2026-06-01

The threading math is **not** in the MML/GitLab tree (`mml-audit` has zero hits for
"threading"). It lives in PyTxT's gitignored `legacy/automated_startup/` as the
`SCexp_ALS_*.m` helpers + `FirstTurnThreading.m` driver (114 lines). Traced in
full:

### The driver (`FirstTurnThreading.m`)
```
RM    = SCgetModelRM(SC, BPMords, CMords, nTurns=1, useIdealRing=1)  % MODELED resp. matrix (pySC + AT)
Mplus = SCgetPinv(RM, alpha=1, N=0, damping=0.5)                     % Tikhonov pinv + gain, ONCE
refData.B = getBPMreading(...)                                       % R0 target orbit, measured or loaded
for i = 1:maxsteps (=6)
    B = getBPMreading
    [dPhiHCM,dPhiVCM] = calcCMstep(B, R0, Mplus, ...)
    setCMs2SetPoints(HCM, dPhiHCM, 'add'); setCMs2SetPoints(VCM, dPhiVCM, 'add')
    pause(1.4)
```
Params: `alpha=1` (Tikhonov regularization), `nSVcut=0` (no singular-value cut),
`damping=0.5` (loop gain), fixed 6 iterations, **no convergence test** (damping
gives stability). `steppv('VCM',5,[5 1])` on line 78 is a deliberate *test* kick,
not production.

### The correction (`SCexp_ALS_calcCMstep.m`) — pure numpy, ~10 lines
```
R  = [B(1,:)'; B(2,:)']     % stack X over Y
dR = R - R0;  dR(isnan)=0   % orbit deviation (== PyTxT Phase-3 diff!)
dphi = Mplus * dR           % the entire correction: one matmul
% then zero every CM downstream of the last BPM that still saw beam:
%   lastBPM = find(~isnan(B(1,:)),1,'last');  zero dphi for CMords > lastBPMord
dPhiHCM = dphi(1:nHCM);  dPhiVCM = dphi(nHCM+1:end)
```
The **downstream-zeroing** is the only first-turn-threading-specific nuance (you
can't steer beam past where it was lost).

### The apply (`SCexp_ALS_setCMs2SetPoints.m`)
`steppv('HCM', -dPhi, CMlist, 'Physics')` — incremental, **physics units (rad)**,
negative sign. The `'Physics'` arg means the AO applies rad→amps
(`Physics2HWParams`) **and** `maxsp` clamping. Only `'add'` mode implemented.

### Corrector envelope (mml-audit + `alsinit.m`, traced 2026-06-01)
HCM = **96 devices**, VCM = **72**. From `alsinit.m`:
- **Conversion** (`alsinit.m:470-471`): `Setpoint.HW2PhysicsFcn = @amp2k`,
  `Physics2HWFcn = @k2amp` — amps↔kick, **energy-dependent** (the conversion
  functions are 450+ lines, per-family, scale with beam energy/BRHO).
- **Limits** (`alsinit.m:5410` `local_maxsp`, hardware amps, by corrector
  position within the sector):
  | Pos in sector | HCM max (A) | VCM max (A) |
  |---|---|---|
  | 1,2,7,8 | 35 | 36 |
  | 3,6 | 17 | — (none) |
  | 4,5 | 17 | 14.5 |
  | 10 | 20 | 19.98 |
  (`local_minsp` assumed symmetric −max, pending confirmation. Record-level
  `DRVH/DRVL` on the setpoint PV is the authoritative runtime backstop anyway.)
- **Channel names** (`alsinit.m:469` → `getname_als('HCM', DeviceList, 1)`): the
  corrector branch of `getname_als.m` (lines ~289-640, Setpoint='AC' type) is now
  **ported to Python** at `tools/gen_corrector_channels.py` (no MATLAB needed). It
  reproduces the exact known device counts — **96 HCM + 72 VCM** — which validates
  the naming formula. Setpoint PV patterns: HCM dev1-8 →
  `SRssC___{HCM1,HCM2,HCSD1,HCSF1,HCSF2,HCSD2,HCM3,HCM4}___AC0x`; VCM dev{1,2,4,5,7,8}
  → `SRssC___{VCM1,VCM2,VCSF1,VCSF2,VCM3,VCM4}___AC0x` (dev 3/6 absent); chicane
  dev10 → `SR(ss+1)U___{H,V}CM2___AC0x`. **One residual to confirm** via read-only
  `family2dev('HCM')`/`('VCM')` dump: `local_maxsp` errors "Sector 1, HCM1 missing"
  yet the count is 96 with dev1-8×12 — verify the SR01 device list.

**Design consequence:** rather than port `amp2k`/`k2amp` to run at PyTxT runtime,
**fold the unit convention into the offline `Mplus` generation** (define the cached
matrix to map BPM-mm → corrector-**amps** directly). Then the runtime CM-apply is:
`caget(setpoint_A) + delta_A → clamp to [−max,+max] → caput`, no energy-dependent
conversion in the hot path. pySC produces the RM; the units choice is made once.

### What this means for PyTxT scope
- **PyTxT already computes `dR`** — Phase-3 reference diff (`B − R0`) *is* the
  `calcCMstep` input. Threading = `Mplus @ dR` + downstream-zeroing on top.
- **The only heavy dependency (pySC + AT) is for `RM`, computed ONCE.** PyTxT can
  generate `Mplus` offline and **ship/cache the matrix** → the *runtime* loop is a
  pure numpy matmul, **no pySC needed at runtime**. pySC is only for
  (re)generating the matrix when the lattice changes. `SCgetPinv` (Tikhonov SVD +
  damping) is ~5 lines of numpy if a pySC binding isn't wired.
- The LOCO lattice model file is in `legacy/automated_startup/lattice/`.

### Verified PyTxT current state (Explore, 2026-06-01)
Phases 1–3 confirmed in source. Read path (`pytxt/ca_client/bpm_reader.py`) is
**passive**: reads `wfr:TBT:{c0,c1,c3,armed}`, nm→mm `/1e6`, injection-turn detect;
captures `armed` but does **not** arm/setup/wait. **No pySC, no SVD, no response
matrix, no HCM/VCM anywhere** — the analysis half is greenfield. CMD pattern
(handler + REST route + CA putter, with REST↔CA parity tests) is clean; new gated
commands plug straight in. Phase-3 diff = element-wise `B − R0` + RMS/max summary.

### Phase-4 build list (every item now concrete)
| # | Item | Where | New? |
|---|---|---|---|
| 1 | Arm + trigger setup (`wfr:TBT:arm`, `triggerMask`, `event48trig`, acq/pretrig) + wait on `armed`→0 | ca_client | new (read path is passive today) |
| 2 | `CMD:INJECT_ONESHOT` (TimInjReq write + seqBusy sync + fine delay + bucket-loading precondition) | handlers/ioc/api | new |
| 3 | Response-matrix gen (pySC + AT lattice) → cache `Mplus` | domain (offline tool) | new, pySC |
| 4 | `SCgetPinv` equivalent (Tikhonov SVD + damping) | domain | new, ~numpy |
| 5 | `calcCMstep` (matmul + downstream-zeroing) | domain | new, trivial |
| 6 | CM apply: physics→HW conversion + Range clamp + incremental caput | domain + ca_client | new |
| 7 | `CMD:STEP_CM` gated command | handlers/ioc/api | new |
| 8 | Loop controller (arm→fire→read→calc→apply ×N, damping, stop) | handlers | new |
| 9 | Frontend threading controls | frontend | new |

---

## Sources

**Live ALS Middle Layer tree** (via the `mml-audit` MCP server — authoritative
for the de-boxed function bodies):

- `machine/ALS/Common/srinjectoneshot.m` — the injection one-shot (§3)
- `mml/steppv.m` — the incremental setpoint wrapper (§4)
- `machine/ALS/Common/synctoevt.m` — event→count-PV table (confirms event 48 =
  `B0215:EVR1:Evt48Cnt-I`, "BR Extraction Kicker")
- `machine/ALS/Common/BPM/bpm_check_tbt.m` — the legacy TBT-check: arm →
  `srinjectoneshot(1,1,40,1)` → poll `wfr:TBT:armed` → `bpm_gettbt` (PyTxT's
  whole Phase-4 loop, with InhibitFlag=1 = no beam dump)
- `machine/ALS/StorageRing/gettune_kicker.m` — same loop for tune measurement
- `machine/ALS/Common/Injection_MRF_Pulsed.m`,
  `machine/ALS/Common/BPM/Working/ReadMe_TimingSystem.m` — `TimInjReq` waveform
  semantics, modes (incl. 42 = "just the SR bumps"), seqBusy notes

**Legacy TxT GUI** (gitignored — local only; the *orchestration* layer):

- `legacy/TxT_GUI/TxT_GUI.mlapp` (unpacked: `run_injection_chain_Pushed`,
  `run_inject_beam`, `runButton_readout_BPMsPushed`, `enable_*` toggles)
- `legacy/TxT_GUI/_unpacked/options_injectBeam.m`
- `legacy/automated_startup/SCexp_ALS_injectBeam.m` (the `srinjectoneshot` call)
- `legacy/automated_startup/SCexp_ALS_{setupBPMs,armBPMs,readoutBPMs,getBPMreading}.m`
- `legacy/automated_startup/FirstTurnThreading.m` (the 114-line driver — §7)
- `legacy/automated_startup/SCexp_ALS_calcCMstep.m` (the correction matmul — §7)
- `legacy/automated_startup/SCexp_ALS_setupCMs.m` / `SCexp_ALS_setCMs2SetPoints.m`
  (CM list build + `steppv` apply in physics units — §7)
- `legacy/automated_startup/lattice/` (the LOCO AT lattice for `SCgetModelRM`)

**mml-audit** (corrector envelope): `get_family HCM` (96 dev) / `VCM` (72 dev) —
`Setpoint.ChannelNames`/`Range`/conversion fields.
