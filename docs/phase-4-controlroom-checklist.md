# Phase 4 — Control-room checklist

The Phase-4 threading work is built and unit/integration-tested **locally against
the fake IOC** (`tests/fixtures/fake_bpm_ioc.py`). This file lists the things that
**cannot** be settled at a desk — they need a real control-room host, live PVs, or
beam — in the order you'd want to do them. Each item says whether it's **read-only**
(safe anytime, no shift) or **active** (commands the machine → needs a physics shift
+ operator sign-off).

Cross-references: `docs/phase-4-injection-notes.md` §3/§4/§9 (de-boxed PV detail),
spec `docs/superpowers/specs/2026-06-01-phase-4-threading-design.md` §9, decisions
log D1–D6 (resolved 2026-06-04).

Legend: 🟢 read-only (do anytime) · 🔴 active (shift + sign-off) · ⏳ blocks a milestone's *finalization* (code is already built/tested locally).

---

## A. Read-only — do these on the next ordinary control-room visit (no shift)

### A1. 🟢⏳ Passive `camonitor` capture during top-off — confirm the injection confirm-signal
**Blocks:** finalizing M3 (`CMD:INJECT_ONESHOT`) — specifically *which counter is the
per-shot confirm signal* and *that `seqBusy` actually toggles 1→0*.
**Why it can be passive:** top-off fires real injection shots continuously, so you
observe the natural cycles — no need to fire your own. `camonitor` is a read-only
subscription; the timing-window constraint only applies to *writing* `TimInjReq`.

Steps (on a control-room host with EPICS env pointed at the live machine):
1. Confirm the ring is in normal user operations / topping off (so shots are flowing).
2. Run, capturing to a timestamped log:
   ```
   camonitor -tc \
     TimInjReq \
     EVG:E1:seqBusy \
     B0215:EVR1-Out:UDC0:Delay-SP \
     B0215:EVR1:Evt48Cnt-I \
     LI11:EVR1:Evt10Cnt-I \
     | tee phase4-camonitor-$(date +%Y%m%d-%H%M).log
   ```
3. Let it run through **≥ 20 top-off injection cycles** (a few minutes).
4. From the log, confirm:
   - `EVG:E1:seqBusy` shows clean `1`→`0` transitions per shot.
   - Each `TimInjReq` write (seqNum element increments) is followed by exactly **one**
     increment of `B0215:EVR1:Evt48Cnt-I` (the hypothesised confirm signal). Verify the
     1:1 ratio holds over all cycles. If `Evt48Cnt` is noisy, check `Evt10Cnt-I`
     (start-of-sequence) as the alternate.
   - Note the typical `TimInjReq`→`seqBusy`→counter ordering and lag.
5. Record the chosen confirm-signal PV back into spec §5.5 / injection-notes §3.

**Output:** the confirm-signal PV name (settles a `# TODO(confirm)` in the
`CMD:INJECT_ONESHOT` handler). No beam manipulation.

### A2. 🟢⏳ `family2dev` device-list dump — finalize the corrector channel catalog
**Blocks:** committing `pytxt/config/hcm_channels.txt` / `vcm_channels.txt` as final
(they're generated locally now but carry one unverified assumption: the SR01-HCM1
device list, where `local_maxsp` errors "Sector 1, HCM1 missing" yet the count is 96).

Steps (MATLAB + MML on a control-room host):
1. ```matlab
   hcm = family2dev('HCM');   % [sector device] pairs, 96 rows expected
   vcm = family2dev('VCM');   % 72 rows expected
   ```
2. Dump both to text (e.g. `dlmwrite` or just paste) and bring them back.
3. Diff against the generated catalogs (`tools/gen_corrector_channels.py` output).
   Confirm counts (96 / 72) and that the SR01 device list matches the formula.
4. If they match → mark the catalog final. If not → patch the generator's SR01 case.

**Output:** corrector catalog confirmed; no machine writes.

### A3. 🟢 (optional) Re-confirm live record metadata
Mostly done 2026-06-01, but if convenient re-verify with `cainfo`/`caget`:
`TimInjReq` (DBF_LONG×7), `EVG:E1:seqBusy` (DBF_DOUBLE 0/1),
`B0215:EVR1-Out:UDC0:Delay-SP` (DBF_LONG, clamps 0–1023). Read-only.

---

## B. Active — require a physics shift + operator sign-off

Do these **only** with beam time allocated, on the `OSPREY:TEST:TXT:*` test prefix
first, and with an operator. Listed in ascending risk.

### B0. 🔴 Pre-reqs to gather before the shift (read-only, but feed the active steps)
- **Interlock / precondition list for firing** (spec §9 #3): gun permit, shutters,
  injection mode gates — everything beyond `bucket:control:cmd` that must be checked
  before `CMD:INJECT_ONESHOT` writes. Get this from the injection/operations group.
- **Corrector limit authority sign-off** (spec §9 #4): confirm the `local_maxsp`
  per-position amp limits PyTxT will clamp to, and the `inhibit=1` default.

### B1. 🔴⏳ One-shot fire validation — `CMD:INJECT_ONESHOT`, `inhibit=1`
**Validates:** M3 end-to-end against the real timing system *without injecting charge*.
1. With PyTxT running on the test prefix, fire one shot with **`inhibit=1`** (bumps
   only, gun blocked — no new charge), `bucket=308`, low `gun_bunches`.
2. Confirm: `TimInjReq` write lands; the `seqBusy` 1→0 sync behaves; the fine-delay
   PV is written; the confirm-signal PV (from A1) ticks; the state PV echoes the shot.
3. **Test the precondition refusal:** attempt a fire while top-off/bucket-loading is
   active → PyTxT must refuse loudly (not race the top-off writer).

### B2. 🔴⏳ Real-magnet step validation — `CMD:STEP_CM`
**Validates:** M2 corrector apply + the D5 compare-and-set guard on real hardware.
1. Pick one HCM (or VCM), read its current setpoint.
2. Issue `CMD:STEP_CM` with a **small** known delta and the correct `expected_prior_A`.
   Confirm the readback moves by the delta and `STATE:CM_LAST_APPLIED` echoes it.
3. **Test the CAS guard:** issue a step with a deliberately wrong `expected_prior_A`
   → must refuse. Issue with a delta that would exceed `local_maxsp` → must clamp.
4. Restore the corrector to its original setpoint.

### B3. 🔴⏳ Active acquisition validation — arm/trigger/wait on real BPMs
**Validates:** M1 active-acquisition path (the arm/setup/wait code, today only tested
against the fake IOC). Confirm `wfr:TBT:arm` + trigger mask + `event48trig` actually
arm the real TBT BPMs and `wfr:TBT:armed` clears after a shot. Can piggyback on B1.

### B4. 🔴⏳ Closed-loop threading commissioning — `CMD:THREAD_START`
**Validates:** M4 — the full loop on beam. Do it in stages:
1. **Commission in `inhibit=1` first** (stored-beam bump response, no charge): run
   `CMD:THREAD_START` with `fire_each_step` using `inhibit=1`, low `max_steps`, small
   `gain`. Watch the divergence guard and per-iteration RMS. Confirm correctors move
   sanely and the loop stops on its own.
2. **Only after that passes, and with explicit operator sign-off + prefix promotion
   to production**, run real first-turn threading with **`inhibit=0`** (gun fires →
   actual first turn to steer). This is the real deliverable; it is gated, not default.

---

## Quick status map (what each milestone still needs from the control room)

| Milestone | Built & tested locally | Control-room item to finalize |
|---|---|---|
| M1 acquisition | ✅ (vs fake IOC) | B3 (arm on real BPMs) |
| M1 domain / matrix runtime | ✅ (numpy, synthetic matrix) | none (real matrix = deferred lattice modeling, not a CR task) |
| M2 corrector catalog | ✅ (provisional) | A2 (family2dev dump) |
| M2 `CMD:STEP_CM` | ✅ (vs fake IOC) | B2 (real-magnet step) |
| M3 `CMD:INJECT_ONESHOT` | ✅ (vs fake IOC) | A1 (confirm-signal) + B0/B1 (interlocks + fire) |
| M4 loop + frontend | ✅ (vs fake IOC, dry-run) | B4 (closed-loop commissioning) |

**Pull-forward:** A1 and A2 are read-only and need no shift — doing them on your next
ordinary control-room visit de-risks M3 and finalizes M2 ahead of the physics shift,
so the shift is spent only on the active B-items.
