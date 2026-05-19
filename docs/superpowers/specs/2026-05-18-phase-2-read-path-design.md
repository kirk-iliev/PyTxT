# PyTxT Phase 2 — Read Path (BPM TBT → Ring Trajectory)

**Status:** Design (drafted via brainstorming; awaiting Kirk's review)
**Date:** 2026-05-18
**Scope:** Phase 2 of 6 (per `PyTxT-project-plan.html`)
**Owner:** Kirk
**Drafted with:** Claude (Opus 4.7)
**Builds on:** [Phase 1 spec](2026-05-06-phase-1-skeleton-design.md)

---

## 1. Purpose

Phase 2 delivers the **read path**: the operator clicks **ACQUIRE** (or an agent writes `CMD:ACQUIRE`), and within ~2 seconds the browser renders a ring-trajectory plot showing each of ~120 storage-ring BPMs' first-turn X and Y position. The same data is published as EPICS PVs (`RESULT:BPM:*`) so any external CA subscriber sees the result identically.

Phase 1 proved the architecture round-trip with a trivial command (`PING`). Phase 2 is the first feature with real beam-physics meaning. It fills the previously-empty `pytxt/domain/` and `pytxt/ca_client/` packages without restructuring anything from phase 1 — every new file lands in a home that already exists.

Phase 2 does **not** arm BPMs, trigger injection, or write anything upstream. It reads whatever TBT data the BPM IOCs currently hold in their buffers and extracts the first-turn ring trajectory.

---

## 2. North-star principles binding this design

The five north-star principles from `CLAUDE.md` and the [phase-1 spec §2](2026-05-06-phase-1-skeleton-design.md#2-north-star-principles-binding-for-this-design) continue to apply. Phase 2's concrete obligations under each:

- **Agent-callable first** — `CMD:ACQUIRE` exists as both a PV and `POST /api/v1/cmd/acquire`. Same handler. The keystone parity test grows by one parametrize row.
- **PVs are the canonical state interface** — every analysis output is a PV. Raw waveforms (which are too large for PV semantics) are exposed via REST per principle #3, not hidden in process memory.
- **REST/WS handles only what PVs can't** — exactly one new REST endpoint (`GET /api/v1/result/bpm/raw`) for bulk raw-waveform transfer; everything else flows through PVs.
- **Forward-looking package layout** — every phase-2 file lands in a package that already exists from phase 1.
- **Domain logic is I/O-free** — the injection-turn detection and first-turn extraction live in `pytxt/domain/` with zero caproto / asyncio / FastAPI imports, testable in milliseconds with synthesized numpy arrays.

---

## 3. Architectural recap — where phase 2 lands on the phase-1 foundation

```
                                      ┌──────────────────────────┐
                                      │ BPM IOCs (LBL controls)  │
                                      │ ~120 × {wfr:TBT:c0,c1,    │
                                      │         c3,armed}         │
                                      └──────────────┬───────────┘
                                                     │ CA reads (persistent
                                                     │ connections, on-demand
                                                     │ read on ACQUIRE)
                                                     ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                  AppState (single source of truth)                      │
│                                                                         │
│  heartbeat, last_ping_at, ping_count, version, started_at   ← phase 1   │
│  bpm_prefixes: list[str]                ← NEW (loaded once at startup)  │
│  acquire_in_flight: bool                ← NEW                           │
│  last_acquire: LastAcquireResult | None ← NEW                           │
│  last_acquire_raws: dict[str, RawBPM]   ← NEW (in-memory, 1 snapshot)   │
└─────────▲──────────────────────────────────────────┬────────────────────┘
          │                                          │
          │ mutate via handler                       │ mirror via IOC publisher
          │                                          ▼
   ┌──────┴──────┐                       ┌──────────────────────────┐
   │ handlers/   │                       │ External surface         │
   │  ping       │ ← phase 1             │  - CMD:PING PV           │ phase 1
   │  acquire    │ ← NEW                 │  - POST /cmd/ping        │ phase 1
   └─────────────┘                       │  - CMD:ACQUIRE PV        │ NEW
          ▲                              │  - POST /cmd/acquire     │ NEW
          │                              │  - RESULT:BPM:* PVs      │ NEW
   ┌──────┴──────┐                       │  - STATE:ACQUIRE_* PVs   │ NEW
   │ Triggers    │                       │  - GET /api/v1/state     │ extended
   │  CMD:ACQUIRE│                       │  - GET /api/v1/result    │ NEW
   │  POST /cmd/ │                       │       /bpm/raw           │
   │     acquire │                       └──────────────────────────┘
   └─────────────┘
```

**Invariants preserved from phase 1:**

1. Every CMD is one Python function called by both the IOC dispatcher and the REST route. No transport-specific code paths exist.
2. AppState is the single source of in-process truth; the IOC publisher mirrors changes outward to PVs. Handlers never write to PVs directly.
3. The PV namespace (`OSPREY:TEST:TXT:*` dev, `TxT:*` prod) is config-driven; no hardcoding.

---

## 4. Package additions

| Package | Phase-1 state | Phase-2 additions |
|---|---|---|
| `pytxt/domain/` | Empty scaffold | `types.py`, `injection_turn.py`, `first_turn_extract.py` |
| `pytxt/ca_client/` | Empty scaffold | `bpm_reader.py` |
| `pytxt/state/` | `app_state.py` | Extend `AppState` dataclass with 4 new fields |
| `pytxt/handlers/` | `ping.py` | `acquire.py` |
| `pytxt/ioc/` | `pvs.py`, `server.py` | Extend `pvs.py` (new `pvproperty` defs); extend `server.py` field-map |
| `pytxt/api/` | `routes/{health,state,cmd}.py`, schemas, `ws_bridge.py` | Extend `cmd.py` (add `acquire` route); new `routes/result.py`; extend `schemas/` |
| `pytxt/config/` | `settings.py` | Add `bpm_prefixes_path` setting; new `bpm_prefixes.txt` data file (one-time MATLAB dump) |
| `pytxt/frontend/` | Phase-1 page | New `trajectory.html`, `trajectory.js`; extend `connection.js` to also call `/cmd/acquire` |
| `tests/unit/` | Existing | New: `test_injection_turn.py`, `test_first_turn_extract.py`, `test_handlers_acquire.py` |
| `tests/integration/` | Existing | New: `test_bpm_reader.py`, `test_acquire_via_ca.py`, `test_acquire_via_rest.py`, `test_result_raw_endpoint.py`; extend `test_parity.py` (one new parametrize row) |
| `tests/e2e/` | `smoke.spec.js`, `ping.spec.js` | New: `trajectory.spec.js` |
| `tests/conftest.py` | Existing fixtures | New: `fake_bpm_ioc_fixture` (parametric N) |

**Zero structural changes from phase 1.** Every new file lands in a package that already exists.

---

## 5. Phase 2 feature surface

### 5.1 New PVs published by the IOC

Prefix is config-driven (`OSPREY:TEST:TXT:` dev, `TxT:` prod). All PVs carry `.DESC` per the discoverability principle.

| PV | Type | Dir | Description |
|---|---|---|---|
| `<prefix>CMD:ACQUIRE` | int | WO | Write any value to trigger BPM acquisition; value ignored |
| `<prefix>STATE:ACQUIRE_IN_FLIGHT` | int (0/1) | RO | 1 while acquisition in progress; rejects concurrent `CMD:ACQUIRE` writes |
| `<prefix>STATE:LAST_ACQUIRE_STATUS` | int | RO | Enum: 0=NEVER, 1=ACQUIRING, 2=OK, 3=PARTIAL, 4=FAILED. The same logical value appears as a string in REST responses (`LastAcquireResult.status`) — the int↔string mapping is canonical and lives in one place (`pytxt/api/schemas/result.py`). |
| `<prefix>STATE:LAST_ACQUIRE_OK_COUNT` | int | RO | BPMs that returned valid data on the most recent ACQUIRE |
| `<prefix>STATE:LAST_ACQUIRE_FAIL_COUNT` | int | RO | BPMs that timed out or returned invalid data |
| `<prefix>STATE:LAST_ACQUIRE_FAILED_BPM_NAMES` | string array, variable length | RO | Names of failed BPMs (empty array if none) |
| `<prefix>STATE:LAST_ACQUIRE_TIMESTAMP` | string (ISO8601) | RO | When the last acquisition finished; empty before first ACQUIRE |
| `<prefix>STATE:LAST_ACQUIRE_FAIL_REASON` | string | RO | Short message when status=FAILED; empty otherwise |
| `<prefix>RESULT:BPM:X_FIRST_TURN` | waveform[N_BPM], float64, mm | RO | Per-BPM X position at detected injection turn; NaN for failed |
| `<prefix>RESULT:BPM:Y_FIRST_TURN` | waveform[N_BPM], float64, mm | RO | Per-BPM Y position at detected injection turn; NaN for failed |
| `<prefix>RESULT:BPM:SUM_FIRST_TURN` | waveform[N_BPM], float64, AU | RO | Per-BPM sum signal at detected injection turn; NaN for failed |
| `<prefix>RESULT:BPM:INJECTION_TURN` | waveform[N_BPM], int32 | RO | Per-BPM detected turn index (sample offset into 100k buffer); −1 for failed |
| `<prefix>RESULT:BPM:NAMES` | string array[N_BPM] | RO | Static-after-startup; canonical BPM prefix per array index — the cross-reference that lets subscribers map array index → BPM identity |

**Note on `LAST_ACQUIRE_FAILED_BPM_NAMES`:** caproto string arrays support variable-length encoding; the PV's actual length on each update equals `fail_count`. A subscriber reading this PV always sees the failed BPMs from the most recent acquisition.

**Divergence from phase-1 forward-look sketch (§13):** the phase-1 spec sketched `STATE:CURRENT_TRAJ_X` and `CMD:READOUT`. Phase 2 uses `RESULT:BPM:X_FIRST_TURN` and `CMD:ACQUIRE` to align with the project plan's documented `TxT:RESULT:BPM:*` namespace (project plan §"PV Namespace") and standard English ("acquire" is what the MATLAB GUI button says). The forward-look was illustrative; this is the actual.

### 5.2 New / extended REST endpoints

| Method | Path | Body / Query | Response | Purpose |
|---|---|---|---|---|
| `POST` | `/api/v1/cmd/acquire` | `{}` (no params) | `AcquireResponse` | Trigger acquisition; calls same handler as `CMD:ACQUIRE` PV |
| `GET` | `/api/v1/result/bpm/raw` | `?bpm=<prefix>` (required) | `BpmRawWaveforms` | Bulk raw waveforms for one BPM from the most recent acquisition |
| `GET` | `/api/v1/state` | — | extended `StateSnapshot` | Now includes `last_acquire`, `acquire_in_flight`, `bpm_prefixes` |

**`?bpm=` is required, not optional.** A no-param "all BPMs" version would be ~144 MB JSON — too large for a single response. If bulk all-BPM transfer ever becomes needed, that's a separate streaming endpoint (deferred). One-BPM-at-a-time still satisfies the agent-callable principle: an agent can iterate over `RESULT:BPM:NAMES` and fetch each.

**`GET /api/v1/result/bpm/raw?bpm=X`:**

- 200 OK with `BpmRawWaveforms` JSON if X is in `bpm_prefixes` and an acquisition has completed.
- 404 if X is not in the configured BPM list.
- 409 if no acquisition has completed yet (raw cache is empty).
- 400 if `bpm` query param is missing or empty.

### 5.3 Pydantic schemas (sketches)

```python
class LastAcquireResult(BaseModel):
    status: Literal["NEVER", "ACQUIRING", "OK", "PARTIAL", "FAILED"]
    ok_count: int
    fail_count: int
    failed_bpm_names: list[str]
    injection_turn_median: int           # convenience summary across per-BPM array
    timestamp: datetime | None
    fail_reason: str = ""                # populated when status=FAILED

class AcquireResponse(BaseModel):
    status: Literal["OK", "PARTIAL", "FAILED"]
    ok_count: int
    fail_count: int
    failed_bpm_names: list[str]
    injection_turn_median: int
    timestamp: datetime

class BpmRawWaveforms(BaseModel):
    bpm_prefix: str                      # e.g. "SR01C:BPM1"
    x_nm: list[int]                      # 100000 samples, raw nm (no mm conversion)
    y_nm: list[int]
    sum_au: list[int]
    armed: int                           # 0 = data was valid at read time
    read_timestamp: datetime

class StateSnapshot(BaseModel):           # extended from phase 1
    # phase 1 fields
    version: str
    heartbeat: int
    uptime_s: float
    last_ping_at: str | None
    ping_count: int
    # phase 2 additions
    bpm_prefixes: list[str]
    acquire_in_flight: bool
    last_acquire: LastAcquireResult
```

### 5.4 Browser page additions

A new page at `/trajectory.html` (the phase-1 page at `/` is preserved unchanged). Layout follows the original MATLAB `TxT_GUI.mlapp` "Trajectory" view (verified by inspecting `legacy/TxT_GUI/_unpacked/TxT_GUI.m` lines 180–185): **two stacked panels, X above Y**, each panel plotting position vs BPM index.

- **Status header** (top): `RING TRAJECTORY · <timestamp> · <ok_count> OK · <fail_count> FAIL`
- **Panel 1 (X, mm)** — Canvas, full width, ~110px tall; horizontal axis = BPM index 0..119; vertical axis ±range mm; dashed zero line; NaN gaps shown as broken-line segments.
- **Panel 2 (Y, mm)** — identical structure, color-distinguished from X.
- **Controls row**: primary `[▶ ACQUIRE]` button; (deferred to phase 3+) auto-refresh toggle; metadata readout (`turn: <median injection_turn> · range: ±<auto>mm`).
- **Hover**: tooltip on hover over a BPM shows its name (from `RESULT:BPM:NAMES`) and exact X/Y values.

The page subscribes via WS to `RESULT:BPM:X_FIRST_TURN`, `Y_FIRST_TURN`, `INJECTION_TURN`, `STATE:LAST_ACQUIRE_*`, and `RESULT:BPM:NAMES`. The ACQUIRE button issues `POST /api/v1/cmd/acquire`.

---

## 6. Component design

### 6.1 `pytxt/domain/types.py`

```python
@dataclass(frozen=True)
class RawBPM:
    prefix: str
    x_wf: np.ndarray         # shape (100000,), dtype int32, units nm
    y_wf: np.ndarray
    sum_wf: np.ndarray
    armed: int               # 0 = data was valid at read time
    read_timestamp: datetime

@dataclass(frozen=True)
class FirstTurnResult:
    x_first_turn: np.ndarray         # (n_bpms,) float64, mm, NaN for failed
    y_first_turn: np.ndarray
    sum_first_turn: np.ndarray
    injection_turn: np.ndarray       # (n_bpms,) int32, -1 for failed
    failed_bpm_names: list[str]
```

`RawBPM` is owned by `domain/` (the canonical shape) even though `ca_client/` is what populates it. This preserves the dependency direction: `ca_client/` imports from `domain/`, never the reverse.

### 6.2 `pytxt/domain/injection_turn.py`

```python
def detect_injection_turn(sum_waveform: np.ndarray) -> int:
    """Find the sample index of the injection turn for one BPM.

    Per MATLAB SCexp_ALS_readoutBPMs.m: argmax of diff(sum), with
    fallback to 1370 if the result falls outside [100, 4500].
    """
    idx = int(np.argmax(np.diff(sum_waveform)))
    return 1370 if idx < 100 or idx > 4500 else idx
```

Pure function. No caproto. Testable with synthesized arrays in microseconds.

### 6.3 `pytxt/domain/first_turn_extract.py`

```python
def extract_first_turn(raws: dict[str, RawBPM | None]) -> FirstTurnResult:
    """Convert per-BPM raw waveforms into the first-turn extracted arrays.

    Ordered dict preserves BPM-index alignment. None entries produce NaN/−1
    sentinels and add the prefix to failed_bpm_names. Per-BPM injection turn
    is detected independently (matches MATLAB — BPMs may be offset by a few
    turns from each other).
    """
    n = len(raws)
    x = np.full(n, np.nan)
    y = np.full(n, np.nan)
    sum_val = np.full(n, np.nan)
    injection_turn = np.full(n, -1, dtype=np.int32)
    failed = []
    for i, (prefix, raw) in enumerate(raws.items()):
        if raw is None:
            failed.append(prefix)
            continue
        idx = detect_injection_turn(raw.sum_wf)
        injection_turn[i] = idx
        x[i] = raw.x_wf[idx] / 1e6      # nm → mm
        y[i] = raw.y_wf[idx] / 1e6
        sum_val[i] = float(raw.sum_wf[idx])
    return FirstTurnResult(x, y, sum_val, injection_turn, failed)
```

### 6.4 `pytxt/ca_client/bpm_reader.py`

```python
class BpmReader:
    """Persistent-connection caproto Context that holds connections to ~480
    BPM PVs (120 BPMs × {c0, c1, c3, armed}) and reads them on demand.

    Connections open at startup (or first use). ACQUIRE triggers parallel
    reads via asyncio.gather; each read has a per-PV timeout. Missing/bad
    BPMs come back as None in the result dict.
    """

    def __init__(self, prefixes: list[str], per_pv_timeout_s: float = 2.0):
        self._prefixes = prefixes
        self._timeout = per_pv_timeout_s
        self._ctx = caproto.asyncio.client.Context()
        self._pvs: dict[str, list[caproto.asyncio.client.PV]] = {}   # prefix → [c0, c1, c3, armed]

    async def start(self) -> None:
        """Open and cache connections to all 480 PVs. Fails loudly if zero connect."""
        # ...build PV objects via ctx.get_pvs(), verify at least one BPM resolves

    async def read_all(self) -> dict[str, RawBPM | None]:
        """Parallel read of all configured BPMs. Returns ordered dict aligned with prefixes."""
        # ...asyncio.gather with per-task timeout, normalize to RawBPM or None
```

### 6.5 `pytxt/handlers/acquire.py`

```python
async def handle_acquire(state: AppState, reader: BpmReader) -> AcquireResponse:
    """Orchestrate one acquisition. Same function whether called from
    IOC CMD putter or REST POST route — agentic parity by construction."""

    if state.acquire_in_flight:
        raise AcquisitionInFlightError("ACQUIRE already in progress")

    try:
        await state.update(
            acquire_in_flight=True,
            last_acquire=_with_status(state.last_acquire, "ACQUIRING"),
        )

        raws = await reader.read_all()
        result = extract_first_turn(raws)

        status = _classify_status(result)
        last = LastAcquireResult(
            status=status,
            ok_count=len(raws) - len(result.failed_bpm_names),
            fail_count=len(result.failed_bpm_names),
            failed_bpm_names=result.failed_bpm_names,
            injection_turn_median=int(np.median(result.injection_turn[result.injection_turn >= 0]))
                                  if (result.injection_turn >= 0).any() else -1,
            timestamp=datetime.now(timezone.utc),
        )

        await state.update(
            last_acquire=last,
            last_acquire_raws=raws,   # in-memory snapshot for /result/bpm/raw
        )
        return AcquireResponse.from_last_acquire(last)

    except Exception as e:
        await state.update(
            last_acquire=_failed(str(e)),
        )
        raise
    finally:
        await state.update(acquire_in_flight=False)
```

Try/finally guarantees `acquire_in_flight` is always cleared, even on exception.

### 6.6 `pytxt/state/app_state.py` (extension)

Phase 1's `AppState` dataclass gets four new fields:

```python
@dataclass
class AppState:
    # phase 1 fields unchanged ...

    # phase 2 additions
    bpm_prefixes: list[str] = field(default_factory=list)
    acquire_in_flight: bool = False
    last_acquire: LastAcquireResult = field(default_factory=lambda: LastAcquireResult(status="NEVER", ok_count=0, fail_count=0, failed_bpm_names=[], injection_turn_median=-1, timestamp=None))
    last_acquire_raws: dict[str, RawBPM] = field(default_factory=dict)
```

The existing `update()` / listener mechanism handles all four. `last_acquire_raws` is the **only** field that's intentionally **not** mirrored to PVs (raw waveforms are too large for PV semantics; they're served via REST on demand).

### 6.7 `pytxt/ioc/server.py` (field → PV map extension)

The explicit `field → pvproperty` mapping in `server.py` grows by entries for each new published field. `last_acquire` is a structured field, so its publication unpacks into multiple PVs:

```python
APP_STATE_TO_PV_MAP = {
    # phase 1 entries unchanged ...

    # phase 2 — single-field-to-single-PV
    "acquire_in_flight": pvs.state_acquire_in_flight,

    # phase 2 — structured field-to-multi-PV (special handler)
    "last_acquire": _publish_last_acquire,        # unpacks to STATE:LAST_ACQUIRE_* and RESULT:BPM:*
    "bpm_prefixes": _publish_bpm_names,           # publishes RESULT:BPM:NAMES once at startup
}
```

`_publish_last_acquire(pvs_group, value)` writes the status, counts, names, timestamp, and the four RESULT:BPM:* waveforms in sequence. They are **not** atomic from an external observer's perspective — see §7.

### 6.8 `pytxt/api/routes/result.py` (new)

One endpoint:

```python
@router.get("/result/bpm/raw", response_model=BpmRawWaveforms)
async def get_bpm_raw(bpm: str, app_state: AppState = Depends(...)) -> BpmRawWaveforms:
    if not bpm:
        raise HTTPException(400, "bpm query param required")
    if bpm not in app_state.bpm_prefixes:
        raise HTTPException(404, f"BPM '{bpm}' not in configured list")
    if not app_state.last_acquire_raws:
        raise HTTPException(409, "no acquisition has completed yet")
    raw = app_state.last_acquire_raws.get(bpm)
    if raw is None:
        raise HTTPException(409, f"BPM '{bpm}' failed in most recent acquisition")
    return BpmRawWaveforms.from_raw(raw)
```

### 6.9 `pytxt/api/routes/cmd.py` (extension)

```python
@router.post("/cmd/acquire", response_model=AcquireResponse)
async def cmd_acquire(
    app_state: AppState = Depends(...),
    reader: BpmReader = Depends(...),
) -> AcquireResponse:
    try:
        return await handle_acquire(app_state, reader)
    except AcquisitionInFlightError as e:
        raise HTTPException(409, str(e))
```

### 6.10 `pytxt/frontend/` additions

- **`trajectory.html`** — semantic structure: header row, two `<canvas>` elements stacked, controls row.
- **`js/trajectory.js`** — page logic:
  - On load, subscribe via `connection.subscribe()` to the seven phase-2 PVs.
  - On each update, store latest in a local cache and call `render()`.
  - `render()` draws zero line, axis labels, connected polyline with NaN-gap breaks, hover-tooltip handler.
  - ACQUIRE button → `connection.command("acquire", {})`.
- **`js/connection.js`** — no API change; the existing `connection.command()` helper already handles arbitrary command names.
- **`css/theme.css`** — add `--canvas-bg`, `--canvas-x`, `--canvas-y`, `--canvas-grid` custom properties; reused by future plots.

The phase-1 page at `/` is preserved. A new top-of-page nav link added to both: `[Ping (phase 1)] [Trajectory (phase 2)]`.

### 6.11 `pytxt/config/` additions

- **`settings.py`** — new field:
  ```python
  bpm_prefixes_path: Path = Path("pytxt/config/bpm_prefixes.txt")
  ```
- **`pytxt/config/bpm_prefixes.txt`** — committed file, one BPM prefix per line, comments with `#`:
  ```
  # ALS storage-ring TBT BPM prefixes
  # Sourced <YYYY-MM-DD of dump, filled in during M2> from MATLAB on appsdev2:
  #   b = getbpmlist('nonBergoz'); b([1 2 8 37],:) = [];
  #   n = getname('BPMx', b); for i=1:size(n,1); disp(n(i,:)); end
  # ~120 entries after MML exclusions [1 2 8 37]
  SR01C:BPM1
  SR01C:BPM2
  ...
  ```
- **`composition.py`** — at startup, reads the file, parses, populates `app_state.bpm_prefixes`, then constructs `BpmReader(prefixes)`.

### 6.12 `pytxt/composition.py` extension

The wiring grows by one block: construct `BpmReader`, call `await reader.start()`, register `reader` as a dependency-injection source for the acquire handler. One line in the `gather()` call to keep the reader alive.

---

## 7. Data flow during ACQUIRE

The end-to-end trace of one acquisition. Same flow whether triggered by CA write or REST POST.

```
 1. Trigger arrives
    ├─ CA write to <prefix>CMD:ACQUIRE  ─┐
    └─ POST /api/v1/cmd/acquire         ─┤── both call:
                                          │      handle_acquire(state, reader)
 2. Handler: concurrency check
    └─ if state.acquire_in_flight: raise AcquisitionInFlightError
       ├─ CA path: caproto returns alarm severity to the writer
       └─ REST path: 409 Conflict

 3. Handler: set in_flight, publish STATE
    state.update(acquire_in_flight=True,
                 last_acquire=<...status=ACQUIRING>)
    └─ IOC publisher mirrors → STATE:ACQUIRE_IN_FLIGHT=1,
                               STATE:LAST_ACQUIRE_STATUS=1

 4. Handler: parallel CA reads via ca_client.bpm_reader.read_all()
    │   uses persistent caproto Context (connections held from startup)
    │   asyncio.gather over ~480 reads (120 BPMs × {c0,c1,c3,armed})
    │   per-PV timeout = 2.0 s (configurable)
    │   missing/timed-out BPMs → None in the result dict
    └─ returns dict[prefix, RawBPM | None]

 5. Handler: domain analysis (pure numpy, no I/O)
    │   for each prefix in order:
    │     if raw is None: NaN/−1 sentinels, add to failed_names
    │     else: detect_injection_turn(raw.sum_wf), extract X/Y/sum
    └─ returns FirstTurnResult

 6. Handler: update AppState (single mutation point)
    state.update(
        last_acquire=LastAcquireResult(<status, counts, names, ts, ...>),
        last_acquire_raws=raws,
    )

 7. IOC publisher fires for each updated field
    └─ writes new values to all RESULT:BPM:* and STATE:LAST_ACQUIRE_* PVs
    └─ CA monitor events fire to all subscribers (Phoebus, agents, WS bridge)

 8. Handler: finally block clears in_flight
    state.update(acquire_in_flight=False)
    └─ IOC publisher mirrors → STATE:ACQUIRE_IN_FLIGHT=0

 9. Handler returns AcquireResponse
    ├─ REST path: serialize as response body
    └─ CA path: caproto returns success to the CA write

10. WS bridge propagates CA monitor events to browser
    └─ trajectory.js receives X_FIRST_TURN, Y_FIRST_TURN, etc.
    └─ re-renders the stacked Canvas plot
```

**Latency expectation:** persistent connections + `asyncio.gather` for 120 BPMs ≈ **0.5–2 seconds**. Domain analysis on 100k-sample arrays is microseconds. End-to-end target: **under 3 seconds**, dominated by CA roundtrip.

**Raw-waveform retention:** only the **last** acquisition's raw waveforms (~144 MB) are kept in `state.last_acquire_raws`. Each ACQUIRE overwrites. No history. Agents/operators that want older snapshots must capture them out-of-band.

**Concurrency model:** explicit reject on concurrent ACQUIRE. No queueing, no silent waiting. An operator double-click or two competing agents each get a clean 409 / CA alarm.

**Atomicity of step 6→7:** the AppState mutation in step 6 is one Python call; the IOC publisher fires N PV updates in sequence (not transactional). External subscribers may briefly see `X_FIRST_TURN` updated before `Y_FIRST_TURN`. This is standard CA behavior — Phoebus screens handle it routinely. We don't try to fake atomicity.

---

## 8. Error handling

| Layer | Failure mode | Response |
|---|---|---|
| **Domain** | `argmax` outside [100, 4500] | Built-in fallback to sample 1370 (port of MATLAB) |
| **Domain** | empty / malformed waveform | Caller (handler) ensures input shape; domain assumes valid input |
| **CA client (startup)** | `read_all` returns 0 successful reads on first try | **Fail startup** with clear log: "no BPMs reachable; check EPICS_CA_ADDR_LIST and BPM IOC status" |
| **CA client (per-read)** | Timeout (>per_pv_timeout_s) or wrong dtype/shape | Return `None` for that prefix in the `read_all()` result dict |
| **CA client (mid-run)** | Connection lost during an ACQUIRE | Affected reads return `None`; caproto reconnects in background for next ACQUIRE |
| **Handler** | `acquire_in_flight` collision | Raise `AcquisitionInFlightError` → CA: alarm severity; REST: 409 Conflict |
| **Handler** | All N BPMs returned `None` | `status=FAILED`; result PVs **still published** with all-NaN (so external observers can distinguish "never ran" from "ran but all failed") |
| **Handler** | Unexpected exception in domain code | `status=FAILED`; log full traceback; short message into `STATE:LAST_ACQUIRE_FAIL_REASON`; `in_flight` cleared by `finally` |
| **IOC publisher** | Failed to write a PV | Log error; continue (do not break the publish chain). State-PV drift impossible by construction; if observed, log loudly. |
| **REST `/result/bpm/raw`** | BPM not in list | 404 with body explaining valid set comes from `RESULT:BPM:NAMES` |
| **REST `/result/bpm/raw`** | No acquisition completed yet, or this BPM failed in most recent | 409 with explanation |
| **Startup** | `config/bpm_prefixes.txt` missing | Fail with clear message; do not start with a default list |
| **Startup** | `config/bpm_prefixes.txt` malformed (blank lines OK, non-prefix tokens not) | Fail with line number of first invalid line |

**The principle:** recoverable errors (one BPM timing out) get sentinels (NaN, −1) and surface in count PVs. Errors that mean "the system isn't working" (no config, no BPMs reachable) fail loudly at startup rather than silently degrading. Errors mid-acquisition update state PVs to reflect what happened — never crash silently, never leave `acquire_in_flight=True` on exception.

---

## 9. Configuration

### 9.1 Settings additions

```python
class Settings(BaseSettings):
    # phase 1 fields unchanged ...

    # phase 2 additions
    bpm_prefixes_path: Path = Path("pytxt/config/bpm_prefixes.txt")
    bpm_read_timeout_s: float = 2.0
```

### 9.2 The BPM prefix file

`pytxt/config/bpm_prefixes.txt` is **checked into the repo**, one prefix per line, `#` comments allowed. Source: a one-time MATLAB dump from appsdev2 (the MML database — `getbpmlist('nonBergoz')` with indices `[1 2 8 37]` removed — is the only authoritative source; channel-finder does not catalog TBT PVs per [memory: bpm-tbt-pv-pattern-confirmed]).

Refresh procedure (documented in the file header): re-run the MATLAB one-liner on appsdev2 when BPM topology changes (hardware swap). Expected change rate: once every few years.

### 9.3 Phase 1 settings unchanged

PV prefix, IOC port, API port, log level, heartbeat interval — all carry over from phase 1. Belt-and-suspenders dev/prod isolation (PV prefix + CA port double-gate) continues to apply.

---

## 10. Testing strategy

### 10.1 Three tiers, extended

| Tier | Phase-1 count | Phase-2 additions | Total after phase 2 |
|---|---|---|---|
| Unit | 4 files | +3: `test_injection_turn`, `test_first_turn_extract`, `test_handlers_acquire` | 7 |
| Integration | 7 files | +4: `test_bpm_reader`, `test_acquire_via_ca`, `test_acquire_via_rest`, `test_result_raw_endpoint`; +1 parametrize row to `test_parity` | 11 |
| E2E | 2 files | +1: `trajectory.spec.js` | 3 |

### 10.2 Unit tests

- **`test_injection_turn.py`**: argmax in middle of waveform; argmax at sample 99 → fallback 1370; argmax at sample 4501 → fallback 1370; flat waveform (no peak) — verify behavior; single dramatic peak — verify exact detection.
- **`test_first_turn_extract.py`**: all valid BPMs → all populated; mix of None and valid → correct NaN placement; all None → all NaN, all failed_names present; BPM-index alignment preserved when input dict has specific ordering; nm→mm conversion correct.
- **`test_handlers_acquire.py`**: happy path with mocked reader; in-flight collision raises `AcquisitionInFlightError`; all-fail path sets status=FAILED but updates AppState; unexpected exception clears `in_flight`; AcquireResponse fields match LastAcquireResult.

### 10.3 Integration tests — the fake BPM IOC fixture

`tests/conftest.py` adds:

```python
@pytest.fixture
def fake_bpm_ioc(request) -> Iterator[FakeBpmIoc]:
    """Spin up N caproto IOCs serving fake BPM PVs with deterministic data.

    Parametrize N via request.param. Each fake BPM serves wfr:TBT:{c0,c1,c3,armed}
    with synthesized waveforms containing a known injection peak at sample 1370.
    Supports fault injection: bpm.simulate_timeout(), bpm.disconnect(), etc.
    """
```

Tests use it via `@pytest.mark.parametrize("fake_bpm_ioc", [1, 5, 120], indirect=True)` to exercise different scales.

- **`test_bpm_reader.py`**: connect to 1 BPM, read returns RawBPM; connect to 5, parallel read; simulate timeout on one of 5, others succeed; simulate wrong dtype, returns None; connection loss mid-read returns None for affected.
- **`test_acquire_via_ca.py`**: CA write to CMD:ACQUIRE triggers full pipeline; RESULT:BPM:X_FIRST_TURN updates with expected values; STATE:LAST_ACQUIRE_OK_COUNT correct.
- **`test_acquire_via_rest.py`**: POST /cmd/acquire returns AcquireResponse; same state changes observable via CA monitor.
- **`test_result_raw_endpoint.py`**: 200 for valid BPM after acquire; 400 for missing query; 404 for BPM not in list; 409 before any acquire / for failed BPM.
- **`test_parity.py`** (extended): one new parametrize argument: `("acquire", caput_command, http_post_command)`. The test body is unchanged — only the parameter set grows.

### 10.4 E2E test

**`trajectory.spec.js`**: navigate to `/trajectory.html`; assert canvases present; click ACQUIRE; wait for status header to show `OK · 1 OK · 0 FAIL` (against single fake BPM in the test fixture); assert pixel data in both canvases is non-empty; assert hover on canvas shows tooltip.

### 10.5 What's NOT tested

- **No tests against real beam.** All automated tests use the fake BPM IOC fixture. Manual validation against real BPMs (probe-style) is a deployment activity, not a CI activity.
- **No load tests.** Phase 2 is single-user single-snapshot; throughput is not a concern.
- **No tests of the MATLAB `1370` constant being correct.** It is correct because MATLAB says so; we port the value as-is.

---

## 11. Build sequence — 4 milestones

Following the vertical-slice approach: 1 BPM end-to-end first, then scale, then failure handling, then polish.

### M1 — Vertical slice, 1 real BPM (~3 days)

- Hardcoded prefix list `["SR01C:BPM1"]`.
- Real CA reads via `BpmReader` (validated by the existing `scripts/probe_bpm.py`).
- Real domain code: `detect_injection_turn` + `extract_first_turn` operating on length-1 arrays.
- `handle_acquire` wired; `CMD:ACQUIRE` PV + `POST /cmd/acquire` route added.
- `RESULT:BPM:X_FIRST_TURN` and friends as length-1 waveforms; `STATE:ACQUIRE_*` PVs in.
- `trajectory.html` + `trajectory.js` with stacked panels rendering one datapoint per axis.
- Tests: full domain unit suite; parity test grows by one row.
- **DoD:** click ACQUIRE in the browser, see real `SR01C:BPM1` first-turn position render. Same effect via `caput OSPREY:TEST:TXT:CMD:ACQUIRE 1`.

### M2 — Scale to all ~120 BPMs (~2 days)

- BPM list loads from `pytxt/config/bpm_prefixes.txt` (one-time MATLAB dump, committed).
- `read_all` uses `asyncio.gather`; RESULT waveforms become length-N (N ≈ 120).
- Frontend renders connected polylines in stacked panels.
- Tests: ca_client integration tests with multi-BPM fake IOC fixture.
- **DoD:** ACQUIRE completes in <3s end-to-end; ring trajectory visible across all ~120 BPMs.

### M3 — Failure handling (~2 days)

- Per-PV 2 s timeout, NaN propagation, state PVs for counts / names.
- `try/finally` around `in_flight` flag.
- 409 / CA alarm for concurrent ACQUIRE.
- Tests: timeout-simulation, partial-fail, all-fail scenarios.
- **DoD:** simulated timeout produces NaN gap in plot + correct fail count in state PV; concurrent ACQUIRE returns 409 cleanly.

### M4 — Raw REST + UI polish + e2e (~2 days)

- `GET /result/bpm/raw?bpm=X` implementation; 400/404/409 paths.
- Frontend: axis labels, ticks, hover-tooltip (BPM name + values on hover).
- Status header shows `<ok> OK · <fail> FAIL · <timestamp>`.
- Playwright e2e: full click-ACQUIRE-render-plot cycle against single fake BPM.
- **DoD:** e2e passes; raw endpoint returns valid `BpmRawWaveforms` JSON for one BPM.

**Total estimate:** ~9 working days. Each milestone is a coherent commit / PR / demo unit.

---

## 12. Definition of done

Phase 2 is shippable when **all** of the following pass:

1. `python -m pytxt` runs locally; the trajectory page at `http://localhost:8008/trajectory.html` loads.
2. With `pytxt/config/bpm_prefixes.txt` populated with the real ALS BPM list and the app running on appsdev2 (or any host on the ALS subnet), clicking **ACQUIRE** completes in <3 seconds and renders a ring trajectory across all ~120 BPMs.
3. `caput OSPREY:TEST:TXT:CMD:ACQUIRE 1` from a separate terminal triggers the same effect; `caget OSPREY:TEST:TXT:RESULT:BPM:X_FIRST_TURN` returns the same waveform the browser displayed.
4. `caget OSPREY:TEST:TXT:STATE:LAST_ACQUIRE_OK_COUNT` and `:FAIL_COUNT` return values matching the on-screen status header.
5. `curl http://localhost:8008/api/v1/state` returns JSON including the new `last_acquire`, `acquire_in_flight`, `bpm_prefixes` fields.
6. `curl -X POST http://localhost:8008/api/v1/cmd/acquire -d '{}' -H 'Content-Type: application/json'` returns an `AcquireResponse` matching what `RESULT:BPM:*` PVs report.
7. `curl 'http://localhost:8008/api/v1/result/bpm/raw?bpm=<one-real-BPM-prefix>'` returns valid `BpmRawWaveforms` JSON.
8. Concurrent ACQUIRE attempts return 409 (REST) / CA alarm (CA) cleanly with no state corruption.
9. With one BPM simulated as unreachable (e.g. wrong prefix in the config file), ACQUIRE returns PARTIAL status with `fail_count=1` and that BPM appears as NaN in the result waveforms.
10. `make test` passes — all three tiers, including the extended parity test.
11. `make test-e2e` passes — the trajectory Playwright spec.
12. `curl http://localhost:8008/openapi.json` includes the new `acquire`, `result/bpm/raw`, and extended `state` endpoints with descriptions.

When all 12 are true, phase 2 is complete and phase 3 may begin.

---

## 13. Explicit non-scope

| Deferred to | What |
|---|---|
| Phase 3 | Reference trajectory load/save (`.mat` files), measurement-vs-reference overlay in the plot, `STATE:REF_LOADED` PV, the difference panels (`axes_traj_dx`, `axes_traj_dy` in the MATLAB GUI), the 4-subplot "with reference" layout |
| Phase 4 | Arming BPMs (`SCexp_ALS_armBPMs.m` port — CA writes to `wfr:TBT:arm`), triggering injection (the `srinjectoneshot` MML black box), `FirstTurnThreading.m` port, golden-orbit subtraction (requires MML data), pySC integration, response matrix calc |
| Phase 5 | Gaussian fits, dispersion, kick angle, RMS metrics, full MATLAB GUI feature parity (tab structure, all 18 manual steps) |
| Phase 6 | CI pipeline, log shipping, Phoebus screen examples, production deploy automation |
| Out of scope per plan | Auth, BBA, septum scan, LEDA, full automated_startup chain |
| Out of scope for phase 2 specifically | Continuous monitoring / auto-refresh (UI is snapshot-on-demand only); per-BPM CA monitor subscriptions (we use on-demand reads); bulk all-BPM raw waveform endpoint (~144 MB); historical acquisition retention (one snapshot only); pySC anything |

---

## 14. Forward compatibility — what phase 3 looks like on this foundation

Concrete additions phase 3 should require:

- New domain code: `pytxt/domain/reference.py` — load/save `.mat` reference trajectories, compute `B - R0` difference arrays.
- New AppState fields: `reference_trajectory: ReferenceTrajectory | None`, `reference_loaded_at: datetime | None`.
- New PVs in `ioc/pvs.py`: `STATE:REF_LOADED`, `STATE:REF_NAME`, `RESULT:BPM:X_DIFF_FIRST_TURN`, `RESULT:BPM:Y_DIFF_FIRST_TURN`, `CMD:LOAD_REF`, `CMD:SAVE_REF`.
- New REST routes: `POST /api/v1/cmd/load_ref`, `POST /api/v1/cmd/save_ref`, multipart file upload/download.
- New frontend: 4-panel layout switch (X, Y, ΔX, ΔY) when a reference is loaded; reference-vs-measurement overlay within each panel (matches MATLAB GUI lines 180–189).
- New handler: `handlers/reference.py` (load and save).
- Two new parametrize rows added to `test_parity.py`.

**Zero structural changes from phase 2** — every addition lands in a package that already exists. The composition root grows by one or two lines.

---

## 15. Open questions / deferred decisions

- **Whether to expose per-BPM raw waveforms as PVs in addition to REST.** Current decision: REST-only (raw is too large for PV semantics). If a future phase needs CA-native access to raw waveforms (e.g., archiver wants to log first-turn data), revisit.
- **WS message `type` discriminator.** Deferred from phase 1 code review. Currently the WS payload shape is implicit (the presence of certain fields tells the client what kind of message it is). Phase 2 adds more message types implicitly — once phase 3 lands or the client logic gets complex, add an explicit `type` field.
- **Whether `bpm_prefixes` should be re-loadable at runtime** (via a `CMD:RELOAD_BPM_LIST`). Current decision: load once at startup; require a restart to pick up changes. Re-evaluate if BPM topology changes more often than expected.

---

*End of design spec. Implementation plan to follow via `superpowers:writing-plans`.*
