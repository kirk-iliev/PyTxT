# PyTxT — Overview

**Last refreshed:** 2026-05-29 · **Phase:** 2 (read path) **complete**; Phase 3 (reference trajectory) next · **Live status:** [`PyTxT-roadmap.html`](../PyTxT-roadmap.html)

This is the canonical "what is this thing?" document for PyTxT. Read it
top-to-bottom and you should be able to answer: what PyTxT does, where
it came from, where it sits in the ALS machine, how it's built, what
surfaces it exposes, what's done today, and what's planned. Pointers at
the end of each section take you to the authoritative artifact for that
topic when you need more depth.

---

## 1. What PyTxT is

PyTxT is a **turn-by-turn (TBT) beam-analysis service** for the
Advanced Light Source (ALS) injection chain. It is a port of the MATLAB
GUI `TxT_GUI.mlapp` (see [`TxT_GUI_manual.pdf`](../TxT_GUI_manual.pdf))
that operators use during storage-ring injection startup. The MATLAB
original arms the BPM electronics, fires injection, reads the turn-by-turn
waveforms back out of every BPM around the ring, and lets the operator
visualize the first-turn trajectory, compare it to a reference, and run
trajectory correction via response-matrix inversion.

PyTxT delivers the same workflow as:

- a **Python backend** (FastAPI + caproto, single asyncio process)
- a **soft EPICS IOC** that publishes the app's operational state as PVs
- a **vanilla-JS + Canvas browser frontend**
- packaged into a Docker container, deployed to `appsdev2:8008`

It is **agent-callable first, human-callable second**: every meaningful
capability is reachable both by writing a PV (CA) and by hitting a REST
endpoint, with identical effect. The browser is one consumer of the same
surface that an Osprey agent or a Phoebus screen would use.

---

## 2. Where it came from

### The MATLAB original

The reference implementation lives on `appsdev2`:

```
/home/als/physbase/users/thellert/automated_startup/GUI/TxT_GUI.mlapp
/home/als/physbase/users/thellert/automated_startup/SCexp_ALS_*.m
```

A read-only copy is also mirrored locally under `legacy/` (gitignored,
scp'd from appsdev2; refresh by re-scp'ing if upstream changes).

The MATLAB GUI is wired into MATLAB Middle Layer (MML) and the SC toolkit:

- **MML wrappers** mediate hardware: `srinjectoneshot` triggers injection,
  `steppv` issues corrector-magnet steps. These are operational black
  boxes whose underlying PVs are not yet enumerated. Their port is
  deferred to phase 4.
- **SC toolkit** (Simulated Commissioning) provides the lattice model,
  response matrices, and SVD inversion. Its Python equivalent is
  [pySC](https://pypi.org/project/accelerator-toolbox/) — the
  `pysc-toolkit` Claude skill is the canonical reference for the port.
- **`SCexp_ALS_readoutBPMs.m`** is the read-side hardware adapter. Phase
  2 of PyTxT is essentially a Python port of this single MATLAB file.

### Why we're porting

The original GUI is locked to MATLAB licenses and a desktop session, and
its state is held in MATLAB workspace variables that nothing else can
see. The driver behind PyTxT is **AI-native ALS operations** — the
ALS runs *Osprey*, a harnessed-Claude framework for agentic accelerator
operation. For an agent to use TxT, it must be able to:

1. invoke commands without screen-scraping a GUI,
2. observe results in the same way it observes any other PV on the
   control system,
3. operate from the same transport surface (CA, REST, eventually MCP)
   regardless of which subsystem it's talking to.

PyTxT is the first ALS analysis app designed against those requirements
from day one.

### Why it's not a PyBeamViewer clone

PyBeamViewer is the architectural prior art at ALS — a single-process
asyncio FastAPI app for camera-frame viewing. PyTxT borrows its
**patterns** (vanilla JS + Canvas, Pydantic schemas, Playwright e2e,
Docker layout) but **diverges deliberately** on one axis: PyBeamViewer
holds state in process memory behind a REST API, whereas PyTxT publishes
its state as **EPICS PVs via a soft IOC**. The justification is principle
#2 below — application state is itself control-system data and belongs
in the same namespace as a magnet IOC.

---

## 3. Where PyTxT sits in the machine

The ALS injection chain feeds the storage ring (SR) from a booster. At
injection time:

1. A pulse from the booster is deflected into the SR via injection
   septum + bumper magnets.
2. ~120 **Beam Position Monitors** (BPMs, Libera electronics) around the
   ring sample the beam position at every turn — typically 100 000
   samples per BPM per acquisition. This is "turn-by-turn" data.
3. The operator inspects the **first-turn trajectory** (one X/Y reading
   per BPM at the injection turn) to verify the beam is threading the
   lattice correctly.
4. If the trajectory deviates from a known-good reference, the operator
   adjusts corrector magnets (CMs) to bring it back.

PyTxT is the analysis surface for steps 3 and 4. It sits between the
existing control-system infrastructure and the operator (or agent):

```
                ┌──────────────────────────────────────────┐
                │   ALS control system (existing)          │
                │                                          │
                │   ~120 BPM IOCs        Corrector IOCs    │
                │   {prefix}:wfr:TBT:…   …:CM:…            │
                │   Phoebus, archiver, alarms              │
                └────────────┬─────────────────┬───────────┘
                             │ CA reads        │ CA writes (phase 4)
                             │                 │
                             ▼                 ▼
                ┌──────────────────────────────────────────┐
                │              PyTxT process               │
                │                                          │
                │   CA client  →  AppState  →  Soft IOC    │
                │                    ▲           │         │
                │             REST/WS API ←──────┘         │
                │                    │                     │
                │                    ▼                     │
                │              Browser frontend            │
                └────────────────────┬─────────────────────┘
                                     │ same PVs
                                     ▼
                ┌──────────────────────────────────────────┐
                │  Other CA clients: Phoebus, archiver,    │
                │  Osprey agents, logbook                  │
                └──────────────────────────────────────────┘
```

PyTxT is **both a CA client** (reading upstream BPMs/correctors) **and a
CA server** (publishing analysis results). The same PV namespace it
publishes is visible to every other control-system consumer with no
adapter.

**Deployment target:** `appsdev2`, port 8008 (HTTP) + EPICS ports
59064/59065 (IOC + repeater) for dev. The dev IOC uses the
`OSPREY:TEST:TXT:*` PV prefix per als-profiles test-IOC safety rules;
production will use `TxT:*`.

---

## 4. Design principles

These are summarized from [`CLAUDE.md`](../CLAUDE.md), which remains the
canonical source. They are listed here so this overview is
self-contained for a first-time reader.

1. **Agent-callable first, human-callable second.** Every command has
   both a PV and a REST endpoint with identical effect. Pydantic schemas
   are first-class; OpenAPI is auto-generated; every PV carries a `.DESC`
   string. The browser is one consumer, not the privileged one.
2. **PVs are the primary state interface.** Fit results, reference
   trajectory, "tracking on/off", liveness — all published as PVs by
   the embedded soft IOC. State is *observable* outside the process.
3. **REST/WS handles only what PVs can't.** Bulk transfers (raw
   waveforms, reference-file I/O), file uploads, static assets, and the
   WS↔CA bridge that lets the browser subscribe to PVs.
4. **Forward-looking package layout.** Each subsystem (CA client, IOC,
   domain, API, frontend) lives in its own clearly bounded package.
   Don't replicate PyBeamViewer's single-subsystem flat layout.
5. **Domain logic is I/O-free.** Pure analysis lives in `pytxt/domain/`
   with no caproto, FastAPI, or asyncio dependencies — testable in
   milliseconds with numpy alone. I/O adapters above the domain layer
   translate to and from this pure core.

---

## 5. Architecture

### 5.1 One process, four cooperating subsystems

PyTxT runs as a **single Python asyncio process**. Inside it, four
subsystems share an event loop and a single `AppState` instance:

| Subsystem | Package | Role |
|---|---|---|
| CA client | `pytxt/ca_client/` | Reads upstream BPM TBT waveforms via caproto |
| Soft IOC | `pytxt/ioc/` | Publishes app state + commands as PVs via caproto |
| FastAPI app | `pytxt/api/` | REST mirrors of every CMD; WS↔CA bridge for browser |
| Domain | `pytxt/domain/` | I/O-free analysis (injection-turn detection, first-turn extraction, future: response-matrix math) |

The composition root is [`pytxt/composition.py`](../pytxt/composition.py).
It wires the IOC, the FastAPI app, the BPM reader, and a 1 Hz heartbeat
loop together and `asyncio.gather`s them. There is no separate IOC
process, no separate web process.

### 5.2 Single source of truth: `AppState`

`pytxt/state/app_state.py` defines a dataclass that holds everything the
app considers operationally meaningful: heartbeat, last ping timestamp,
acquisition-in-flight flag, last-acquire result, in-memory raw
waveforms from the most recent acquisition, and the configured BPM
prefix list.

`AppState.update(**changes)` is the canonical mutation point. It is:

- **atomic across fields** (validate+apply all changes, *then* fire
  listeners — listeners always see post-update state),
- **listener-driven** (the IOC publisher subscribes per-field; when a
  field changes, its PV updates immediately),
- **typo-rejecting** (mutating an unknown field raises
  `AttributeError`).

The IOC is the primary `AppState` listener — it converts state changes
into PV updates, which CA clients (including the browser via the WS
bridge) then see.

### 5.3 End-to-end data flow on `ACQUIRE`

The keystone interaction. Triggered by either a CA write to
`{prefix}CMD:ACQUIRE` or a `POST /api/v1/cmd/acquire`:

```
 1. Operator click   →  WS sends CMD:ACQUIRE write  (or HTTP POST)
 2. IOC putter / REST route  →  handle_acquire()   (one canonical handler)
 3. handle_acquire sets acquire_in_flight=True via AppState.update
       → IOC listener publishes STATE:ACQUIRE_IN_FLIGHT=1
       → browser sees the busy state via its CA subscription
 4. BpmReader.read_all() — parallel asyncio.gather of ~120 BPM reads,
       each fetching {prefix}:wfr:TBT:{c0,c1,c3,armed}
 5. extract_first_turn() — pure-numpy domain function detects the
       injection turn from the sum waveform and pulls X/Y at that index
 6. AppState.update(last_acquire=..., last_acquire_raws=...)
       → IOC publishes RESULT:BPM:X_FIRST_TURN, Y_FIRST_TURN,
         SUM_FIRST_TURN, INJECTION_TURN, plus STATE:LAST_ACQUIRE_*
       → browser canvas re-renders the ring trajectory
 7. handle_acquire returns AcquireResponse (REST caller) or completes
       the CA putter; finally clause clears acquire_in_flight.
```

The shared handler (`pytxt/handlers/acquire.py`) is what enforces
**agentic parity by construction**: there is no way for a REST-initiated
acquire and a PV-initiated acquire to diverge, because they invoke
literally the same function.

Step 6 also stashes the per-BPM full waveforms (None entries stripped)
into `AppState.last_acquire_raws`. That in-memory cache is what backs the
raw-waveform drill-down endpoint (§7.2) — the one payload too large for
PV semantics. Because `AppState.update` is atomic, a reader hitting
`/result/bpm/raw` mid-acquire never sees half-written data, so the raw
endpoint has no 409 path.

### 5.3a The synthetic reader (e2e / demo)

`pytxt/ca_client/synthetic_reader.py` provides `SyntheticBpmReader`, a
drop-in for `BpmReader` selected at composition time via
`PYTXT_USE_SYNTHETIC_READER=1`. It returns deterministic per-BPM
waveforms — a flat sum signal with a rising edge at sample 1370 so the
domain's injection-turn detection finds a real turn, and per-BPM-varying
X/Y so the rendered polyline isn't flat. It performs no CA I/O, so the
full click-ACQUIRE-render-hover cycle (and the Playwright e2e suite) runs
with no live ring. It is never wired in production.

### 5.4 The WebSocket↔CA bridge

`pytxt/api/ws_bridge.py` exposes one WebSocket endpoint,
`/api/v1/pvs`. A browser connects, sends a JSON `{action: "subscribe",
pvs: [...]}` message, and the server opens an in-process caproto async
client subscription per PV. PV updates are forwarded as JSON
`{pv, value, ts}` messages.

This is deliberate: the browser is **just another CA client** that
happens to render images. It sees the same type coercions, the same
update semantics, the same delivery guarantees as Phoebus or any
external CA tool. There is no UI-private state path.

---

## 6. Package layout

```
pytxt/
├── __main__.py            # python -m pytxt → composition.main()
├── composition.py         # composition root: wires IOC + API + reader
├── config/
│   ├── settings.py        # pydantic-settings (env-var driven, PYTXT_*)
│   ├── bpm_prefixes.py    # loader for the committed BPM prefix list
│   └── bpm_prefixes.txt   # 107 ALS SR BPM PV prefixes (colon form)
├── state/
│   └── app_state.py       # single source of truth + listener bus
├── handlers/              # canonical handlers, called by BOTH IOC + REST
│   ├── ping.py
│   └── acquire.py
├── ioc/
│   ├── server.py          # caproto IOC lifecycle
│   └── pvs.py             # PVGroup: every PV with .DESC string
├── ca_client/
│   └── bpm_reader.py      # persistent caproto client; reads ~120 BPMs in parallel
├── domain/                # I/O-free analysis (pure numpy)
│   ├── types.py           # RawBPM, FirstTurnResult dataclasses
│   ├── injection_turn.py  # detects injection turn from sum waveform
│   └── first_turn_extract.py
├── api/
│   ├── server.py          # FastAPI app factory
│   ├── ws_bridge.py       # WebSocket↔CA bridge
│   ├── routes/            # /api/v1/{health,state,cmd,result}
│   └── schemas/           # Pydantic models (cmd, state, result, ws)
└── frontend/              # vanilla JS + Canvas (static assets)
```

**Status flags** for each package as of 2026-05-29 (Phase 2 complete):

| Package | Status | Notes |
|---|---|---|
| `config/` | implemented | Settings + BPM prefix loader live; 107-entry catalog committed |
| `state/` | implemented | AppState fields for phase 1 + 2 published, incl. `last_acquire_raws` cache |
| `handlers/` | implemented | `ping` + `acquire` |
| `ioc/` | implemented | Phase-1 + phase-2 PV namespaces populated |
| `ca_client/` | implemented | `BpmReader` validated against 107 BPMs ≤3 s; `SyntheticBpmReader` for e2e/demo |
| `domain/` | implemented (phase 2 scope) | First-turn extract done; response-matrix work lands in phase 4 |
| `api/routes/` | implemented (phase 2 scope) | `cmd`/`state`/`config`/`health` + `result/bpm/raw` all live |
| `api/ws_bridge` | implemented | Browser subscribes per-PV; coerces caproto values to JSON |
| `frontend/` | implemented (phase 2 scope) | Ring-trajectory X/Y plot, per-BPM hover tooltip, status header w/ timestamp |

---

## 7. The machine interface (what's reachable today)

### 7.1 PV namespace

Prefix is configurable via `PYTXT_PV_PREFIX`. Dev default:
`OSPREY:TEST:TXT:`. Production: `TxT:`. PV names below are shown without
the prefix.

| PV | Type | RW | Purpose |
|---|---|---|---|
| `HEALTH:HEARTBEAT` | int | R | Liveness counter; +1 every 1 s |
| `HEALTH:UPTIME_S` | float | R | Seconds since process start |
| `STATE:VERSION` | string | R | Running PyTxT semver |
| `STATE:LAST_PING_AT` | string | R | ISO-8601 UTC of most recent ping |
| `STATE:PING_COUNT` | int | R | Total pings since startup |
| `STATE:ACQUIRE_IN_FLIGHT` | int | R | 1 while an acquisition is running |
| `STATE:LAST_ACQUIRE_STATUS` | int | R | 0=NEVER, 1=ACQUIRING, 2=OK, 3=PARTIAL, 4=FAILED |
| `STATE:LAST_ACQUIRE_OK_COUNT` | int | R | BPMs that returned valid data |
| `STATE:LAST_ACQUIRE_FAIL_COUNT` | int | R | BPMs that timed out / returned bad data |
| `STATE:LAST_ACQUIRE_TIMESTAMP` | string | R | ISO-8601 UTC of most recent ACQUIRE |
| `STATE:LAST_ACQUIRE_FAIL_REASON` | string | R | Error message when LAST_ACQUIRE_STATUS=FAILED |
| `STATE:LAST_ACQUIRE_FAILED_BPM_NAMES` | string[128] | R | Names of failed BPMs from last ACQUIRE |
| `RESULT:BPM:X_FIRST_TURN` | float[128] | R | Per-BPM X position (mm) at injection turn; NaN for failed BPMs |
| `RESULT:BPM:Y_FIRST_TURN` | float[128] | R | Per-BPM Y position (mm) at injection turn; NaN for failed BPMs |
| `RESULT:BPM:SUM_FIRST_TURN` | float[128] | R | Per-BPM sum signal (AU) at injection turn |
| `RESULT:BPM:INJECTION_TURN` | int[128] | R | Per-BPM detected injection-turn sample index; −1 for failed |
| `RESULT:BPM:NAMES` | string[128] | R | Static-after-startup: BPM prefix for each array index |
| `CMD:PING` | int | W | Write any value → issue a ping (smoke test) |
| `CMD:ACQUIRE` | int | W | Write any value → trigger BPM acquisition |

The waveform arrays use a static `max_length=128` (defined in
`pytxt/ioc/pvs.py` as `_BPM_MAX`) to accommodate up to ~128 BPMs with
headroom; only the first `N` entries (where N = number of configured
BPMs, currently 107) are meaningful.

The canonical definitions — including the `.DESC` strings agents will
see — are in [`pytxt/ioc/pvs.py`](../pytxt/ioc/pvs.py).

### 7.2 REST endpoints

Base URL `http://appsdev2:8008` in dev. Full schemas via the
auto-generated OpenAPI at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Transport-level liveness probe; always HTTP 200 |
| `GET` | `/api/v1/state` | Full `AppState` snapshot (one-shot read of everything the IOC publishes) |
| `GET` | `/api/v1/config` | Frontend bootstrap: returns the deployed `pv_prefix` |
| `POST` | `/api/v1/cmd/ping` | REST mirror of `CMD:PING`; same handler |
| `POST` | `/api/v1/cmd/acquire` | REST mirror of `CMD:ACQUIRE`; 409 if already in-flight |
| `GET` | `/api/v1/result/bpm/raw?bpm=<prefix>` | Full raw TBT waveforms for one BPM (see below) |
| `WS` | `/api/v1/pvs` | Subscribe to PVs over WebSocket; messages `{action, pvs[]}` in, `{pv, value, ts}` out |
| `GET` | `/` | Static frontend |

`GET /api/v1/result/bpm/raw?bpm=<prefix>` (live since M4) is the
drill-down for one BPM's full turn-by-turn waveforms — the one endpoint
that exists *because* PVs can't carry 107 × 100 000 int32 samples
(~144 MB) cleanly. It reads the in-memory `last_acquire_raws` cache
populated by the most recent acquire and returns a `BpmRawWaveforms`:

```json
{
  "bpm_prefix": "SR01C:BPM1",
  "x_nm":   [ ...100000 raw int nm... ],
  "y_nm":   [ ...100000 raw int nm... ],
  "sum_au": [ ...100000 raw int AU... ],
  "armed": 0,
  "read_timestamp": "2026-05-29T…Z"
}
```

Note the values are **raw nm / AU** — the `/1e6` nm→mm conversion is
applied only to the first-turn scalars published as PVs, not to this
bulk download. Error paths: **400** for missing/empty `bpm`, **404** for
an unknown prefix *or* a BPM with no stored data yet (acquire never ran,
or that BPM was in the last failed-set). No **409** — the cache is
swapped atomically, so concurrent acquires never expose partial data.

### 7.3 Equivalence

| Action | CA path | REST path |
|---|---|---|
| Ping | write `CMD:PING` | `POST /api/v1/cmd/ping` |
| Acquire | write `CMD:ACQUIRE` | `POST /api/v1/cmd/acquire` |
| Observe last acquire | subscribe `STATE:LAST_ACQUIRE_*` | `GET /api/v1/state` (one-shot) |
| Observe results | subscribe `RESULT:BPM:*` | `GET /api/v1/state` (one-shot) |
| Stream results | subscribe via CA | subscribe via `WS /api/v1/pvs` |

Both transports route through the same handler functions. There is no
"REST-only" or "PV-only" behaviour.

---

## 8. The operator workflow (from the MATLAB manual)

The 18-step workflow defined in [`TxT_GUI_manual.pdf`](../TxT_GUI_manual.pdf)
is the feature-parity target. Mapped to PyTxT phases:

| Step | Workflow action | Delivered by |
|---|---|---|
| 1–4 | Launch GUI, select reference, choose BPMs | Phase 3 (reference loader) |
| 5–7 | Arm BPMs, fire injection one-shot, read TBT data | **Phase 2 read path + phase 4 (arm/inject)** |
| 8–9 | Detect injection turn, extract first-turn X/Y | ✓ Phase 2 |
| 10–11 | Plot ring trajectory, overlay reference | Plot ✓ Phase 2 (X/Y panels + hover); reference overlay → phase 3 |
| 12–14 | Compute orbit RMS, kick fits, dispersion | Phase 5 (analysis polish) |
| 15–17 | Run trajectory correction (response-matrix inverse → CM steps) | Phase 4 (threading workflow) |
| 18 | Save updated reference | Phase 3 |

This mapping makes the phase boundaries operationally concrete: phase 2
delivers the read half of step 7 and all of 8–9; the rest queues up
behind it.

---

## 9. Current status (2026-05-29)

- **Phase 1** (skeleton + hello-world IOC + WS bridge) — **complete**;
  proves the architecture round-trip end-to-end.
- **Phase 2** (read path) — **complete (2026-05-24)**. All four
  milestones closed; full suite **121 pytest + 5 Playwright** green.
  - **M1** — read pipeline, AppState wiring, IOC publish, e2e test.
    **Validated on the real ring 2026-05-20** (SR01C:BPM1 via CA, REST,
    browser). Surfaced and pinned five backend bugs.
  - **M2** — scaled to all 107 BPMs. M2-1 composition-time prefix loader
    (`load_bpm_prefixes`); M2-2 multi-BPM scale (`handle_acquire` ~1.2 s
    at N=107, under the 3 s budget); M2-3 live-ring browser render —
    surfaced two more backend fixes (EPICS_CA_ADDR_LIST localhost
    discovery; WS-bridge waveform coercion).
  - **M3** — failure handling: partial-fail / all-offline / timeout
    classification + CA-side concurrency rejection (caput while in-flight
    re-raises).
  - **M4** — raw-waveform REST endpoint (`/result/bpm/raw`), frontend
    hover tooltip + status-header timestamp, `SyntheticBpmReader` for
    ring-free e2e, and the Playwright trajectory spec.
- **Phase 3** (reference trajectory) — **next**; spec not yet drafted.
- **Phases 4–6** — not started. See §10.

The single-source-of-truth live tracker is
[`PyTxT-roadmap.html`](../PyTxT-roadmap.html) — open it in a browser
for the interactive view (clickable phase cards, what's-next list,
recent activity).

---

## 10. Roadmap

The phased delivery plan is locked in
[`PyTxT-project-plan.html`](../PyTxT-project-plan.html) (PI-owned;
generated 2026-05-04). Summarized here for reference:

| Phase | Theme | What it adds | Spec / plan |
|---|---|---|---|
| 1 | Skeleton + hello-world IOC | Repo scaffold, single PV, FastAPI + WS bridge | [spec](superpowers/specs/2026-05-06-phase-1-skeleton-design.md), [plan](superpowers/plans/2026-05-07-phase-1-skeleton.md) |
| 2 | Read path | CA client reads ~120 BPM TBT waveforms; publishes `RESULT:BPM:*`; browser renders trajectory | [spec](superpowers/specs/2026-05-18-phase-2-read-path-design.md), [plan](superpowers/plans/2026-05-19-phase-2-read-path.md), [decisions](superpowers/specs/2026-05-18-phase-2-decisions.md) |
| 3 | Reference trajectory | Load/save .mat reference files; publish `STATE:REF_LOADED`; overlay reference vs live in UI | not yet drafted |
| 4 | Threading workflow | Port `FirstTurnThreading.m` to pySC; `CMD:THREAD` triggers run; results to PVs; arm + inject one-shot | not yet drafted |
| 5 | Analysis polish | Kick fits, dispersion, RMS metrics; UI matches MATLAB GUI feature parity | not yet drafted |
| 6 | Hardening | Playwright e2e, integration tests against test IOC, CI build, deploy to appsdev2 | not yet drafted |

### Open questions to resolve as we go

- **Osprey integration shape** — HTTP, MCP, direct CA, or all three?
  Design for all three to be cheap to add until known.
- **MML black boxes** — `srinjectoneshot` and `steppv` hide their PV
  contracts. Resolution deferred to phase 4.
- **Test-IOC port isolation** — dev uses `OSPREY:TEST:TXT:*` +
  ports 59064/59065 per als-profiles safety rules; production
  uses real `TxT:*`. Config-driven from day 1 (`PYTXT_PV_PREFIX`).

---

## 11. Where to read next

| You want to know… | Read this |
|---|---|
| The north-star principles in their canonical form | [`CLAUDE.md`](../CLAUDE.md) |
| Locked scope / phased delivery / reference-material pointers | [`PyTxT-project-plan.html`](../PyTxT-project-plan.html) |
| Live status, recent commits, what's next | [`PyTxT-roadmap.html`](../PyTxT-roadmap.html) |
| The 18-step operator workflow (feature-parity target) | [`TxT_GUI_manual.pdf`](../TxT_GUI_manual.pdf) |
| Per-phase design rationale | `docs/superpowers/specs/*-design.md` |
| Per-phase implementation plans | `docs/superpowers/plans/*.md` |
| Gap-filling decisions taken during implementation | `docs/superpowers/specs/*-decisions.md` |
| Validation procedure for control-room phase milestones | [`docs/phase-2-m1-controlroom-validation.md`](phase-2-m1-controlroom-validation.md) |
| Authoritative PV namespace + .DESC strings | [`pytxt/ioc/pvs.py`](../pytxt/ioc/pvs.py) |
| Authoritative REST shape | run the app, open `/docs` (OpenAPI) |
| The MATLAB original (read-only mirror) | `legacy/TxT_GUI/`, `legacy/automated_startup/` |
| How to run / test locally | [`README.md`](../README.md) |

---

*This document is hand-maintained. Refresh it whenever a phase
milestone changes the public surface (new PVs, new endpoints, new
packages), or when the architectural picture shifts. The roadmap HTML
covers day-to-day status; this doc covers the durable picture.*
