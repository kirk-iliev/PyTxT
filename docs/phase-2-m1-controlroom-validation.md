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
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip    # in-venv only; does NOT touch system pip
pip install uv               # in-venv only; gives us a sane resolver
uv pip install -e ".[dev]"
```

`uv` is strongly preferred here. Plain `pip install -e ".[dev]"` works
but is prone to multi-minute backtracking on this box — the upper bounds
in `pyproject.toml` help but don't fully fix pip's resolver behavior.

**Everything above stays inside `.venv/`** — no system-wide changes are
made or required. If you need to scrap and retry, `rm -rf .venv` is the
complete undo.

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

Leave this running. In a second terminal, also `source .venv/bin/activate`
for the `pytxt`-installed binaries.

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

```bash
# Trigger acquire over CA. Same effect as the button.
caput OSPREY:TEST:TXT:CMD:ACQUIRE 1

# State PVs should reflect the acquire:
caget OSPREY:TEST:TXT:STATE:ACQUIRE_IN_FLIGHT
caget OSPREY:TEST:TXT:STATE:LAST_ACQUIRE_OK_COUNT     # expect 1
caget OSPREY:TEST:TXT:STATE:LAST_ACQUIRE_FAIL_COUNT   # expect 0

# Result waveforms (length-1 in M1):
caget OSPREY:TEST:TXT:RESULT:BPM:X_FIRST_TURN
caget OSPREY:TEST:TXT:RESULT:BPM:Y_FIRST_TURN
```

Confirm `X_FIRST_TURN` and `Y_FIRST_TURN` match what the browser
rendered (within float-print precision).

### 6.3 Via REST (the agent-callable path)

```bash
# State endpoint should expose acquire bookkeeping:
curl -s http://localhost:8008/api/v1/state | python3 -m json.tool

# Trigger acquire over REST:
curl -s -X POST http://localhost:8008/api/v1/cmd/acquire \
     -H 'Content-Type: application/json' -d '{}' \
   | python3 -m json.tool

# Raw waveforms for one BPM:
curl -s 'http://localhost:8008/api/v1/result/bpm/raw?bpm=SR01C:BPM1' \
   | python3 -m json.tool | head -40
```

Confirm the `acquire` response and the `raw` endpoint return the same
X / Y values seen in the browser and via `caget`.

### 6.4 OpenAPI discoverability check

```bash
curl -s http://localhost:8008/openapi.json | python3 -m json.tool \
  | grep -E '"/api/v1/(cmd/acquire|result/bpm/raw|state)"'
```

All three endpoints should be listed. (This is DoD item 12.)

---

## 7. Failure-mode spot checks

These are M3-territory features, but a couple are easy to verify in M1
and confirm the foundation is solid:

```bash
# Concurrent acquire — fire two acquires back-to-back. Second should 409:
curl -s -X POST http://localhost:8008/api/v1/cmd/acquire -d '{}' \
     -H 'Content-Type: application/json' &
curl -s -X POST http://localhost:8008/api/v1/cmd/acquire -d '{}' \
     -H 'Content-Type: application/json' -w '\nstatus=%{http_code}\n'
wait

# Unknown BPM on the raw endpoint — should 404:
curl -s -o /dev/null -w '%{http_code}\n' \
     'http://localhost:8008/api/v1/result/bpm/raw?bpm=NOT:A:BPM'
```

If either of these doesn't behave, log it in
`docs/superpowers/specs/2026-05-18-phase-2-decisions.md` — but it does
not block M2 since the formal scope is M3.

---

## 8. Sign-off checklist before starting M2

Copy this into a scratchpad or the decisions log and tick each:

- [ ] `caget SR01C:BPM1:wfr:TBT:c0` returns a waveform from this host
- [ ] `scripts/probe_bpm.py SR01C:BPM1` prints all four PVs cleanly
- [ ] `make test-unit` passes on the host
- [ ] `make test-integration` passes on the host
- [ ] `python3 -m pytxt` starts and serves `/trajectory.html`
- [ ] Browser ACQUIRE renders a real `SR01C:BPM1` datapoint on both canvases
- [ ] `caput OSPREY:TEST:TXT:CMD:ACQUIRE 1` triggers the same render
- [ ] `RESULT:BPM:X_FIRST_TURN` and `Y_FIRST_TURN` match the browser values
- [ ] `POST /api/v1/cmd/acquire` returns matching values
- [ ] `GET /api/v1/result/bpm/raw?bpm=SR01C:BPM1` returns matching values
- [ ] `openapi.json` lists `acquire`, `result/bpm/raw`, `state`
- [ ] Concurrent acquire → second returns 409
- [ ] Unknown BPM raw → 404

All ticked ⇒ M1 is validated against the real ring. Proceed to M2
(scale to ~120 BPMs from `pytxt/config/bpm_prefixes.txt`).

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
