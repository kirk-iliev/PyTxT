# Phase 2 / M1 — Control-Room Validation Handbook

Goal: confirm M1 of Phase 2 works against real `SR01C:BPM1` from a host
on the ALS subnet (e.g. `appsdev2`) **before** starting M2 (scale to all
~120 BPMs). M1's Definition-of-Done is one BPM end-to-end via browser
**and** via CA, with identical effect — this handbook walks through
proving both.

Spec being validated: `docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md`
(milestone **M1**, section 11). DoD ref: section 12 items 1, 3 (limited
to one BPM), and the M1 bullet.

---

## 0. Prerequisites on the control-room host

You should be on `appsdev2` (or another host with ALS CA reachability).
Run these once per machine, not per session.

### 0.1 Python version

The project targets **Python 3.10+** (lowered from 3.11 specifically to
match `appsdev2`'s system Python). Confirm:

```bash
python3 --version            # expect 3.10.x or newer
```

If this box has only 3.9 or older, stop and resolve that first — but
3.10 is the current floor and `appsdev2` already has it.

### 0.2 Confirm CA reachability from this host

Before touching PyTxT, prove the BPM IOC is reachable from this box.
This isolates "is the network/EPICS env right?" from "is PyTxT right?".

```bash
echo $EPICS_CA_ADDR_LIST          # should be non-empty on ALS hosts
echo $EPICS_CA_AUTO_ADDR_LIST     # 'NO' on most ALS hosts

# Direct caget against the real BPM (any one of these is fine):
caget SR01C:BPM1:wfr:TBT:c0       # X waveform, length 100000
caget SR01C:BPM1:wfr:TBT:armed    # ready flag
```

If those return values, network + EPICS env are fine. If they hang or
say "Channel connect timed out," **stop here** and fix CA env before
continuing — PyTxT cannot succeed if `caget` can't.

---

## 1. Get the code on the host

```bash
cd ~/coding              # or wherever you keep checkouts
git clone https://github.com/kirk-iliev/PyTxT.git
# or if it's already cloned:
cd PyTxT && git pull
git log --oneline -3     # confirm 9e00b76 (dep caps) is at the tip
```

---

## 2. Install dependencies

```bash
cd ~/coding/PyTxT

# Reuse the existing .venv if it's already there (it was created with the
# system's 3.10 interpreter — that matches our floor, no rebuild needed):
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip    # in-venv only; does NOT touch system pip
pip install uv               # in-venv only; gives us a sane resolver
uv pip install -e ".[dev]"
```

`uv` is strongly preferred here. Plain `pip install -e ".[dev]"` works
but is prone to multi-minute backtracking on this box — the upper bounds
in `pyproject.toml` help but don't fully fix pip's resolver behavior.

**Everything above stays inside `.venv/`** — no system-wide changes are
made or required. The only reason to `rm -rf .venv` and start over is if
a half-finished install left site-packages in a weird state; otherwise
`uv pip install` reconciles the existing venv to match `pyproject.toml`.

Sanity check:

```bash
python3 -m pytxt --help 2>&1 | head -5   # confirms entry point resolves
pytest --collect-only -q | tail -3       # confirms test suite is discoverable
```

---

## 3. Sanity-check the BPM with the probe script

Before involving the IOC + REST + browser stack, prove caproto from
**this Python interpreter** can read `SR01C:BPM1`:

```bash
python3 scripts/probe_bpm.py SR01C:BPM1
```

Expected: 4 PVs printed (`c0`, `c1`, `c3`, `armed`), each with shape,
dtype, timestamp, severity, basic stats. **If this fails, fix it before
starting the app** — the app uses the same `caproto.asyncio.client`
machinery.

---

## 4. Run the automated test suite on the host

This is the cheapest "did anything regress between my Mac and here"
check. All tests should pass against the fake IOC fixture — they do not
hit the real ring.

```bash
make test-unit
make test-integration
# e2e is optional here; only run if Playwright is set up on this box:
# make test-e2e
```

If unit or integration tests fail on the host but pass on my Mac, that's
a real signal — pause and investigate before continuing.

---

## 5. Start PyTxT against the real ring

The app defaults to the **safe** dev namespace (`OSPREY:TEST:TXT:*`,
ports 59064/59065). For M1 validation that's exactly what we want —
PyTxT publishes its own PVs under `OSPREY:TEST:TXT:*` while *reading*
the real `SR01C:BPM1:wfr:TBT:*` PVs. No production PVs are touched.

```bash
cd ~/coding/PyTxT
source .venv/bin/activate
python3 -m pytxt
```

Leave this running. Watch for the line

```
BpmReader connected to 1 BPMs
```

a second or two after startup — that confirms the in-process CA client
successfully resolved `SR01C:BPM1:wfr:TBT:*` against the ring. Without
this line, ACQUIRE will return `STATUS=FAILED` with all-NaN positions;
debug by checking that this terminal's `EPICS_CA_ADDR_LIST` (etc.) is
the operator default that lets plain `caget SR01C:BPM1:...` work.

In a **second terminal** (any shell — the validation commands in §6 are
plain `caget`/`caput`/`curl`, none of which need the venv). You will
override EPICS env vars in that terminal for the `OSPREY:TEST:TXT:*`
namespace; do not also activate the venv there unless you want to use
`pytest` from it.

---

## 6. Validation matrix — three transports, same effect

M1 DoD is "click ACQUIRE in the browser, see real `SR01C:BPM1`
first-turn position render. Same effect via `caput OSPREY:TEST:TXT:CMD:ACQUIRE 1`."
Validate each transport. All three must show the same data.

### 6.1 Via the browser (the human path)

1. Open `http://<host>:8008/trajectory.html` in a browser.
   (If you're SSH'd into `appsdev2` from your laptop, set up an SSH
   tunnel: `ssh -L 8008:localhost:8008 appsdev2` and open
   `http://localhost:8008/trajectory.html`.)
2. Confirm two stacked canvases (X and Y) are present.
3. Click **ACQUIRE**.
4. Status header should read something like `OK · 1 OK · 0 FAIL`.
5. Each canvas should render a single datapoint (M1 is 1 BPM only).
6. Hover the datapoint — tooltip should show `SR01C:BPM1` and the
   numeric X / Y values.

**Record the displayed X and Y values.** You'll compare them to the CA
and REST paths next.

### 6.2 Via CA (the control-system-citizen path)

PyTxT runs its IOC on **port 59064**, not the standard CA port 5064.
Your operator shell's `EPICS_CA_*` defaults point at the production
ring, so plain `caput`/`caget` against the `OSPREY:TEST:TXT:*` namespace
will time out. Before the commands below, redirect this shell's CA at
PyTxT:

```bash
export EPICS_CA_SERVER_PORT=59064
export EPICS_CA_REPEATER_PORT=59065
export EPICS_CA_ADDR_LIST=127.0.0.1
export EPICS_CA_AUTO_ADDR_LIST=NO
```

While those exports are set, this shell can **only** see PyTxT — direct
reads of ring PVs (e.g. `caget SR01C:BPM1:wfr:TBT:c0`) will fail in
*this* shell. Use a third terminal without these exports if you need to
read ring PVs concurrently.

```bash
# Trigger acquire over CA. Same effect as the button.
caput OSPREY:TEST:TXT:CMD:ACQUIRE 1
# Expected output:
#   Old : OSPREY:TEST:TXT:CMD:ACQUIRE    0
#   New : OSPREY:TEST:TXT:CMD:ACQUIRE    0
# CMD:ACQUIRE is a trigger PV — the *write itself* fires the handler;
# the displayed value being 0/0 is not a bug. (See test_ca_caput_value_is_ignored.)

# State PVs should reflect the acquire:
caget OSPREY:TEST:TXT:STATE:ACQUIRE_IN_FLIGHT       # expect 0 (after acquire returns)
caget OSPREY:TEST:TXT:STATE:LAST_ACQUIRE_OK_COUNT   # expect 1
caget OSPREY:TEST:TXT:STATE:LAST_ACQUIRE_FAIL_COUNT # expect 0
caget OSPREY:TEST:TXT:STATE:LAST_ACQUIRE_STATUS     # expect 2 (= OK; see STATUS_INT_TO_STR)

# Result waveforms — padded to length 128. For M1 (1 BPM) the real
# value sits at element [0]; elements [1..127] are NaN padding.
caget OSPREY:TEST:TXT:RESULT:BPM:X_FIRST_TURN
caget OSPREY:TEST:TXT:RESULT:BPM:Y_FIRST_TURN
```

Confirm element [0] of `X_FIRST_TURN` and `Y_FIRST_TURN` matches what
the browser rendered (within float-print precision). The X/Y values
will be in **mm** (caproto's float PV holds the post-conversion value);
a stored beam typically shows sub-mm offsets at BPM1.

### 6.3 Via REST (the agent-callable path)

REST is HTTP, not CA — no `EPICS_CA_*` env needed. Run these from any
terminal that can reach `localhost:8008` (your SSH-tunnel laptop is
convenient since you already have it open):

```bash
# State endpoint — unified snapshot of every published field:
curl -s http://localhost:8008/api/v1/state | python3 -m json.tool

# Trigger acquire over REST:
curl -s -X POST http://localhost:8008/api/v1/cmd/acquire \
     -H 'Content-Type: application/json' -d '{}' \
   | python3 -m json.tool
# Expect: {"status": "OK", "ok_count": 1, "fail_count": 0, ...}
```

Confirm the `acquire` response status is `OK` and the `last_acquire`
block of `/api/v1/state` shows the same `timestamp` and
`injection_turn_median` as the REST acquire's response — that's the
agentic-parity invariant: CA and REST drive the same handler and surface
the same state.

> **M4 (not M1):** The raw-waveform endpoint
> `GET /api/v1/result/bpm/raw?bpm=<prefix>` is not implemented in M1 —
> `pytxt/api/routes/result.py` is an intentional stub. Any curl against
> it returns 404 until M4 lands. The M1 DoD is met by `acquire` + `state`
> alone.

### 6.4 OpenAPI discoverability check

```bash
curl -s http://localhost:8008/openapi.json | python3 -m json.tool \
  | grep -E '"/api/v1/(cmd/acquire|result/bpm/raw|state)"'
```

For M1 you should see **two** of the three paths listed:

```
"/api/v1/state": {
"/api/v1/cmd/acquire": {
```

`result/bpm/raw` is **not** listed in M1 — the stub doesn't register a
route. It will appear in M4 when the endpoint lands.

---

## 7. Failure-mode spot checks

These are M3-territory features, but the 409 case is easy to verify in
M1 and confirms the concurrency guard works on real hardware:

```bash
# Concurrent acquire — fire two acquires back-to-back. Second should 409:
curl -s -X POST http://localhost:8008/api/v1/cmd/acquire -d '{}' \
     -H 'Content-Type: application/json' &
curl -s -X POST http://localhost:8008/api/v1/cmd/acquire -d '{}' \
     -H 'Content-Type: application/json' -w '\nstatus=%{http_code}\n'
wait
```

Whichever curl finishes second should print `status=409`. If both return
200, the in-flight guard regressed.

> **Skipped in M1:** the "unknown BPM on raw endpoint → 404" check from
> earlier drafts of this doc is meaningless in M1 because the whole
> `result/bpm/raw` route 404s (M4 territory). It's tracked as part of
> M4-T1 in the phase-2 plan.

If the 409 spot check misbehaves, log it in
`docs/superpowers/specs/2026-05-18-phase-2-decisions.md` — but it does
not block M2 since the formal scope is M3.

---

## 8. Sign-off checklist before starting M2

Copy this into a scratchpad or the decisions log and tick each. Items
marked **(M4)** are noted here for context but are not M1 deliverables —
do not block M2 on them.

- [ ] `caget SR01C:BPM1:wfr:TBT:c0` returns a waveform from this host (§3)
- [ ] `scripts/probe_bpm.py SR01C:BPM1` prints all four PVs cleanly (§3)
- [ ] `make test-unit` passes on the host (§4)
- [ ] `make test-integration` passes on the host (§4)
- [ ] `python3 -m pytxt` starts and serves `/trajectory.html` (§5)
- [ ] PyTxT log shows `BpmReader connected to 1 BPMs` (§5)
- [ ] Browser ACQUIRE renders a real `SR01C:BPM1` datapoint on both canvases (§6.1)
- [ ] `caput OSPREY:TEST:TXT:CMD:ACQUIRE 1` triggers the same render (§6.2)
- [ ] `RESULT:BPM:X_FIRST_TURN[0]` and `Y_FIRST_TURN[0]` are real numbers (sub-mm); elements [1..127] are NaN padding (§6.2)
- [ ] `POST /api/v1/cmd/acquire` returns `{"status": "OK", "ok_count": 1, "fail_count": 0, ...}` (§6.3)
- [ ] `/api/v1/state` shows `last_acquire` matching the REST response's timestamp and injection_turn_median (§6.3)
- [ ] `openapi.json` lists `acquire` and `state` (§6.4); `result/bpm/raw` is **expected to be absent** (M4)
- [ ] Concurrent acquire → second returns 409 (§7)
- [ ] **(M4)** `GET /api/v1/result/bpm/raw?bpm=SR01C:BPM1` returns matching values
- [ ] **(M4)** Unknown BPM raw → 404

All non-M4 boxes ticked ⇒ M1 is validated against the real ring.
Proceed to M2 (scale to ~120 BPMs from `pytxt/config/bpm_prefixes.txt`).

---

## 9. Shutdown / cleanup

```bash
# In the PyTxT terminal:
Ctrl-C

# Or from anywhere:
pkill -f "python.* -m pytxt" || true
```

No persistent state to clean up — PyTxT holds no on-disk data in
phase 2.
