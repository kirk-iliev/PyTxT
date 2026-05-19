# Phase 2 — Read Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the BPM TBT read path — operator clicks `ACQUIRE`, app reads ~120 BPM turn-by-turn waveforms via CA, extracts first-turn positions per the MATLAB injection-turn detection algorithm, publishes results as PVs and renders a stacked X/Y ring trajectory in the browser. Same effect via `caput CMD:ACQUIRE` or `POST /api/v1/cmd/acquire`.

**Architecture:** Read-only CA client (`pytxt/ca_client/bpm_reader.py`) reads upstream BPM PVs into `RawBPM` dataclasses; pure numpy domain code (`pytxt/domain/`) detects injection turn and extracts first-turn positions with NaN sentinels; the shared `handle_acquire` handler updates AppState; IOC mirrors changes outward to new `RESULT:BPM:*` and `STATE:ACQUIRE:*` PVs; REST exposes the same trigger and a bulk-raw-waveform endpoint. Vertical slice approach: M1 builds the full pipeline at N=1; M2 scales to ~120 BPMs; M3 adds failure handling; M4 finishes raw REST endpoint, UI polish, and Playwright e2e.

**Tech Stack:** Python 3.12, FastAPI, caproto (both server and async client), numpy, pydantic, pydantic-settings, pytest + pytest-asyncio, Playwright (e2e), vanilla JS + Canvas (frontend).

**Source spec:** `docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md` (read first).

**Decision log to maintain during implementation:** `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` — append entries for spec-gaps, deviations, and tradeoffs.

**File map (all paths absolute from repo root):**

- Create: `pytxt/domain/types.py` (`RawBPM`, `FirstTurnResult` dataclasses)
- Create: `pytxt/domain/injection_turn.py` (`detect_injection_turn`)
- Create: `pytxt/domain/first_turn_extract.py` (`extract_first_turn`)
- Create: `pytxt/ca_client/bpm_reader.py` (`BpmReader` class)
- Create: `pytxt/handlers/acquire.py` (`handle_acquire`, `AcquisitionInFlightError`)
- Create: `pytxt/api/routes/result.py` (`GET /api/v1/result/bpm/raw`)
- Create: `pytxt/api/schemas/result.py` (`LastAcquireResult`, `AcquireResponse`, `BpmRawWaveforms`, status enum mapping)
- Create: `pytxt/config/bpm_prefixes.txt` (committed list of ~120 BPM PV prefixes, sourced from MATLAB)
- Create: `pytxt/frontend/trajectory.html`
- Create: `pytxt/frontend/js/trajectory.js`
- Create: `tests/fixtures/fake_bpm_ioc.py` (caproto-based fake BPM IOC fixture)
- Create: `tests/unit/test_domain_types.py`
- Create: `tests/unit/test_injection_turn.py`
- Create: `tests/unit/test_first_turn_extract.py`
- Create: `tests/unit/test_handlers_acquire.py`
- Create: `tests/unit/test_schemas_result.py`
- Create: `tests/integration/test_bpm_reader.py`
- Create: `tests/integration/test_acquire_via_ca.py`
- Create: `tests/integration/test_acquire_via_rest.py`
- Create: `tests/integration/test_result_raw_endpoint.py`
- Create: `tests/e2e/trajectory.spec.js`
- Modify: `pytxt/state/app_state.py` (add 4 new fields)
- Modify: `pytxt/ioc/pvs.py` (add new pvproperties and CMD:ACQUIRE putter)
- Modify: `pytxt/ioc/server.py` (extend `_FIELD_TO_PV_ATTR`, add `_publish_last_acquire` and `_publish_bpm_names` helpers)
- Modify: `pytxt/api/routes/cmd.py` (add `POST /cmd/acquire`)
- Modify: `pytxt/api/schemas/state.py` (extend `StateSnapshot` with new fields)
- Modify: `pytxt/api/server.py` (include result router)
- Modify: `pytxt/api/routes/state.py` (extended state projection)
- Modify: `pytxt/composition.py` (load BPM prefixes, construct BpmReader, register dependency, expose to FastAPI app)
- Modify: `pytxt/config/settings.py` (add `bpm_prefixes_path`, `bpm_read_timeout_s`)
- Modify: `pytxt/frontend/index.html` (add nav link to /trajectory.html)
- Modify: `pytxt/frontend/css/theme.css` (add canvas custom properties)
- Modify: `tests/integration/test_parity.py` (add `acquire` parametrize row)
- Modify: `tests/conftest.py` (register `fake_bpm_ioc` fixture)

---

## Pre-flight

### Task 0: Re-read the spec and decisions log

**Files:** (read-only)
- `docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md`
- `docs/superpowers/specs/2026-05-18-phase-2-decisions.md`
- `CLAUDE.md`

- [ ] **Step 1: Read both spec and decisions log end-to-end.**
- [ ] **Step 2: Note the decision-log convention.** Every non-trivial implementation decision gets an entry appended to `2026-05-18-phase-2-decisions.md` using the template at the top of that file.
- [ ] **Step 3: Confirm git state is clean.**

```bash
git status
```
Expected: working tree clean on `main`.

---

## Pre-flight Task A: Fake BPM IOC fixture

This fixture is used by every integration test in this plan. It serves `wfr:TBT:{c0,c1,c3,armed}` PVs for arbitrary BPM prefixes with deterministic synthesized data (a sum-signal step at sample 1370, X/Y waveforms with low-amplitude noise around realistic values).

### Task A: Build the fake BPM IOC fixture

**Files:**
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/fake_bpm_ioc.py`
- Modify: `tests/conftest.py:67` (append fixture registration)

- [ ] **Step 1: Write the failing test for the fixture's data shape.**

Create `tests/fixtures/__init__.py` as an empty file. Create `tests/integration/test_fake_bpm_ioc.py`:

```python
"""Sanity check: the fake BPM IOC fixture serves the expected PV shape."""
import asyncio
import pytest
import numpy as np
from caproto.asyncio.client import Context as ClientContext


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [["SR01C:BPM1"]], indirect=True)
async def test_fake_bpm_serves_tbt_channels(fake_bpm_ioc):
    """The fixture publishes c0/c1/c3 as length-100000 int32 waveforms and armed as a scalar."""
    client = ClientContext()
    c0, c1, c3, armed = await client.get_pvs(
        "SR01C:BPM1:wfr:TBT:c0",
        "SR01C:BPM1:wfr:TBT:c1",
        "SR01C:BPM1:wfr:TBT:c3",
        "SR01C:BPM1:wfr:TBT:armed",
    )
    r_c0 = await c0.read()
    r_c1 = await c1.read()
    r_c3 = await c3.read()
    r_armed = await armed.read()

    assert len(r_c0.data) == 100000
    assert len(r_c1.data) == 100000
    assert len(r_c3.data) == 100000
    assert r_armed.data[0] == 0  # data ready by default

    # Sum signal should have an injection-turn peak around sample 1370
    sum_wf = np.asarray(r_c3.data)
    peak_idx = int(np.argmax(np.diff(sum_wf)))
    assert 1300 < peak_idx < 1500, f"expected peak ~1370, got {peak_idx}"
```

- [ ] **Step 2: Run test to verify it fails (fixture not defined).**

```bash
pytest tests/integration/test_fake_bpm_ioc.py -v
```
Expected: `ERROR` with `fixture 'fake_bpm_ioc' not found`.

- [ ] **Step 3: Implement the fixture.**

Create `tests/fixtures/fake_bpm_ioc.py`:

```python
"""Caproto-based fake BPM IOC fixture for integration tests.

Spins up N PVGroups in-process (one per BPM prefix) on the conftest-pinned
ephemeral CA port. Each fake BPM publishes:

- {prefix}:wfr:TBT:c0  — X waveform (100000 int32, nm)
- {prefix}:wfr:TBT:c1  — Y waveform (100000 int32, nm)
- {prefix}:wfr:TBT:c3  — sum signal (100000 int32, AU)
- {prefix}:wfr:TBT:armed — scalar uint16 (0 = data ready)

Synthesized data has a sum-signal step at sample 1370 so injection-turn
detection produces deterministic results. X/Y are zero-mean noise with
a small offset (~80 µm) that varies per BPM index. armed is 0 by default;
fault injection via fixture.bpm_offline / fixture.bpm_timeout flips behavior.
"""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np
import pytest
import pytest_asyncio
from caproto import ChannelType
from caproto.asyncio.server import Context
from caproto.server import PVGroup, pvproperty


_SAMPLES = 100000
_INJECTION_SAMPLE = 1370


def _synthesize_waveforms(bpm_index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (x_nm, y_nm, sum_au) for one BPM.

    sum_au has a clear step at sample _INJECTION_SAMPLE so detect_injection_turn
    returns that index deterministically. x_nm and y_nm have a small per-BPM
    DC offset plus low-amplitude noise — realistic order of magnitude.
    """
    rng = np.random.default_rng(seed=42 + bpm_index)
    # Sum signal: low background, step up at injection, decay over ~5000 turns
    sum_au = np.full(_SAMPLES, 1000, dtype=np.int32)
    sum_au[_INJECTION_SAMPLE:] = 200_000
    decay = np.linspace(1.0, 0.5, _SAMPLES - _INJECTION_SAMPLE)
    sum_au[_INJECTION_SAMPLE:] = (sum_au[_INJECTION_SAMPLE:] * decay).astype(np.int32)
    sum_au += rng.integers(-500, 500, size=_SAMPLES, dtype=np.int32)

    # X/Y position waveforms: per-BPM DC offset + noise (in nm)
    x_offset_nm = int(80_000 * np.sin(bpm_index * 0.05))   # ±80 µm across BPMs
    y_offset_nm = int(80_000 * np.cos(bpm_index * 0.05))
    x_nm = np.full(_SAMPLES, x_offset_nm, dtype=np.int32) + \
           rng.integers(-5000, 5000, size=_SAMPLES, dtype=np.int32)
    y_nm = np.full(_SAMPLES, y_offset_nm, dtype=np.int32) + \
           rng.integers(-5000, 5000, size=_SAMPLES, dtype=np.int32)

    return x_nm, y_nm, sum_au


def _make_bpm_group(prefix: str, bpm_index: int) -> PVGroup:
    """Build a PVGroup serving the four TBT PVs for one BPM."""
    x_nm, y_nm, sum_au = _synthesize_waveforms(bpm_index)

    class FakeBPM(PVGroup):
        c0 = pvproperty(
            value=x_nm.tolist(), dtype=int, read_only=True,
            name="wfr:TBT:c0", max_length=_SAMPLES,
        )
        c1 = pvproperty(
            value=y_nm.tolist(), dtype=int, read_only=True,
            name="wfr:TBT:c1", max_length=_SAMPLES,
        )
        c3 = pvproperty(
            value=sum_au.tolist(), dtype=int, read_only=True,
            name="wfr:TBT:c3", max_length=_SAMPLES,
        )
        armed = pvproperty(
            value=0, dtype=int, read_only=True,
            name="wfr:TBT:armed",
        )

    # The prefix in caproto's PVGroup gets prepended to each pvproperty name.
    # We want SR01C:BPM1:wfr:TBT:c0, so prefix = "SR01C:BPM1:"
    return FakeBPM(prefix=prefix + ":" if not prefix.endswith(":") else prefix)


@dataclass
class FakeBpmIoc:
    """Handle returned from the fixture. Holds the running context and the
    list of BPM prefixes it's serving. Use for fault injection in M3 tasks."""
    prefixes: list[str]
    _context: Context
    _task: asyncio.Task


@pytest_asyncio.fixture
async def fake_bpm_ioc(request) -> FakeBpmIoc:
    """Parametrize via @pytest.mark.parametrize('fake_bpm_ioc', [N_or_list], indirect=True).

    If param is an int N, generates prefixes ["FAKE:BPM1", "FAKE:BPM2", ...].
    If param is a list[str], uses those exact prefixes.
    """
    param = request.param if hasattr(request, "param") else 1
    if isinstance(param, int):
        prefixes = [f"FAKE:BPM{i+1}" for i in range(param)]
    else:
        prefixes = list(param)

    # Build all PVGroups and merge their pvdbs
    groups = [_make_bpm_group(p, i) for i, p in enumerate(prefixes)]
    pvdb: dict = {}
    for g in groups:
        pvdb.update(g.pvdb)

    ctx = Context(pvdb)
    task = asyncio.create_task(ctx.run(log_pv_names=False))
    # Give caproto a moment to bind sockets
    await asyncio.sleep(0.2)

    handle = FakeBpmIoc(prefixes=prefixes, _context=ctx, _task=task)
    try:
        yield handle
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
```

- [ ] **Step 4: Register the fixture in conftest.**

Append to `tests/conftest.py`:

```python
# Import phase-2 fixtures so tests can use them without explicit imports.
from tests.fixtures.fake_bpm_ioc import fake_bpm_ioc  # noqa: F401
```

- [ ] **Step 5: Run test to verify it passes.**

```bash
pytest tests/integration/test_fake_bpm_ioc.py -v
```
Expected: 1 passed.

- [ ] **Step 6: Commit.**

```bash
git add tests/fixtures/__init__.py tests/fixtures/fake_bpm_ioc.py \
        tests/conftest.py tests/integration/test_fake_bpm_ioc.py
git commit -m "test(fixtures): fake BPM IOC fixture serving wfr:TBT:* waveforms"
```

---

## Milestone 1 — Vertical slice, 1 real BPM

Build the full pipeline (ca_client → domain → handler → IOC → REST → frontend) wired end-to-end with `bpm_prefixes = ["SR01C:BPM1"]` hardcoded. By the end of M1, clicking ACQUIRE in the browser fetches real BPM data and renders one datapoint per axis.

### Task M1-1: Pydantic schemas for results

**Files:**
- Create: `pytxt/api/schemas/result.py`
- Create: `tests/unit/test_schemas_result.py`

- [ ] **Step 1: Write failing tests for schema shape.**

Create `tests/unit/test_schemas_result.py`:

```python
"""Phase-2 result schemas: round-trip, required fields, enum mapping."""
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from pytxt.api.schemas.result import (
    AcquireStatus,
    LastAcquireResult,
    AcquireResponse,
    BpmRawWaveforms,
    STATUS_INT_TO_STR,
    STATUS_STR_TO_INT,
)


def test_acquire_status_int_string_mapping_is_bijective():
    assert STATUS_INT_TO_STR == {0: "NEVER", 1: "ACQUIRING", 2: "OK", 3: "PARTIAL", 4: "FAILED"}
    for i, s in STATUS_INT_TO_STR.items():
        assert STATUS_STR_TO_INT[s] == i


def test_last_acquire_result_round_trip():
    r = LastAcquireResult(
        status=AcquireStatus.OK,
        ok_count=120,
        fail_count=0,
        failed_bpm_names=[],
        injection_turn_median=1370,
        timestamp=datetime.now(timezone.utc),
    )
    js = r.model_dump_json()
    r2 = LastAcquireResult.model_validate_json(js)
    assert r2.status == "OK"
    assert r2.ok_count == 120


def test_acquire_response_required_fields():
    with pytest.raises(ValidationError):
        AcquireResponse()  # missing required


def test_bpm_raw_waveforms_shape():
    raw = BpmRawWaveforms(
        bpm_prefix="SR01C:BPM1",
        x_nm=[0, 1, 2],
        y_nm=[0, 1, 2],
        sum_au=[100, 200, 300],
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )
    assert raw.bpm_prefix == "SR01C:BPM1"
    assert len(raw.x_nm) == 3
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/unit/test_schemas_result.py -v
```
Expected: `ImportError` / fail.

- [ ] **Step 3: Implement the schemas.**

Create `pytxt/api/schemas/result.py`:

```python
"""Phase-2 REST schemas for BPM acquisition results.

The status enum has both a string form (REST/JSON-friendly) and an int form
(EPICS-friendly). The two mappings here are the single source of truth.
"""
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AcquireStatus(StrEnum):
    NEVER = "NEVER"
    ACQUIRING = "ACQUIRING"
    OK = "OK"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


# Canonical int↔string mapping (same in IOC enum PV and REST JSON).
STATUS_INT_TO_STR: dict[int, str] = {
    0: "NEVER",
    1: "ACQUIRING",
    2: "OK",
    3: "PARTIAL",
    4: "FAILED",
}
STATUS_STR_TO_INT: dict[str, int] = {v: k for k, v in STATUS_INT_TO_STR.items()}


class LastAcquireResult(BaseModel):
    """Outcome of the most recent ACQUIRE. Stored in AppState.last_acquire
    and mirrored to STATE:LAST_ACQUIRE_* PVs."""
    status: AcquireStatus = Field(description="Lifecycle status")
    ok_count: int = Field(description="BPMs that returned valid data")
    fail_count: int = Field(description="BPMs that timed out / returned invalid data")
    failed_bpm_names: list[str] = Field(default_factory=list)
    injection_turn_median: int = Field(
        description="Median per-BPM detected injection turn; -1 if all failed"
    )
    timestamp: datetime | None = Field(default=None)
    fail_reason: str = Field(default="", description="Short error when status=FAILED")


class AcquireResponse(BaseModel):
    """Response body for POST /api/v1/cmd/acquire."""
    status: Literal["OK", "PARTIAL", "FAILED"]
    ok_count: int
    fail_count: int
    failed_bpm_names: list[str]
    injection_turn_median: int
    timestamp: datetime


class BpmRawWaveforms(BaseModel):
    """Response body for GET /api/v1/result/bpm/raw?bpm=<prefix>."""
    bpm_prefix: str
    x_nm: list[int]   # 100000 samples, raw nm (no mm conversion)
    y_nm: list[int]
    sum_au: list[int]
    armed: int        # 0 = data was valid at read time
    read_timestamp: datetime
```

- [ ] **Step 4: Run test to verify it passes.**

```bash
pytest tests/unit/test_schemas_result.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit.**

```bash
git add pytxt/api/schemas/result.py tests/unit/test_schemas_result.py
git commit -m "feat(api): phase-2 result schemas (LastAcquireResult, AcquireResponse, BpmRawWaveforms)"
```

---

### Task M1-2: Domain types — RawBPM and FirstTurnResult

**Files:**
- Create: `pytxt/domain/types.py`
- Create: `tests/unit/test_domain_types.py`

- [ ] **Step 1: Write the failing test.**

Create `tests/unit/test_domain_types.py`:

```python
"""Domain dataclasses: frozen, type-correct, no I/O imports."""
from datetime import datetime, timezone
import numpy as np
import pytest

from pytxt.domain.types import RawBPM, FirstTurnResult


def test_raw_bpm_is_frozen():
    raw = RawBPM(
        prefix="SR01C:BPM1",
        x_wf=np.zeros(100000, dtype=np.int32),
        y_wf=np.zeros(100000, dtype=np.int32),
        sum_wf=np.zeros(100000, dtype=np.int32),
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )
    with pytest.raises((TypeError, AttributeError)):
        raw.prefix = "other"   # frozen


def test_first_turn_result_shape():
    n = 5
    r = FirstTurnResult(
        x_first_turn=np.full(n, np.nan),
        y_first_turn=np.full(n, np.nan),
        sum_first_turn=np.full(n, np.nan),
        injection_turn=np.full(n, -1, dtype=np.int32),
        failed_bpm_names=["A", "B"],
    )
    assert r.x_first_turn.shape == (n,)
    assert r.injection_turn.dtype == np.int32


def test_domain_imports_no_io():
    """domain/ must not import caproto, fastapi, or asyncio anywhere."""
    import pytxt.domain.types as m
    src = open(m.__file__).read()
    assert "caproto" not in src
    assert "fastapi" not in src
    assert "import asyncio" not in src
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pytest tests/unit/test_domain_types.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement.**

Create `pytxt/domain/types.py`:

```python
"""Pure-numpy dataclasses shared by ca_client/, handlers/, and IOC publish.

NO I/O imports here (no caproto, no FastAPI, no asyncio). Adapters that
construct these types live above the domain package.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class RawBPM:
    """Single BPM's TBT capture as read from CA. dtype/shape correspond to
    what caproto returns from {prefix}:wfr:TBT:{c0,c1,c3,armed}."""
    prefix: str
    x_wf: np.ndarray         # shape (100000,), dtype int32, units nm
    y_wf: np.ndarray
    sum_wf: np.ndarray
    armed: int               # 0 = data was valid at read time
    read_timestamp: datetime


@dataclass(frozen=True)
class FirstTurnResult:
    """Extracted per-BPM first-turn positions, aligned with the BPM list order.
    NaN/-1 sentinels mark BPMs that failed during the acquisition."""
    x_first_turn: np.ndarray         # (n_bpms,) float64, mm, NaN for failed
    y_first_turn: np.ndarray
    sum_first_turn: np.ndarray
    injection_turn: np.ndarray       # (n_bpms,) int32, -1 for failed
    failed_bpm_names: list[str]
```

- [ ] **Step 4: Run test to verify it passes.**

```bash
pytest tests/unit/test_domain_types.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit.**

```bash
git add pytxt/domain/types.py tests/unit/test_domain_types.py
git commit -m "feat(domain): RawBPM and FirstTurnResult dataclasses"
```

---

### Task M1-3: Domain — injection turn detection

**Files:**
- Create: `pytxt/domain/injection_turn.py`
- Create: `tests/unit/test_injection_turn.py`

- [ ] **Step 1: Write failing tests for all branches of the algorithm.**

Create `tests/unit/test_injection_turn.py`:

```python
"""Port of MATLAB SCexp_ALS_readoutBPMs.m injection-turn detection.

argmax(diff(sum)) with fallback to 1370 when result is outside [100, 4500].
"""
import numpy as np
import pytest

from pytxt.domain.injection_turn import detect_injection_turn


def _waveform_with_step(at: int, n: int = 100000) -> np.ndarray:
    """Build a sum-signal waveform with a step up at sample `at`."""
    wf = np.full(n, 1000, dtype=np.int32)
    wf[at:] = 200000
    return wf


def test_detects_clear_peak_in_valid_range():
    wf = _waveform_with_step(at=1370)
    assert detect_injection_turn(wf) == 1370


def test_detects_clear_peak_at_lower_edge():
    wf = _waveform_with_step(at=100)
    assert detect_injection_turn(wf) == 100


def test_detects_clear_peak_at_upper_edge():
    wf = _waveform_with_step(at=4500)
    assert detect_injection_turn(wf) == 4500


def test_falls_back_to_1370_when_peak_below_100():
    wf = _waveform_with_step(at=50)
    assert detect_injection_turn(wf) == 1370


def test_falls_back_to_1370_when_peak_above_4500():
    wf = _waveform_with_step(at=5000)
    assert detect_injection_turn(wf) == 1370


def test_flat_waveform_falls_back_to_1370():
    """No clear peak — argmax(diff) lands at sample 0, outside [100,4500]."""
    wf = np.full(100000, 1000, dtype=np.int32)
    assert detect_injection_turn(wf) == 1370
```

- [ ] **Step 2: Run to verify it fails.**

```bash
pytest tests/unit/test_injection_turn.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement.**

Create `pytxt/domain/injection_turn.py`:

```python
"""Per-BPM injection-turn detection.

Port of MATLAB SCexp_ALS_readoutBPMs.m:

    [~,injind] = max(diff(sum'));
    if any(injind<100) || any(injind>4500)
        injind(loop) = 1370;     % per-BPM fallback
    end

The comment in the MATLAB source notes that BPMs may be offset from
each other by a few turns — that's why detection is per-BPM, not global.
"""
from __future__ import annotations

import numpy as np


_VALID_MIN = 100
_VALID_MAX = 4500
_FALLBACK_INDEX = 1370


def detect_injection_turn(sum_waveform: np.ndarray) -> int:
    """Return the sample index of the injection turn.

    Algorithm: argmax of the first difference of the sum signal. If the
    result falls outside [100, 4500], fall back to the documented default
    of 1370 (matches MATLAB).
    """
    idx = int(np.argmax(np.diff(sum_waveform)))
    if idx < _VALID_MIN or idx > _VALID_MAX:
        return _FALLBACK_INDEX
    return idx
```

- [ ] **Step 4: Run to verify all pass.**

```bash
pytest tests/unit/test_injection_turn.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit.**

```bash
git add pytxt/domain/injection_turn.py tests/unit/test_injection_turn.py
git commit -m "feat(domain): injection-turn detection (port of MATLAB)"
```

---

### Task M1-4: Domain — first-turn extraction with NaN sentinels

**Files:**
- Create: `pytxt/domain/first_turn_extract.py`
- Create: `tests/unit/test_first_turn_extract.py`

- [ ] **Step 1: Write failing tests.**

Create `tests/unit/test_first_turn_extract.py`:

```python
"""extract_first_turn: convert raw BPM dict → FirstTurnResult with NaN sentinels."""
from datetime import datetime, timezone
import numpy as np

from pytxt.domain.first_turn_extract import extract_first_turn
from pytxt.domain.types import RawBPM


def _raw_with_offset(prefix: str, x_offset_nm: int, y_offset_nm: int, peak_at: int = 1370):
    sum_wf = np.full(100000, 1000, dtype=np.int32)
    sum_wf[peak_at:] = 200000
    return RawBPM(
        prefix=prefix,
        x_wf=np.full(100000, x_offset_nm, dtype=np.int32),
        y_wf=np.full(100000, y_offset_nm, dtype=np.int32),
        sum_wf=sum_wf,
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )


def test_all_valid_bpms_extracted():
    raws = {
        "A": _raw_with_offset("A", 80_000, 0),   # 0.08 mm X
        "B": _raw_with_offset("B", 0, -50_000),  # -0.05 mm Y
    }
    r = extract_first_turn(raws)
    np.testing.assert_allclose(r.x_first_turn, [0.08, 0.0])
    np.testing.assert_allclose(r.y_first_turn, [0.0, -0.05])
    assert list(r.injection_turn) == [1370, 1370]
    assert r.failed_bpm_names == []


def test_none_entries_become_nan_with_failed_names():
    raws = {
        "A": _raw_with_offset("A", 80_000, 0),
        "B": None,
        "C": _raw_with_offset("C", 0, 0),
    }
    r = extract_first_turn(raws)
    assert np.isnan(r.x_first_turn[1])
    assert np.isnan(r.y_first_turn[1])
    assert r.injection_turn[1] == -1
    assert r.failed_bpm_names == ["B"]
    assert not np.isnan(r.x_first_turn[0])
    assert not np.isnan(r.x_first_turn[2])


def test_all_none_all_nan_all_failed():
    raws = {"X": None, "Y": None, "Z": None}
    r = extract_first_turn(raws)
    assert np.all(np.isnan(r.x_first_turn))
    assert np.all(r.injection_turn == -1)
    assert r.failed_bpm_names == ["X", "Y", "Z"]


def test_bpm_index_alignment_preserved():
    """Dict-insertion order defines BPM index. Don't reorder."""
    raws = {"Z": _raw_with_offset("Z", 1_000_000, 0), "A": _raw_with_offset("A", 0, 0)}
    r = extract_first_turn(raws)
    # Index 0 is "Z" (first inserted)
    np.testing.assert_allclose(r.x_first_turn[0], 1.0)
    np.testing.assert_allclose(r.x_first_turn[1], 0.0)
```

- [ ] **Step 2: Run to verify failing.**

```bash
pytest tests/unit/test_first_turn_extract.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement.**

Create `pytxt/domain/first_turn_extract.py`:

```python
"""Extract per-BPM first-turn position arrays from a dict of raw waveforms.

Failed BPMs (raws[prefix] is None) produce NaN/-1 sentinels and are added
to failed_bpm_names. Dict-insertion order defines BPM index; preserve it.

nm → mm conversion: divide by 1e6, matching MATLAB SCexp_ALS_readoutBPMs.m.
"""
from __future__ import annotations

import numpy as np

from pytxt.domain.injection_turn import detect_injection_turn
from pytxt.domain.types import FirstTurnResult, RawBPM


def extract_first_turn(raws: dict[str, RawBPM | None]) -> FirstTurnResult:
    n = len(raws)
    x = np.full(n, np.nan, dtype=np.float64)
    y = np.full(n, np.nan, dtype=np.float64)
    sum_val = np.full(n, np.nan, dtype=np.float64)
    injection_turn = np.full(n, -1, dtype=np.int32)
    failed: list[str] = []

    for i, (prefix, raw) in enumerate(raws.items()):
        if raw is None:
            failed.append(prefix)
            continue
        idx = detect_injection_turn(raw.sum_wf)
        injection_turn[i] = idx
        x[i] = float(raw.x_wf[idx]) / 1e6
        y[i] = float(raw.y_wf[idx]) / 1e6
        sum_val[i] = float(raw.sum_wf[idx])

    return FirstTurnResult(
        x_first_turn=x,
        y_first_turn=y,
        sum_first_turn=sum_val,
        injection_turn=injection_turn,
        failed_bpm_names=failed,
    )
```

- [ ] **Step 4: Run to verify pass.**

```bash
pytest tests/unit/test_first_turn_extract.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit.**

```bash
git add pytxt/domain/first_turn_extract.py tests/unit/test_first_turn_extract.py
git commit -m "feat(domain): first-turn extraction with NaN sentinels"
```

---

### Task M1-5: Extend AppState with phase-2 fields

**Files:**
- Modify: `pytxt/state/app_state.py`
- Modify: `tests/unit/test_app_state.py` (add tests for new fields)

- [ ] **Step 1: Read current AppState (already in your context). Append failing tests.**

Append to `tests/unit/test_app_state.py`:

```python
import asyncio
import numpy as np

from pytxt.api.schemas.result import AcquireStatus, LastAcquireResult


def test_app_state_has_phase_2_fields():
    """AppState defaults populate the four new phase-2 fields."""
    from pytxt.state.app_state import AppState
    s = AppState()
    assert s.bpm_prefixes == []
    assert s.acquire_in_flight is False
    assert s.last_acquire is not None
    assert s.last_acquire.status == "NEVER"
    assert s.last_acquire_raws == {}


def test_acquire_in_flight_is_listener_observable():
    """Listeners fire on acquire_in_flight changes."""
    from pytxt.state.app_state import AppState
    s = AppState()
    captured = []

    async def cb(v):
        captured.append(v)

    s.subscribe("acquire_in_flight", cb)

    async def run():
        await s.update(acquire_in_flight=True)
        await s.update(acquire_in_flight=False)

    asyncio.run(run())
    assert captured == [True, False]
```

- [ ] **Step 2: Run to verify failing.**

```bash
pytest tests/unit/test_app_state.py -v -k "phase_2 or acquire_in_flight"
```
Expected: `AttributeError` on `bpm_prefixes`.

- [ ] **Step 3: Implement.**

Modify `pytxt/state/app_state.py`. Replace the imports block and the dataclass body:

```python
"""AppState — single in-process source of truth.

A typed dataclass plus async change-notification. Subsystems (the IOC,
REST routes, the WS bridge, future CA client) read AppState as needed
and mutate it via `update()`. Listeners registered via `subscribe()`
are invoked on change.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from pytxt.api.schemas.result import AcquireStatus, LastAcquireResult

logger = logging.getLogger(__name__)

ListenerFn = Callable[[Any], Awaitable[None]]


def _initial_last_acquire() -> LastAcquireResult:
    return LastAcquireResult(
        status=AcquireStatus.NEVER,
        ok_count=0,
        fail_count=0,
        failed_bpm_names=[],
        injection_turn_median=-1,
        timestamp=None,
    )


@dataclass
class AppState:
    # === Phase 1 published fields ===
    heartbeat: int = 0
    last_ping_at: Optional[str] = None
    ping_count: int = 0
    version: str = ""
    started_at: float = 0.0
    uptime_s_pushed: float = 0.0

    # === Phase 2 published fields ===
    bpm_prefixes: list[str] = field(default_factory=list)
    acquire_in_flight: bool = False
    last_acquire: LastAcquireResult = field(default_factory=_initial_last_acquire)
    # In-memory only: raw waveforms from the most recent acquisition,
    # served by GET /api/v1/result/bpm/raw. Not mirrored to PVs.
    last_acquire_raws: dict = field(default_factory=dict)

    # Internal: per-field listener lists (excluded from repr/init)
    _listeners: dict[str, list[ListenerFn]] = field(
        default_factory=dict, init=False, repr=False
    )

    @property
    def uptime_s(self) -> float:
        return time.time() - self.started_at if self.started_at else 0.0

    def subscribe(self, field_name: str, callback: ListenerFn) -> None:
        self._listeners.setdefault(field_name, []).append(callback)

    async def update(self, **changes: Any) -> None:
        for k, v in changes.items():
            if k.startswith("_") or not hasattr(self, k) or callable(getattr(type(self), k, None)):
                raise AttributeError(f"AppState has no settable field {k!r}")
            old = getattr(self, k)
            if old == v:
                continue
            setattr(self, k, v)
            for cb in self._listeners.get(k, []):
                try:
                    await cb(v)
                except Exception:
                    logger.exception(
                        "AppState listener for field %r failed; "
                        "other listeners still fired",
                        k,
                    )
```

- [ ] **Step 4: Run to verify pass + all phase-1 AppState tests still pass.**

```bash
pytest tests/unit/test_app_state.py -v
```
Expected: all pass (existing phase-1 tests + 2 new phase-2 tests).

- [ ] **Step 5: Commit.**

```bash
git add pytxt/state/app_state.py tests/unit/test_app_state.py
git commit -m "feat(state): extend AppState with bpm_prefixes, acquire_in_flight, last_acquire, last_acquire_raws"
```

---

### Task M1-6: CA client — BpmReader

**Files:**
- Create: `pytxt/ca_client/bpm_reader.py`
- Create: `tests/integration/test_bpm_reader.py`

- [ ] **Step 1: Write failing tests against the fake BPM IOC fixture.**

Create `tests/integration/test_bpm_reader.py`:

```python
"""Integration: BpmReader reads upstream BPM TBT PVs in parallel.

Uses the fake_bpm_ioc fixture, so the test is fully self-contained.
"""
import numpy as np
import pytest

from pytxt.ca_client.bpm_reader import BpmReader
from pytxt.domain.types import RawBPM


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [["FAKE:BPM1"]], indirect=True)
async def test_read_one_bpm_returns_raw_bpm(fake_bpm_ioc):
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=3.0)
    await reader.start()
    try:
        result = await reader.read_all()
    finally:
        await reader.stop()

    assert set(result.keys()) == {"FAKE:BPM1"}
    raw = result["FAKE:BPM1"]
    assert raw is not None
    assert isinstance(raw, RawBPM)
    assert raw.prefix == "FAKE:BPM1"
    assert raw.x_wf.shape == (100000,)
    assert raw.y_wf.shape == (100000,)
    assert raw.sum_wf.shape == (100000,)
    assert raw.armed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [5], indirect=True)
async def test_read_multiple_bpms_returns_aligned_dict(fake_bpm_ioc):
    """All five BPMs return RawBPM; dict ordering matches input prefixes order."""
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=3.0)
    await reader.start()
    try:
        result = await reader.read_all()
    finally:
        await reader.stop()

    assert list(result.keys()) == fake_bpm_ioc.prefixes
    for prefix in fake_bpm_ioc.prefixes:
        assert result[prefix] is not None, f"{prefix} returned None"
        assert result[prefix].prefix == prefix


@pytest.mark.asyncio
async def test_read_unreachable_bpm_returns_none(test_pv_prefix):
    """A nonexistent BPM prefix returns None in the result dict (not an exception)."""
    reader = BpmReader(prefixes=["NONEXISTENT:BPM"], per_pv_timeout_s=1.0)
    await reader.start()
    try:
        result = await reader.read_all()
    finally:
        await reader.stop()
    assert result == {"NONEXISTENT:BPM": None}
```

- [ ] **Step 2: Run to verify failing.**

```bash
pytest tests/integration/test_bpm_reader.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement.**

Create `pytxt/ca_client/bpm_reader.py`:

```python
"""Persistent-connection CA client for reading BPM TBT waveforms.

Holds caproto async PV objects for every configured BPM's four channels
({prefix}:wfr:TBT:{c0,c1,c3,armed}). On ACQUIRE, dispatches all reads in
parallel via asyncio.gather with a per-PV timeout. Missing or
malformed responses produce None in the result dict (the caller — typically
the acquire handler — turns these into NaN sentinels via the domain layer).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from caproto.asyncio.client import Context as ClientContext

from pytxt.domain.types import RawBPM

logger = logging.getLogger(__name__)

_CHANNELS = ("c0", "c1", "c3", "armed")


class BpmReader:
    """Persistent CA client. Open at startup; read_all() on each ACQUIRE."""

    def __init__(self, prefixes: list[str], per_pv_timeout_s: float = 2.0):
        self._prefixes = list(prefixes)
        self._timeout = per_pv_timeout_s
        self._ctx: Optional[ClientContext] = None
        # prefix → dict of {"c0": PV, "c1": PV, "c3": PV, "armed": PV}
        self._pvs: dict[str, dict[str, object]] = {}

    async def start(self) -> None:
        """Open caproto Context and fetch PV objects for all configured BPMs.

        Does NOT block on the first read — caproto resolves PV names lazily.
        We just create the PV objects; read failures show up at read_all time.
        """
        self._ctx = ClientContext()
        all_names: list[str] = []
        for prefix in self._prefixes:
            for ch in _CHANNELS:
                all_names.append(f"{prefix}:wfr:TBT:{ch}")
        pvs = await self._ctx.get_pvs(*all_names, timeout=self._timeout)
        # Re-shape flat list back into per-BPM channel dict
        for i, prefix in enumerate(self._prefixes):
            base = i * len(_CHANNELS)
            self._pvs[prefix] = {ch: pvs[base + j] for j, ch in enumerate(_CHANNELS)}

    async def stop(self) -> None:
        """Close the caproto Context. Idempotent."""
        if self._ctx is not None:
            try:
                await self._ctx.disconnect()
            except Exception:
                logger.exception("BpmReader.stop: error closing caproto context")
            self._ctx = None
            self._pvs = {}

    async def read_all(self) -> dict[str, RawBPM | None]:
        """Read every configured BPM in parallel; return aligned dict."""
        if self._ctx is None:
            raise RuntimeError("BpmReader.read_all() called before start()")

        async def _read_one(prefix: str) -> tuple[str, RawBPM | None]:
            channels = self._pvs.get(prefix)
            if channels is None:
                return prefix, None
            try:
                c0_r, c1_r, c3_r, armed_r = await asyncio.gather(
                    asyncio.wait_for(channels["c0"].read(), timeout=self._timeout),
                    asyncio.wait_for(channels["c1"].read(), timeout=self._timeout),
                    asyncio.wait_for(channels["c3"].read(), timeout=self._timeout),
                    asyncio.wait_for(channels["armed"].read(), timeout=self._timeout),
                )
            except Exception as exc:
                logger.debug("BPM %s read failed: %s: %s", prefix, type(exc).__name__, exc)
                return prefix, None

            try:
                x_wf = np.asarray(c0_r.data, dtype=np.int32)
                y_wf = np.asarray(c1_r.data, dtype=np.int32)
                sum_wf = np.asarray(c3_r.data, dtype=np.int32)
                armed = int(armed_r.data[0])
            except Exception:
                logger.exception("BPM %s data conversion failed", prefix)
                return prefix, None

            if x_wf.shape != (100000,) or y_wf.shape != (100000,) or sum_wf.shape != (100000,):
                logger.warning(
                    "BPM %s wrong waveform shape: x=%s y=%s sum=%s",
                    prefix, x_wf.shape, y_wf.shape, sum_wf.shape,
                )
                return prefix, None

            return prefix, RawBPM(
                prefix=prefix,
                x_wf=x_wf,
                y_wf=y_wf,
                sum_wf=sum_wf,
                armed=armed,
                read_timestamp=datetime.now(timezone.utc),
            )

        pairs = await asyncio.gather(*(_read_one(p) for p in self._prefixes))
        # Preserve prefix order
        return {p: r for p, r in pairs}
```

- [ ] **Step 4: Run to verify pass.**

```bash
pytest tests/integration/test_bpm_reader.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit.**

```bash
git add pytxt/ca_client/bpm_reader.py tests/integration/test_bpm_reader.py
git commit -m "feat(ca_client): BpmReader with persistent connections and parallel reads"
```

---

### Task M1-7: Acquire handler

**Files:**
- Create: `pytxt/handlers/acquire.py`
- Create: `tests/unit/test_handlers_acquire.py`

- [ ] **Step 1: Write failing tests with a mocked reader.**

Create `tests/unit/test_handlers_acquire.py`:

```python
"""Unit tests for handle_acquire with a mocked reader."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import numpy as np
import pytest

from pytxt.api.schemas.result import AcquireStatus
from pytxt.domain.types import RawBPM
from pytxt.handlers.acquire import AcquisitionInFlightError, handle_acquire
from pytxt.state.app_state import AppState


def _fake_raw(prefix: str):
    sum_wf = np.full(100000, 1000, dtype=np.int32)
    sum_wf[1370:] = 200000
    return RawBPM(
        prefix=prefix,
        x_wf=np.full(100000, 80_000, dtype=np.int32),
        y_wf=np.zeros(100000, dtype=np.int32),
        sum_wf=sum_wf,
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_happy_path_updates_state_and_returns_response():
    state = AppState(bpm_prefixes=["A", "B"])
    reader = AsyncMock()
    reader.read_all.return_value = {"A": _fake_raw("A"), "B": _fake_raw("B")}

    response = await handle_acquire(state, reader)

    assert response.status == "OK"
    assert response.ok_count == 2
    assert response.fail_count == 0
    assert state.acquire_in_flight is False
    assert state.last_acquire.status == "OK"
    assert state.last_acquire_raws["A"].prefix == "A"


@pytest.mark.asyncio
async def test_in_flight_collision_raises():
    state = AppState(bpm_prefixes=["A"], acquire_in_flight=True)
    reader = AsyncMock()

    with pytest.raises(AcquisitionInFlightError):
        await handle_acquire(state, reader)


@pytest.mark.asyncio
async def test_all_fail_status_failed():
    state = AppState(bpm_prefixes=["A", "B"])
    reader = AsyncMock()
    reader.read_all.return_value = {"A": None, "B": None}

    response = await handle_acquire(state, reader)

    assert response.status == "FAILED"
    assert response.ok_count == 0
    assert response.fail_count == 2
    assert state.last_acquire.status == "FAILED"


@pytest.mark.asyncio
async def test_partial_fail_status_partial():
    state = AppState(bpm_prefixes=["A", "B"])
    reader = AsyncMock()
    reader.read_all.return_value = {"A": _fake_raw("A"), "B": None}

    response = await handle_acquire(state, reader)

    assert response.status == "PARTIAL"
    assert response.ok_count == 1
    assert response.fail_count == 1
    assert response.failed_bpm_names == ["B"]


@pytest.mark.asyncio
async def test_exception_clears_in_flight():
    state = AppState(bpm_prefixes=["A"])
    reader = AsyncMock()
    reader.read_all.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await handle_acquire(state, reader)

    assert state.acquire_in_flight is False
    assert state.last_acquire.status == "FAILED"
```

- [ ] **Step 2: Run to verify failing.**

```bash
pytest tests/unit/test_handlers_acquire.py -v
```
Expected: `ImportError`.

- [ ] **Step 3: Implement.**

Create `pytxt/handlers/acquire.py`:

```python
"""Canonical handler for the ACQUIRE command.

Same function whether called by the IOC's CMD:ACQUIRE putter or the REST
POST route — agentic parity by construction. Concurrent attempts raise
AcquisitionInFlightError, surfaced as a CA alarm or HTTP 409 by callers.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

import numpy as np

from pytxt.api.schemas.result import (
    AcquireResponse,
    AcquireStatus,
    LastAcquireResult,
)
from pytxt.domain.first_turn_extract import extract_first_turn
from pytxt.domain.types import RawBPM
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)


class AcquisitionInFlightError(RuntimeError):
    """Raised when ACQUIRE is triggered while one is already in progress."""


class _ReaderProtocol(Protocol):
    async def read_all(self) -> dict[str, RawBPM | None]: ...


def _classify(ok: int, fail: int) -> AcquireStatus:
    if ok == 0:
        return AcquireStatus.FAILED
    if fail > 0:
        return AcquireStatus.PARTIAL
    return AcquireStatus.OK


def _median_injection_turn(injection_turn: np.ndarray) -> int:
    valid = injection_turn[injection_turn >= 0]
    if valid.size == 0:
        return -1
    return int(np.median(valid))


async def handle_acquire(state: AppState, reader: _ReaderProtocol) -> AcquireResponse:
    """Orchestrate one acquisition.

    Sequence: check in-flight → set in-flight → read all BPMs in parallel
    → extract first-turn positions → publish via AppState update → return
    AcquireResponse. The in-flight flag is always cleared (try/finally).
    """
    if state.acquire_in_flight:
        raise AcquisitionInFlightError("ACQUIRE already in progress")

    try:
        await state.update(
            acquire_in_flight=True,
            last_acquire=LastAcquireResult(
                status=AcquireStatus.ACQUIRING,
                ok_count=0,
                fail_count=0,
                failed_bpm_names=[],
                injection_turn_median=-1,
                timestamp=None,
            ),
        )

        raws = await reader.read_all()
        first_turn = extract_first_turn(raws)

        ok_count = len(raws) - len(first_turn.failed_bpm_names)
        fail_count = len(first_turn.failed_bpm_names)
        status = _classify(ok_count, fail_count)
        median_turn = _median_injection_turn(first_turn.injection_turn)
        now = datetime.now(timezone.utc)

        last = LastAcquireResult(
            status=status,
            ok_count=ok_count,
            fail_count=fail_count,
            failed_bpm_names=first_turn.failed_bpm_names,
            injection_turn_median=median_turn,
            timestamp=now,
        )

        # Strip None entries from raws so /result/bpm/raw can simply look up by prefix.
        successful_raws = {p: r for p, r in raws.items() if r is not None}

        await state.update(
            last_acquire=last,
            last_acquire_raws=successful_raws,
        )

        return AcquireResponse(
            status=status.value,
            ok_count=ok_count,
            fail_count=fail_count,
            failed_bpm_names=first_turn.failed_bpm_names,
            injection_turn_median=median_turn,
            timestamp=now,
        )

    except AcquisitionInFlightError:
        raise
    except Exception as exc:
        logger.exception("handle_acquire: unexpected error")
        await state.update(
            last_acquire=LastAcquireResult(
                status=AcquireStatus.FAILED,
                ok_count=0,
                fail_count=len(state.bpm_prefixes),
                failed_bpm_names=list(state.bpm_prefixes),
                injection_turn_median=-1,
                timestamp=datetime.now(timezone.utc),
                fail_reason=f"{type(exc).__name__}: {exc}",
            ),
        )
        raise
    finally:
        await state.update(acquire_in_flight=False)
```

- [ ] **Step 4: Run to verify pass.**

```bash
pytest tests/unit/test_handlers_acquire.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit.**

```bash
git add pytxt/handlers/acquire.py tests/unit/test_handlers_acquire.py
git commit -m "feat(handlers): handle_acquire with in-flight guard and try/finally"
```

---

### Task M1-8: Add phase-2 PVs to the IOC

**Files:**
- Modify: `pytxt/ioc/pvs.py`

- [ ] **Step 1: Modify `pytxt/ioc/pvs.py` to add the new pvproperties and the CMD:ACQUIRE putter.**

The handler needs access to a `BpmReader` instance; the PVGroup constructor accepts it. We use a fixed `max_length=128` for waveform PVs (accommodates up to ~120 BPMs + headroom; actual reported length is what the IOC writes).

Replace `pytxt/ioc/pvs.py` with:

```python
"""caproto PVGroup defining the phase-1 + phase-2 PV namespaces.

Each pvproperty's `doc` becomes the .DESC field — discoverable to
agents reading the IOC's introspection PVs.
"""
from __future__ import annotations

from typing import Optional

import caproto as ca
from caproto.server import PVGroup, pvproperty

from pytxt.handlers.acquire import AcquisitionInFlightError, handle_acquire
from pytxt.handlers.ping import handle_ping
from pytxt.state.app_state import AppState

_BPM_MAX = 128  # waveform max_length; accommodates ~120 BPMs with headroom


class PyTxTPVGroup(PVGroup):
    # === HEALTH:* ===
    heartbeat = pvproperty(
        value=0, dtype=int, read_only=True,
        name="HEALTH:HEARTBEAT",
        doc="Liveness counter; increments every 1 second",
    )
    uptime_s = pvproperty(
        value=0.0, dtype=float, read_only=True,
        name="HEALTH:UPTIME_S",
        doc="Seconds since process start",
    )

    # === STATE:* (phase 1) ===
    version = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:VERSION",
        doc="Semantic version of the running PyTxT app",
    )
    last_ping_at = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_PING_AT",
        doc="ISO-8601 UTC timestamp of most recent ping; empty before first ping",
    )
    ping_count = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:PING_COUNT",
        doc="Total pings received since startup",
    )

    # === STATE:ACQUIRE_* (phase 2) ===
    acquire_in_flight = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:ACQUIRE_IN_FLIGHT",
        doc="1 while an acquisition is running; rejects concurrent CMD:ACQUIRE writes",
    )
    last_acquire_status = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:LAST_ACQUIRE_STATUS",
        doc="Enum: 0=NEVER, 1=ACQUIRING, 2=OK, 3=PARTIAL, 4=FAILED",
    )
    last_acquire_ok_count = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:LAST_ACQUIRE_OK_COUNT",
        doc="BPMs that returned valid data on the most recent ACQUIRE",
    )
    last_acquire_fail_count = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:LAST_ACQUIRE_FAIL_COUNT",
        doc="BPMs that timed out or returned invalid data on the most recent ACQUIRE",
    )
    last_acquire_timestamp = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_ACQUIRE_TIMESTAMP",
        doc="ISO-8601 UTC timestamp of the most recent acquisition; empty before first ACQUIRE",
    )
    last_acquire_fail_reason = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_ACQUIRE_FAIL_REASON",
        doc="Short error message when LAST_ACQUIRE_STATUS=FAILED; empty otherwise",
    )
    last_acquire_failed_bpm_names = pvproperty(
        value=[""] * _BPM_MAX, dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_ACQUIRE_FAILED_BPM_NAMES",
        max_length=_BPM_MAX,
        doc="Names of failed BPMs from the most recent ACQUIRE",
    )

    # === RESULT:BPM:* (phase 2) ===
    result_bpm_x_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:X_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM X position (mm) at detected injection turn; NaN for failed BPMs",
    )
    result_bpm_y_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:Y_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM Y position (mm) at detected injection turn; NaN for failed BPMs",
    )
    result_bpm_sum_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:SUM_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM sum signal (AU) at detected injection turn; NaN for failed BPMs",
    )
    result_bpm_injection_turn = pvproperty(
        value=[0] * _BPM_MAX, dtype=int, read_only=True,
        name="RESULT:BPM:INJECTION_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM detected injection-turn sample index; -1 for failed BPMs",
    )
    result_bpm_names = pvproperty(
        value=[""] * _BPM_MAX, dtype=ca.ChannelType.STRING, read_only=True,
        name="RESULT:BPM:NAMES",
        max_length=_BPM_MAX,
        doc="Static-after-startup: canonical BPM prefix for each array index",
    )

    # === CMD:* ===
    cmd_ping = pvproperty(
        value=0, dtype=int,
        name="CMD:PING",
        doc="Write any value to issue a ping (value ignored; trigger only)",
    )
    cmd_acquire = pvproperty(
        value=0, dtype=int,
        name="CMD:ACQUIRE",
        doc="Write any value to trigger BPM acquisition (value ignored; trigger only)",
    )

    def __init__(self, *args, state: AppState, reader: Optional[object] = None, **kwargs):
        self._state = state
        self._reader = reader
        super().__init__(*args, **kwargs)

    @cmd_ping.putter
    async def cmd_ping(self, instance, value):
        await handle_ping(self._state)
        return value

    @cmd_acquire.putter
    async def cmd_acquire(self, instance, value):
        """CA write to CMD:ACQUIRE dispatches to the canonical handler.

        If a reader is not configured (e.g., unit-style tests), the
        write is a no-op so the IOC remains testable in isolation.
        AcquisitionInFlightError is swallowed and surfaced via the
        STATE:ACQUIRE_IN_FLIGHT PV — CA writers see no exception.
        """
        if self._reader is None:
            return value
        try:
            await handle_acquire(self._state, self._reader)
        except AcquisitionInFlightError:
            # Already in flight — state PVs reflect that. CA write returns success.
            pass
        return value
```

- [ ] **Step 2: Run existing IOC tests to confirm the structural change didn't break phase 1.**

```bash
pytest tests/integration/test_ioc_lifecycle.py tests/integration/test_ping_via_ca.py -v
```
Expected: all pass (phase-1 lifecycle and ping tests still green).

- [ ] **Step 3: Commit.**

```bash
git add pytxt/ioc/pvs.py
git commit -m "feat(ioc): add CMD:ACQUIRE + STATE:ACQUIRE_* + RESULT:BPM:* pvproperties"
```

---

### Task M1-9: Extend IOC field-to-PV map with publish helpers

**Files:**
- Modify: `pytxt/ioc/server.py`

- [ ] **Step 1: Modify `pytxt/ioc/server.py` to handle the structured fields.**

The phase-1 `_FIELD_TO_PV_ATTR` is a simple `field → pv_attr` map with a uniform writer. Phase 2 has:
- `acquire_in_flight` → single PV (use existing pattern, with bool→int coercion)
- `last_acquire` → 6 PVs (status, counts, names, timestamp, fail_reason)
- `bpm_prefixes` → `RESULT:BPM:NAMES` (string array, set once at startup)

Add structured-field publishers and a registration that handles both simple and structured fields.

Replace `pytxt/ioc/server.py` entirely:

```python
"""Soft IOC lifecycle wrapper.

Owns the PVGroup, binds AppState changes to PV writes, and exposes
`run()` for composition.py to await.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import Any, Optional

import numpy as np
from caproto.asyncio.server import Context

from pytxt.api.schemas.result import STATUS_STR_TO_INT, LastAcquireResult
from pytxt.ioc.pvs import PyTxTPVGroup
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)


# Simple (1:1) AppState field → PVGroup attribute name mappings.
_FIELD_TO_PV_ATTR: dict[str, str] = {
    "heartbeat": "heartbeat",
    "uptime_s_pushed": "uptime_s",
    "version": "version",
    "last_ping_at": "last_ping_at",
    "ping_count": "ping_count",
}


def _coerce_for_write(value: Any) -> Any:
    """Caproto only accepts int/float/str/list. Coerce bools and None."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    return value


def _pad_string_array(items: list[str], max_len: int) -> list[str]:
    """Pad a variable-length string array to max_len with empty strings."""
    padded = list(items[:max_len])
    padded.extend([""] * (max_len - len(padded)))
    return padded


def _pad_numeric_array(items: list[float] | np.ndarray, max_len: int, fill: float = 0.0) -> list[float]:
    """Convert numpy array → list, padding to max_len. NaN passes through caproto float PVs."""
    arr = np.asarray(items, dtype=float).tolist()
    if len(arr) >= max_len:
        return arr[:max_len]
    arr.extend([fill] * (max_len - len(arr)))
    return arr


def _pad_int_array(items: list[int] | np.ndarray, max_len: int, fill: int = 0) -> list[int]:
    arr = [int(v) for v in np.asarray(items).tolist()]
    if len(arr) >= max_len:
        return arr[:max_len]
    arr.extend([fill] * (max_len - len(arr)))
    return arr


class PyTxTIOC:
    """Wraps the caproto PVGroup with state binding and lifecycle."""

    def __init__(
        self,
        prefix: str,
        host: str,
        port: int,
        repeater_port: int,
        state: AppState,
        reader: Optional[object] = None,
    ):
        self.prefix = prefix
        self.host = host
        self.port = port
        self.repeater_port = repeater_port
        self.state = state
        self.pvgroup = PyTxTPVGroup(prefix=prefix, state=state, reader=reader)
        self._context: Optional[Context] = None
        self._running_event = asyncio.Event()
        self._bind_state_changes()

    def _bind_state_changes(self) -> None:
        """Subscribe to AppState changes; mirror to caproto PVs."""

        # --- Simple 1:1 mappings ---
        for field_name, pv_attr in _FIELD_TO_PV_ATTR.items():
            pv = getattr(self.pvgroup, pv_attr)

            async def _writer(value, _pv=pv, _name=field_name) -> None:
                value = _coerce_for_write(value)
                for attempt in (1, 2):
                    try:
                        await _pv.write(value)
                        return
                    except Exception:
                        if attempt == 1:
                            await asyncio.sleep(0.05)
                            continue
                        logger.exception(
                            "IOC write to PV for AppState field %r failed after retry", _name
                        )

            self.state.subscribe(field_name, _writer)

        # --- Phase 2: acquire_in_flight (bool → 0/1 int) ---
        in_flight_pv = self.pvgroup.acquire_in_flight

        async def _write_in_flight(value) -> None:
            try:
                await in_flight_pv.write(int(bool(value)))
            except Exception:
                logger.exception("IOC write to STATE:ACQUIRE_IN_FLIGHT failed")

        self.state.subscribe("acquire_in_flight", _write_in_flight)

        # --- Phase 2: last_acquire → 6 PVs + result waveforms ---
        async def _publish_last_acquire(value: LastAcquireResult) -> None:
            await self._publish_last_acquire(value)

        self.state.subscribe("last_acquire", _publish_last_acquire)

        # --- Phase 2: bpm_prefixes → RESULT:BPM:NAMES (one-shot at startup) ---
        async def _publish_bpm_names(value: list[str]) -> None:
            try:
                await self.pvgroup.result_bpm_names.write(
                    _pad_string_array(value, max_len=128)
                )
            except Exception:
                logger.exception("IOC write to RESULT:BPM:NAMES failed")

        self.state.subscribe("bpm_prefixes", _publish_bpm_names)

    async def _publish_last_acquire(self, value: LastAcquireResult) -> None:
        """Write all PVs derived from a LastAcquireResult."""
        try:
            await self.pvgroup.last_acquire_status.write(STATUS_STR_TO_INT[value.status.value])
            await self.pvgroup.last_acquire_ok_count.write(value.ok_count)
            await self.pvgroup.last_acquire_fail_count.write(value.fail_count)
            ts = value.timestamp.isoformat() if value.timestamp else ""
            await self.pvgroup.last_acquire_timestamp.write(ts)
            await self.pvgroup.last_acquire_fail_reason.write(value.fail_reason or "")
            await self.pvgroup.last_acquire_failed_bpm_names.write(
                _pad_string_array(value.failed_bpm_names, max_len=128)
            )
        except Exception:
            logger.exception("IOC publish of LastAcquireResult fields failed")

        # Result waveforms: derived from state.last_acquire_raws (the source
        # of truth for the raw data) plus the extracted first-turn arrays
        # which the handler has already pushed into state.last_acquire.
        # We pull from AppState directly to keep this publish atomic-ish.
        raws = self.state.last_acquire_raws
        prefixes = self.state.bpm_prefixes
        try:
            # The first-turn arrays were computed by extract_first_turn in the
            # handler; re-derive them here from raws + the published last_acquire
            # for index alignment. To avoid double work, we use the *already-
            # extracted* values via a small helper on AppState — but since they
            # aren't stored as arrays separately, we re-extract here. This is
            # microseconds for 120 entries.
            from pytxt.domain.first_turn_extract import extract_first_turn

            aligned: dict[str, object] = {p: raws.get(p) for p in prefixes}
            r = extract_first_turn(aligned)
            await self.pvgroup.result_bpm_x_first_turn.write(
                _pad_numeric_array(r.x_first_turn, max_len=128, fill=math.nan)
            )
            await self.pvgroup.result_bpm_y_first_turn.write(
                _pad_numeric_array(r.y_first_turn, max_len=128, fill=math.nan)
            )
            await self.pvgroup.result_bpm_sum_first_turn.write(
                _pad_numeric_array(r.sum_first_turn, max_len=128, fill=math.nan)
            )
            await self.pvgroup.result_bpm_injection_turn.write(
                _pad_int_array(r.injection_turn, max_len=128, fill=-1)
            )
        except Exception:
            logger.exception("IOC publish of RESULT:BPM:* waveforms failed")

    async def run(self) -> None:
        if self.port:
            os.environ["EPICS_CAS_SERVER_PORT"] = str(self.port)
            os.environ["EPICS_CA_SERVER_PORT"] = str(self.port)
        if self.host:
            os.environ["EPICS_CAS_INTF_ADDR_LIST"] = self.host
        if self.repeater_port:
            os.environ["EPICS_CA_REPEATER_PORT"] = str(self.repeater_port)

        running_event = self._running_event
        pvgroup = self.pvgroup
        state = self.state

        async def _startup_hook(async_lib) -> None:
            # Push phase-1 initial values
            for field_name, pv_attr in _FIELD_TO_PV_ATTR.items():
                value = getattr(state, field_name, None)
                if value is None:
                    value = "" if field_name == "last_ping_at" else 0
                pv = getattr(pvgroup, pv_attr)
                try:
                    await pv.write(value)
                except Exception:
                    logger.exception("IOC startup: failed to initialise PV for field %r", field_name)

            # Push phase-2 initial values (NAMES is the most important — it's static)
            try:
                await pvgroup.result_bpm_names.write(
                    _pad_string_array(state.bpm_prefixes, max_len=128)
                )
                await pvgroup.acquire_in_flight.write(int(state.acquire_in_flight))
                await pvgroup.last_acquire_status.write(
                    STATUS_STR_TO_INT[state.last_acquire.status.value]
                )
            except Exception:
                logger.exception("IOC startup: failed to initialise phase-2 PVs")

            running_event.set()

        self._context = Context(self.pvgroup.pvdb)
        await self._context.run(log_pv_names=False, startup_hook=_startup_hook)

    async def wait_until_running(self, timeout: float = 5.0) -> None:
        await asyncio.wait_for(self._running_event.wait(), timeout=timeout)
```

- [ ] **Step 2: Run phase-1 IOC tests to confirm nothing broke.**

```bash
pytest tests/integration/test_ioc_lifecycle.py tests/integration/test_ping_via_ca.py tests/integration/test_state_endpoint.py -v
```
Expected: all pass.

- [ ] **Step 3: Commit.**

```bash
git add pytxt/ioc/server.py
git commit -m "feat(ioc): bind phase-2 AppState fields to RESULT:BPM:* and STATE:ACQUIRE_* PVs"
```

---

### Task M1-10: REST POST /api/v1/cmd/acquire route

**Files:**
- Modify: `pytxt/api/routes/cmd.py`

- [ ] **Step 1: Write the failing integration test.**

Create `tests/integration/test_acquire_via_rest.py`:

```python
"""Integration: POST /api/v1/cmd/acquire calls handle_acquire and returns AcquireResponse."""
from unittest.mock import AsyncMock
from datetime import datetime, timezone

import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport

from pytxt.domain.types import RawBPM


def _fake_raw(prefix):
    sum_wf = np.full(100000, 1000, dtype=np.int32)
    sum_wf[1370:] = 200000
    return RawBPM(
        prefix=prefix,
        x_wf=np.full(100000, 80_000, dtype=np.int32),
        y_wf=np.zeros(100000, dtype=np.int32),
        sum_wf=sum_wf,
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_post_acquire_returns_response():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["A"])
    reader = AsyncMock()
    reader.read_all.return_value = {"A": _fake_raw("A")}

    app = create_app(state=state)
    app.state.bpm_reader = reader

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/acquire", json={})

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "OK"
    assert body["ok_count"] == 1
    assert body["fail_count"] == 0


@pytest.mark.asyncio
async def test_post_acquire_concurrent_returns_409():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["A"], acquire_in_flight=True)
    reader = AsyncMock()
    app = create_app(state=state)
    app.state.bpm_reader = reader

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/acquire", json={})
    assert r.status_code == 409
```

- [ ] **Step 2: Run to verify failing.**

```bash
pytest tests/integration/test_acquire_via_rest.py -v
```
Expected: 404 (route not yet wired).

- [ ] **Step 3: Modify `pytxt/api/routes/cmd.py`.**

Replace the file with:

```python
"""POST /api/v1/cmd/* — REST mirrors of CMD-PV writes.

These endpoints invoke the **same handler functions** the IOC's CMD-PV
dispatcher invokes. The shared import enforces agentic parity
structurally — there is no way for REST and CA paths to diverge.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from pytxt.api.schemas.cmd import PingResponse
from pytxt.api.schemas.result import AcquireResponse
from pytxt.handlers.acquire import AcquisitionInFlightError, handle_acquire
from pytxt.handlers.ping import handle_ping

router = APIRouter(prefix="/api/v1/cmd", tags=["cmd"])


@router.post("/ping", response_model=PingResponse)
async def post_ping(request: Request) -> PingResponse:
    """Issue a ping. Body: ``{}``. Identical effect to CA write to CMD:PING."""
    state = request.app.state.app_state
    await handle_ping(state)
    return PingResponse(acknowledged_at=datetime.now(timezone.utc).isoformat())


@router.post("/acquire", response_model=AcquireResponse)
async def post_acquire(request: Request) -> AcquireResponse:
    """Trigger BPM acquisition. Body: ``{}``. Identical effect to CA write to CMD:ACQUIRE.

    Returns 409 if an acquisition is already in flight.
    """
    state = request.app.state.app_state
    reader = getattr(request.app.state, "bpm_reader", None)
    if reader is None:
        raise HTTPException(503, "BPM reader not configured")
    try:
        return await handle_acquire(state, reader)
    except AcquisitionInFlightError as e:
        raise HTTPException(409, str(e))
```

- [ ] **Step 4: Run to verify pass.**

```bash
pytest tests/integration/test_acquire_via_rest.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit.**

```bash
git add pytxt/api/routes/cmd.py tests/integration/test_acquire_via_rest.py
git commit -m "feat(api): POST /api/v1/cmd/acquire route (409 on concurrent)"
```

---

### Task M1-11: Extend `/api/v1/state` projection

**Files:**
- Modify: `pytxt/api/schemas/state.py`
- Modify: `pytxt/api/routes/state.py`

- [ ] **Step 1: Append failing test to `tests/integration/test_state_endpoint.py`.**

```python
@pytest.mark.asyncio
async def test_state_endpoint_includes_phase_2_fields():
    from pytxt.state.app_state import AppState
    from pytxt.api.server import create_app
    import time

    state = AppState(version="0.1.0", started_at=time.time(), bpm_prefixes=["A", "B"])
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/state")

    assert r.status_code == 200
    body = r.json()
    assert body["bpm_prefixes"] == ["A", "B"]
    assert body["acquire_in_flight"] is False
    assert body["last_acquire"]["status"] == "NEVER"
```

- [ ] **Step 2: Run to verify failing.**

```bash
pytest tests/integration/test_state_endpoint.py -v -k "phase_2"
```
Expected: fail with `KeyError` on `bpm_prefixes`.

- [ ] **Step 3: Modify `pytxt/api/schemas/state.py`.**

```python
"""REST schema: full AppState projection."""
from typing import Optional
from pydantic import BaseModel, Field

from pytxt.api.schemas.result import LastAcquireResult


class StateSnapshot(BaseModel):
    """Projection of AppState fields for `GET /api/v1/state`. Pure
    one-to-one mapping to the published HEALTH:*, STATE:*, and RESULT:* PVs."""
    # Phase 1
    version: str = Field(description="Semantic version of the running app")
    heartbeat: int = Field(description="Liveness counter; increments every 1s")
    uptime_s: float = Field(description="Seconds since process start")
    last_ping_at: Optional[str] = Field(default=None)
    ping_count: int = Field(description="Pings received since startup")
    # Phase 2
    bpm_prefixes: list[str] = Field(
        default_factory=list,
        description="Configured BPM prefixes; static after startup",
    )
    acquire_in_flight: bool = Field(
        default=False,
        description="True while an acquisition is running",
    )
    last_acquire: LastAcquireResult = Field(
        description="Outcome of the most recent ACQUIRE; status=NEVER before first"
    )
```

- [ ] **Step 4: Modify `pytxt/api/routes/state.py`.**

```python
"""GET /api/v1/state — full AppState snapshot.
GET /api/v1/config — frontend bootstrap config (PV prefix etc.).
"""
from fastapi import APIRouter, Request

from pytxt.api.schemas.state import StateSnapshot

router = APIRouter(prefix="/api/v1", tags=["state"])


@router.get("/state", response_model=StateSnapshot)
async def get_state(request: Request) -> StateSnapshot:
    state = request.app.state.app_state
    return StateSnapshot(
        version=state.version,
        heartbeat=state.heartbeat,
        uptime_s=state.uptime_s,
        last_ping_at=state.last_ping_at,
        ping_count=state.ping_count,
        bpm_prefixes=state.bpm_prefixes,
        acquire_in_flight=state.acquire_in_flight,
        last_acquire=state.last_acquire,
    )


@router.get("/config")
async def get_config(request: Request) -> dict:
    settings = request.app.state.settings
    prefix = settings.pv_prefix if settings else "OSPREY:TEST:TXT:"
    return {"pv_prefix": prefix}
```

- [ ] **Step 5: Run to verify pass.**

```bash
pytest tests/integration/test_state_endpoint.py -v
```
Expected: all pass (phase-1 tests + the new phase-2 test).

- [ ] **Step 6: Commit.**

```bash
git add pytxt/api/schemas/state.py pytxt/api/routes/state.py tests/integration/test_state_endpoint.py
git commit -m "feat(api): extend /api/v1/state with phase-2 fields"
```

---

### Task M1-12: Parity test — add the `acquire` row

**Files:**
- Modify: `tests/integration/test_parity.py`

The parity test is the load-bearing invariant for every command. The existing test parametrizes over `command_name, ca_pv_suffix, rest_path`. Adding ACQUIRE requires injecting a fake reader into both paths.

- [ ] **Step 1: Modify `tests/integration/test_parity.py` to handle the acquire case.**

Replace the whole file with:

```python
"""The agentic-parity invariant test.

For every command that exists in PyTxT, issuing it via CA write and via
REST POST must produce bit-identical state effects. This test is the
load-bearing canary for agentic parity. **It must remain green forever.**
"""
import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import numpy as np
import pytest
from caproto.asyncio.client import Context as ClientContext
from httpx import AsyncClient, ASGITransport

from pytxt.domain.types import RawBPM


def _public_state(state) -> dict:
    """Explicit projection of AppState fields the parity test compares.

    Phase 2: also covers acquire_in_flight, last_acquire.status, ok/fail
    counts. Raw waveform dicts and timestamps are normalized because they
    differ across runs.
    """
    return {
        "heartbeat": state.heartbeat,
        "ping_count": state.ping_count,
        "last_ping_at": "<set>" if state.last_ping_at else None,
        "version": state.version,
        "uptime_s_pushed": state.uptime_s_pushed,
        # phase 2
        "acquire_in_flight": state.acquire_in_flight,
        "last_acquire_status": state.last_acquire.status.value,
        "last_acquire_ok_count": state.last_acquire.ok_count,
        "last_acquire_fail_count": state.last_acquire.fail_count,
        "last_acquire_failed_bpm_names": list(state.last_acquire.failed_bpm_names),
        "last_acquire_timestamp": "<set>" if state.last_acquire.timestamp else None,
        "last_acquire_raws_keys": sorted(state.last_acquire_raws.keys()),
    }


def _fake_raw(prefix):
    sum_wf = np.full(100000, 1000, dtype=np.int32)
    sum_wf[1370:] = 200000
    return RawBPM(
        prefix=prefix,
        x_wf=np.full(100000, 80_000, dtype=np.int32),
        y_wf=np.zeros(100000, dtype=np.int32),
        sum_wf=sum_wf,
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )


async def _do_via_ca(prefix: str, cmd: str) -> None:
    client = ClientContext()
    pv, = await client.get_pvs(prefix + cmd)
    await pv.write(1)
    await asyncio.sleep(0.2)   # let listener fan-out complete


async def _do_via_rest(app, path: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(path, json={})
        assert r.status_code == 200, f"REST {path} failed: {r.status_code} {r.text}"


def _make_state(command_name: str):
    from pytxt.state.app_state import AppState
    bpm = ["A"] if command_name == "acquire" else []
    return AppState(version="0.1.0", started_at=time.time(), bpm_prefixes=bpm)


def _make_reader(command_name: str):
    if command_name != "acquire":
        return None
    reader = AsyncMock()
    reader.read_all.return_value = {"A": _fake_raw("A")}
    return reader


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command_name, ca_pv_suffix, rest_path",
    [
        ("ping", "CMD:PING", "/api/v1/cmd/ping"),
        ("acquire", "CMD:ACQUIRE", "/api/v1/cmd/acquire"),
        # phase 3+: ("load_ref", "CMD:LOAD_REF", "/api/v1/cmd/load-ref"),
    ],
)
async def test_parity_ca_vs_rest(test_pv_prefix, command_name, ca_pv_suffix, rest_path):
    from pytxt.ioc.server import PyTxTIOC
    from pytxt.api.server import create_app

    # --- Path 1: CA write ---
    state_ca = _make_state(command_name)
    reader_ca = _make_reader(command_name)
    ioc_ca = PyTxTIOC(prefix=test_pv_prefix, host="127.0.0.1", port=0,
                      repeater_port=0, state=state_ca, reader=reader_ca)
    server_task = asyncio.create_task(ioc_ca.run())
    await ioc_ca.wait_until_running()
    try:
        before_ca = _public_state(state_ca)
        await _do_via_ca(test_pv_prefix, ca_pv_suffix)
        after_ca = _public_state(state_ca)
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    diff_ca = {k: (before_ca[k], after_ca[k]) for k in after_ca if before_ca[k] != after_ca[k]}

    # --- Path 2: REST POST ---
    state_rest = _make_state(command_name)
    reader_rest = _make_reader(command_name)
    app = create_app(state=state_rest)
    if reader_rest is not None:
        app.state.bpm_reader = reader_rest

    before_rest = _public_state(state_rest)
    await _do_via_rest(app, rest_path)
    after_rest = _public_state(state_rest)
    diff_rest = {k: (before_rest[k], after_rest[k]) for k in after_rest if before_rest[k] != after_rest[k]}

    assert diff_ca == diff_rest, (
        f"Command {command_name!r} produced different effects via CA vs REST.\n"
        f"  CA diff:   {diff_ca}\n"
        f"  REST diff: {diff_rest}\n"
        "The agentic-parity invariant has been violated."
    )
```

- [ ] **Step 2: Run the parity test.**

```bash
pytest tests/integration/test_parity.py -v
```
Expected: 2 passed (ping row + acquire row).

- [ ] **Step 3: Commit.**

```bash
git add tests/integration/test_parity.py
git commit -m "test(parity): add ACQUIRE row to the keystone parity test"
```

---

### Task M1-13: Wire BpmReader into composition

**Files:**
- Modify: `pytxt/composition.py`
- Modify: `pytxt/api/server.py`

- [ ] **Step 1: Modify `pytxt/api/server.py` to accept and store the reader on `app.state.bpm_reader`.**

Replace the file:

```python
"""FastAPI app factory."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pytxt.api.routes import health, cmd, result
from pytxt.api.routes import state as state_route
from pytxt.api import ws_bridge
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def create_app(
    state: AppState,
    settings: Optional[Any] = None,
    bpm_reader: Optional[Any] = None,
) -> FastAPI:
    """Create and configure the FastAPI app.

    Parameters
    ----------
    state : AppState
        Shared in-process state.
    settings : Settings
        Settings instance.
    bpm_reader : BpmReader | None
        Phase-2 CA client. None in tests that don't exercise ACQUIRE.
    """
    app = FastAPI(
        title="PyTxT",
        version=state.version or "0.0.0+dev",
        description=(
            "Turn-by-turn beam analysis service for the ALS injection chain. "
            "REST + WebSocket browser interface; canonical state interface is "
            "EPICS PVs published by the embedded soft IOC."
        ),
    )

    app.state.app_state = state
    app.state.settings = settings
    app.state.bpm_reader = bpm_reader

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(state_route.router)
    app.include_router(cmd.router)
    app.include_router(result.router)
    app.include_router(ws_bridge.router)

    if (_FRONTEND_DIR / "index.html").exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")

    return app
```

Note: this imports `pytxt.api.routes.result`, which we'll create in M4. For M1 we add a *stub* file to make the import succeed.

Create `pytxt/api/routes/result.py` as a stub (real implementation in M4-T1):

```python
"""GET /api/v1/result/* — read-only result endpoints.

Phase 2 M1: stub. Real implementation (raw waveform endpoint) lands in M4.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/v1", tags=["result"])
```

- [ ] **Step 2: Modify `pytxt/composition.py` to construct a BpmReader, hardcoded to one BPM for M1.**

Replace `pytxt/composition.py`:

```python
"""Composition root."""
from __future__ import annotations

import asyncio
import logging
import time
from importlib.metadata import PackageNotFoundError, version as pkg_version

import uvicorn

from pytxt.api.server import create_app
from pytxt.ca_client.bpm_reader import BpmReader
from pytxt.config.settings import Settings
from pytxt.ioc.server import PyTxTIOC
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)


def _resolve_version() -> str:
    try:
        return pkg_version("pytxt")
    except PackageNotFoundError:
        return "0.0.0+dev"


# M1: hardcoded single-BPM list. M2-T1 replaces this with config-file loading.
_PHASE_2_M1_BPM_PREFIXES = ["SR01C:BPM1"]


async def main() -> None:
    settings = Settings()
    settings.version = _resolve_version()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info(
        "PyTxT %s starting | prefix=%s | ioc=%s:%d | api=%s:%d | bpms=%d",
        settings.version, settings.pv_prefix,
        settings.ioc_host, settings.ioc_port,
        settings.api_host, settings.api_port,
        len(_PHASE_2_M1_BPM_PREFIXES),
    )

    state = AppState(
        version=settings.version,
        started_at=time.time(),
        bpm_prefixes=_PHASE_2_M1_BPM_PREFIXES,
    )

    reader = BpmReader(
        prefixes=_PHASE_2_M1_BPM_PREFIXES,
        per_pv_timeout_s=settings.bpm_read_timeout_s,
    )

    ioc = PyTxTIOC(
        prefix=settings.pv_prefix,
        host=settings.ioc_host,
        port=settings.ioc_port,
        repeater_port=settings.ioc_repeater_port,
        state=state,
        reader=reader,
    )

    api_app = create_app(state=state, settings=settings, bpm_reader=reader)
    config = uvicorn.Config(
        api_app,
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
        access_log=False,
    )
    api_server = uvicorn.Server(config)

    async def heartbeat_loop() -> None:
        while True:
            await asyncio.sleep(settings.heartbeat_interval_s)
            await state.update(
                heartbeat=state.heartbeat + 1,
                uptime_s_pushed=state.uptime_s,
            )

    # Start reader once the IOC is running so name resolution sees the network.
    async def start_reader_after_warmup() -> None:
        await asyncio.sleep(1.0)
        try:
            await reader.start()
            logger.info("BpmReader connected to %d BPMs", len(_PHASE_2_M1_BPM_PREFIXES))
        except Exception:
            logger.exception("BpmReader.start() failed — ACQUIRE will fail until reachable")

    await asyncio.gather(
        ioc.run(),
        api_server.serve(),
        heartbeat_loop(),
        start_reader_after_warmup(),
    )
```

- [ ] **Step 3: Modify `pytxt/config/settings.py` to add `bpm_read_timeout_s`.**

Add this field to `Settings` in `pytxt/config/settings.py` after `heartbeat_interval_s`:

```python
    # --- Phase 2 ---
    bpm_read_timeout_s: float = 2.0
```

Also append a placeholder field for phase-2-M2 BPM prefixes path (used in M2):

```python
    bpm_prefixes_path: str = "pytxt/config/bpm_prefixes.txt"
```

- [ ] **Step 4: Run the full integration suite.**

```bash
pytest tests/integration -v
```
Expected: all pass.

- [ ] **Step 5: Commit.**

```bash
git add pytxt/api/server.py pytxt/api/routes/result.py pytxt/composition.py pytxt/config/settings.py
git commit -m "feat(composition): wire BpmReader through composition root (M1 hardcoded SR01C:BPM1)"
```

---

### Task M1-14: Frontend — trajectory page (minimal, N=1)

**Files:**
- Create: `pytxt/frontend/trajectory.html`
- Create: `pytxt/frontend/js/trajectory.js`
- Modify: `pytxt/frontend/index.html` (add nav link)
- Modify: `pytxt/frontend/css/theme.css` (add canvas custom props)

- [ ] **Step 1: Create `pytxt/frontend/trajectory.html`.**

```html
<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>PyTxT — Trajectory</title>
  <link rel="stylesheet" href="/css/theme.css?v=2">
</head>
<body>
  <header class="app-header">
    <h1 class="app-title">PyTxT — Trajectory</h1>
    <nav class="app-nav">
      <a href="/">Ping</a>
      <a href="/trajectory.html" class="active">Trajectory</a>
    </nav>
    <div class="connection-status" id="connectionStatus" data-state="connecting">
      <span class="dot"></span>
      <span class="label" id="connectionStatusLabel">connecting…</span>
    </div>
  </header>

  <main class="app-main">
    <section class="trajectory-panel">
      <div class="trajectory-header">
        <span id="trajectoryStatus">No acquisition yet</span>
        <span id="trajectoryCounts" class="counts"></span>
      </div>
      <div class="canvas-wrap">
        <div class="axis-label">X (mm)</div>
        <canvas id="canvasX" width="800" height="160" aria-label="X position vs BPM index"></canvas>
      </div>
      <div class="canvas-wrap">
        <div class="axis-label">Y (mm)</div>
        <canvas id="canvasY" width="800" height="160" aria-label="Y position vs BPM index"></canvas>
      </div>
      <div class="actions">
        <button type="button" id="acquireButton" class="primary">▶ Acquire</button>
        <span id="acquireMeta" class="meta"></span>
      </div>
    </section>
  </main>

  <script src="/js/connection.js"></script>
  <script src="/js/trajectory.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `pytxt/frontend/js/trajectory.js`.**

```javascript
/* PyTxT trajectory page — phase 2 read-path UI.
 *
 * Subscribes to RESULT:BPM:{X,Y}_FIRST_TURN, INJECTION_TURN, NAMES, and
 * STATE:LAST_ACQUIRE_{STATUS, OK_COUNT, FAIL_COUNT, TIMESTAMP}. Renders
 * stacked X/Y polylines on Canvas. Ignores NaN entries (drawn as gaps).
 *
 * Phase 2 M1: data is length-1, so the "polyline" is one point per panel.
 * Same code handles length-N for M2; no changes needed beyond data flowing.
 */
(function () {
  'use strict';

  const statusEl = document.getElementById('connectionStatus');
  const statusLabelEl = document.getElementById('connectionStatusLabel');
  const trajectoryStatusEl = document.getElementById('trajectoryStatus');
  const trajectoryCountsEl = document.getElementById('trajectoryCounts');
  const acquireButton = document.getElementById('acquireButton');
  const acquireMetaEl = document.getElementById('acquireMeta');
  const canvasX = document.getElementById('canvasX');
  const canvasY = document.getElementById('canvasY');

  const state = {
    prefix: 'OSPREY:TEST:TXT:',  // overridden by /api/v1/config
    x: [], y: [], injectionTurn: [], names: [],
    status: 'NEVER', okCount: 0, failCount: 0, timestamp: '',
  };

  function statusName(code) {
    return ['NEVER', 'ACQUIRING', 'OK', 'PARTIAL', 'FAILED'][code] || 'UNKNOWN';
  }

  function render(canvas, data, color) {
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    // Background
    ctx.fillStyle = getComputedStyle(canvas).getPropertyValue('--canvas-bg').trim() || '#0a0a0a';
    ctx.fillRect(0, 0, w, h);
    // Zero line
    const cy = h / 2;
    ctx.strokeStyle = getComputedStyle(canvas).getPropertyValue('--canvas-grid').trim() || '#333';
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(0, cy); ctx.lineTo(w, cy); ctx.stroke();
    ctx.setLineDash([]);

    if (!data.length) return;
    // Auto-range (symmetric around 0, padded)
    let maxAbs = 0;
    for (const v of data) {
      if (Number.isFinite(v) && Math.abs(v) > maxAbs) maxAbs = Math.abs(v);
    }
    if (maxAbs === 0) maxAbs = 1;  // avoid div-by-zero
    const yScale = (h / 2 - 8) / maxAbs;

    // Plot
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    let pendingMove = true;
    for (let i = 0; i < data.length; i++) {
      const v = data[i];
      if (!Number.isFinite(v)) { pendingMove = true; continue; }
      const x = data.length === 1
        ? w / 2
        : (i * (w - 20) / (data.length - 1)) + 10;
      const y = cy - v * yScale;
      if (pendingMove) { ctx.moveTo(x, y); pendingMove = false; }
      else { ctx.lineTo(x, y); }
      // Point marker (especially useful for N=1)
      ctx.fillRect(x - 1.5, y - 1.5, 3, 3);
    }
    ctx.stroke();
  }

  function redraw() {
    render(canvasX, state.x, getComputedStyle(canvasX).getPropertyValue('--canvas-x').trim() || '#4ade80');
    render(canvasY, state.y, getComputedStyle(canvasY).getPropertyValue('--canvas-y').trim() || '#60a5fa');

    trajectoryStatusEl.textContent = `Status: ${state.status} · turn ${
      Number.isFinite(state.medianTurn) ? state.medianTurn : '—'}`;
    trajectoryCountsEl.textContent =
      `${state.okCount} OK · ${state.failCount} FAIL${state.timestamp ? ' · ' + state.timestamp : ''}`;
  }

  function pv(name) { return state.prefix + name; }

  async function bootstrap() {
    try {
      const cfg = await fetch('/api/v1/config').then(r => r.json());
      state.prefix = cfg.pv_prefix;
    } catch (e) {
      console.warn('Could not fetch /api/v1/config; using default prefix', e);
    }

    connection.onStatusChange((s) => {
      statusEl.dataset.state = s;
      statusLabelEl.textContent = s === 'connected' ? 'connected' : s;
    });

    connection.subscribe(pv('RESULT:BPM:X_FIRST_TURN'), (msg) => {
      state.x = Array.isArray(msg.value) ? msg.value : [msg.value];
      redraw();
    });
    connection.subscribe(pv('RESULT:BPM:Y_FIRST_TURN'), (msg) => {
      state.y = Array.isArray(msg.value) ? msg.value : [msg.value];
      redraw();
    });
    connection.subscribe(pv('RESULT:BPM:INJECTION_TURN'), (msg) => {
      const arr = Array.isArray(msg.value) ? msg.value : [msg.value];
      const valid = arr.filter(v => v >= 0);
      state.medianTurn = valid.length
        ? valid.slice().sort((a, b) => a - b)[Math.floor(valid.length / 2)]
        : null;
      redraw();
    });
    connection.subscribe(pv('RESULT:BPM:NAMES'), (msg) => {
      state.names = Array.isArray(msg.value) ? msg.value : [msg.value];
    });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_STATUS'), (msg) => {
      state.status = statusName(msg.value);
      redraw();
    });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_OK_COUNT'), (msg) => {
      state.okCount = msg.value; redraw();
    });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_FAIL_COUNT'), (msg) => {
      state.failCount = msg.value; redraw();
    });
    connection.subscribe(pv('STATE:LAST_ACQUIRE_TIMESTAMP'), (msg) => {
      state.timestamp = msg.value || ''; redraw();
    });

    acquireButton.addEventListener('click', async () => {
      acquireButton.disabled = true;
      acquireMetaEl.textContent = 'acquiring…';
      try {
        const r = await connection.command('acquire', {});
        acquireMetaEl.textContent = `${r.status} (${r.ok_count} OK · ${r.fail_count} FAIL)`;
      } catch (e) {
        acquireMetaEl.textContent = `error: ${e.message}`;
      } finally {
        acquireButton.disabled = false;
      }
    });
  }

  bootstrap();
})();
```

- [ ] **Step 3: Modify `pytxt/frontend/index.html` to add nav link.**

Find the `<header>` block in `pytxt/frontend/index.html` and add the nav between `<h1>` and `<div class="connection-status">`:

```html
    <h1 class="app-title">PyTxT</h1>
    <nav class="app-nav">
      <a href="/" class="active">Ping</a>
      <a href="/trajectory.html">Trajectory</a>
    </nav>
    <div class="connection-status" ...
```

- [ ] **Step 4: Add canvas custom properties and nav styles to `pytxt/frontend/css/theme.css`.**

Append:

```css
/* === Phase 2 — trajectory page === */
:root {
  --canvas-bg: #0a0a0a;
  --canvas-grid: #2a2a2a;
  --canvas-x: #4ade80;
  --canvas-y: #60a5fa;
}

.app-nav {
  display: flex;
  gap: 0.6rem;
  margin-left: 1.5rem;
}
.app-nav a {
  color: var(--fg-muted, #8a8a92);
  text-decoration: none;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  font-size: 0.9em;
}
.app-nav a.active, .app-nav a:hover {
  color: var(--accent, #0b5fff);
  background: rgba(11, 95, 255, 0.08);
}

.trajectory-panel {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 1rem 1.2rem;
}
.trajectory-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border-bottom: 1px solid #333;
  padding-bottom: 0.4rem;
  font-family: "SF Mono", Menlo, monospace;
  font-size: 0.9em;
}
.trajectory-header .counts {
  color: var(--fg-muted, #8a8a92);
}
.canvas-wrap {
  position: relative;
}
.canvas-wrap .axis-label {
  position: absolute;
  top: 4px;
  left: 8px;
  font-family: "SF Mono", Menlo, monospace;
  font-size: 0.78em;
  color: #888;
  pointer-events: none;
}
canvas {
  display: block;
  width: 100%;
  border: 1px solid #333;
  border-radius: 4px;
  background: var(--canvas-bg);
}
.trajectory-panel .actions {
  display: flex;
  gap: 0.6rem;
  align-items: center;
  margin-top: 0.4rem;
}
.trajectory-panel .actions .meta {
  color: var(--fg-muted, #8a8a92);
  font-family: "SF Mono", Menlo, monospace;
  font-size: 0.85em;
}
```

- [ ] **Step 5: Sanity-check that all tests still pass.**

```bash
pytest tests/unit tests/integration -v
```
Expected: all pass.

- [ ] **Step 6: Commit.**

```bash
git add pytxt/frontend/trajectory.html pytxt/frontend/js/trajectory.js \
        pytxt/frontend/index.html pytxt/frontend/css/theme.css
git commit -m "feat(frontend): trajectory page with stacked X/Y canvases (M1)"
```

---

### Task M1-15: Manual DoD validation (M1)

**Files:** none — manual verification step.

- [ ] **Step 1: Run `python -m pytxt` locally.** (Won't connect to real BPMs unless you're on appsdev2, but the IOC + app should start cleanly.)

```bash
python -m pytxt
```
Expected: log line shows `bpms=1`, IOC binds, FastAPI listens on 8008. Reader will fail to resolve `SR01C:BPM1` from your laptop but the app stays up.

- [ ] **Step 2: From a second terminal, hit the IOC.**

```bash
caget OSPREY:TEST:TXT:RESULT:BPM:NAMES
caget OSPREY:TEST:TXT:STATE:LAST_ACQUIRE_STATUS
```
Expected: `NAMES` shows `SR01C:BPM1` (and empty padding); status returns `0` (NEVER).

- [ ] **Step 3: Open the browser at http://localhost:8008/trajectory.html.** Confirm the page loads and the WS status indicator goes green. Status header shows "NEVER", canvases render zero lines only.

- [ ] **Step 4 (appsdev2-only): scp the code to appsdev2 and run there.** Click ACQUIRE; confirm one datapoint appears in each panel and `STATE:LAST_ACQUIRE_OK_COUNT` becomes 1.

- [ ] **Step 5: Append a decision-log entry summarising any deviations encountered during M1.**

Edit `docs/superpowers/specs/2026-05-18-phase-2-decisions.md`, append an entry per the template.

- [ ] **Step 6: Tag the milestone.**

```bash
git tag phase-2-m1-complete
```

---

## Milestone 2 — Scale to all ~120 BPMs

### Task M2-1: Source the BPM prefix list from MATLAB

**Files:**
- Create: `pytxt/config/bpm_prefixes.txt`

- [ ] **Step 1: On appsdev2 (or any machine with MATLAB + MML), run the one-liner.**

```bash
matlab -batch "b = getbpmlist('nonBergoz'); b([1 2 8 37],:) = []; n = getname('BPMx', b); for i=1:size(n,1); disp(strtrim(n(i,:))); end" > /tmp/bpm_names_raw.txt
```

Translate any underscore-padded MML names to the modern colon form per the convention confirmed by the probe (`SR01C___BPM1X__` → `SR01C:BPM1`). Then `scp` back to your local repo:

```bash
scp appsdev2:/tmp/bpm_names_processed.txt pytxt/config/bpm_prefixes.txt
```

- [ ] **Step 2: Add file header and verify format.**

`pytxt/config/bpm_prefixes.txt` should start with:

```
# ALS storage-ring TBT BPM prefixes
# Sourced YYYY-MM-DD from MATLAB on appsdev2:
#   b = getbpmlist('nonBergoz'); b([1 2 8 37],:) = [];
#   n = getname('BPMx', b); for i=1:size(n,1); disp(strtrim(n(i,:))); end
# ~120 entries after MML exclusions [1 2 8 37]
SR01C:BPM1
SR01C:BPM2
...
```

One prefix per line, `#` comments allowed, no trailing colon on prefix lines.

- [ ] **Step 3: Sanity-check.**

```bash
grep -vE '^(#|\s*$)' pytxt/config/bpm_prefixes.txt | wc -l
```
Expected: ~120 non-blank, non-comment lines.

- [ ] **Step 4: Commit.**

```bash
git add pytxt/config/bpm_prefixes.txt
git commit -m "data: commit ALS storage-ring BPM prefix list (one-time MATLAB dump)"
```

---

### Task M2-2: Load BPM list from file in composition

**Files:**
- Modify: `pytxt/composition.py`

- [ ] **Step 1: Add a loader and use it instead of the hardcoded list.**

Modify `pytxt/composition.py`. Remove `_PHASE_2_M1_BPM_PREFIXES`. Add a loader:

```python
from pathlib import Path


def _load_bpm_prefixes(path: str) -> list[str]:
    """Read one prefix per line; ignore blanks and # comments."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"BPM prefix list not found at {p}. Generate it with the MATLAB "
            f"one-liner described in docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §9.2."
        )
    prefixes: list[str] = []
    with p.open() as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                raise ValueError(
                    f"{p}:{lineno}: invalid BPM prefix {line!r} (must contain ':')"
                )
            prefixes.append(line)
    if not prefixes:
        raise ValueError(f"{p} contains no BPM prefixes (only comments/blanks)")
    return prefixes
```

Replace the hardcoded `bpm_prefixes` use inside `main()` with:

```python
    bpm_prefixes = _load_bpm_prefixes(settings.bpm_prefixes_path)
    logger.info("Loaded %d BPM prefixes from %s", len(bpm_prefixes), settings.bpm_prefixes_path)

    state = AppState(
        version=settings.version,
        started_at=time.time(),
        bpm_prefixes=bpm_prefixes,
    )

    reader = BpmReader(
        prefixes=bpm_prefixes,
        per_pv_timeout_s=settings.bpm_read_timeout_s,
    )
```

- [ ] **Step 2: Run the app to verify it loads cleanly with the real list.**

```bash
python -m pytxt
```
Expected: log shows `Loaded 120 BPM prefixes from pytxt/config/bpm_prefixes.txt`.

Ctrl-C to stop.

- [ ] **Step 3: Confirm tests still pass.**

```bash
pytest tests/unit tests/integration -v
```
Expected: all pass.

- [ ] **Step 4: Commit.**

```bash
git add pytxt/composition.py
git commit -m "feat(composition): load BPM prefix list from pytxt/config/bpm_prefixes.txt"
```

---

### Task M2-3: Integration test — parallel read of multiple BPMs

**Files:**
- Append to `tests/integration/test_bpm_reader.py`

- [ ] **Step 1: Append the failing test (uses fake_bpm_ioc with N=10).**

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [10], indirect=True)
async def test_read_ten_bpms_completes_under_3s(fake_bpm_ioc):
    """Parallel reads of 10 BPMs complete within the spec-stated latency budget."""
    import time
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=3.0)
    await reader.start()
    try:
        t0 = time.monotonic()
        result = await reader.read_all()
        elapsed = time.monotonic() - t0
    finally:
        await reader.stop()

    assert len(result) == 10
    assert all(r is not None for r in result.values())
    assert elapsed < 3.0, f"read_all took {elapsed:.2f}s, expected <3s"
```

- [ ] **Step 2: Run to verify pass.**

```bash
pytest tests/integration/test_bpm_reader.py -v
```
Expected: all pass.

- [ ] **Step 3: Commit.**

```bash
git add tests/integration/test_bpm_reader.py
git commit -m "test(bpm_reader): parallel read of 10 BPMs under 3s budget"
```

---

### Task M2-4: Manual DoD validation (M2)

**Files:** none — manual.

- [ ] **Step 1 (appsdev2-only): deploy + ACQUIRE.** Click ACQUIRE in the browser; confirm response under 3 s and a ring trajectory polyline appears in both panels.
- [ ] **Step 2: Verify result PVs.**

```bash
caget OSPREY:TEST:TXT:STATE:LAST_ACQUIRE_OK_COUNT
caget -# 5 OSPREY:TEST:TXT:RESULT:BPM:X_FIRST_TURN
```
Expected: `OK_COUNT ≈ 120`; X waveform shows ~5 BPM values in mm.

- [ ] **Step 3: Append decision-log entry.**
- [ ] **Step 4: Tag.**

```bash
git tag phase-2-m2-complete
```

---

## Milestone 3 — Failure handling

### Task M3-1: Fault injection in the fake BPM IOC fixture

**Files:**
- Modify: `tests/fixtures/fake_bpm_ioc.py`

- [ ] **Step 1: Extend the fixture with a fault-injection API.**

Append two helpers to `FakeBpmIoc`:

```python
    def take_offline(self, prefix: str) -> None:
        """Cause subsequent CA reads to {prefix}:wfr:TBT:* to time out.

        Implementation: remove the prefix from the served pvdb by stopping
        and restarting Context with the entry removed. For the test-scale
        fixture this is acceptable; we just block at this BPM by replacing
        its PV objects with ones that never respond. Simplest portable
        approach: re-bind that prefix's PV objects with a long-sleeping
        getter override.
        """
        for pv in self._pvgroups[prefix].pvdb.values():
            async def _stalled(*a, **k):
                await asyncio.sleep(60)
                return ()
            pv.getter = _stalled
```

To make `take_offline` work, the existing fixture must keep `_pvgroups: dict[str, PVGroup]` rather than just merging into a single pvdb. Refactor the start-up section of the fixture:

```python
    groups = [_make_bpm_group(p, i) for i, p in enumerate(prefixes)]
    pvgroups = dict(zip(prefixes, groups))
    pvdb: dict = {}
    for g in groups:
        pvdb.update(g.pvdb)

    ctx = Context(pvdb)
    task = asyncio.create_task(ctx.run(log_pv_names=False))
    await asyncio.sleep(0.2)

    handle = FakeBpmIoc(prefixes=prefixes, _context=ctx, _task=task)
    handle._pvgroups = pvgroups
```

Update `@dataclass FakeBpmIoc` to add `_pvgroups: dict = field(default_factory=dict)`.

- [ ] **Step 2: Add a smoke test for fault injection.**

Append to `tests/integration/test_fake_bpm_ioc.py`:

```python
@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [["FAKE:BPM1", "FAKE:BPM2"]], indirect=True)
async def test_take_offline_causes_timeout(fake_bpm_ioc):
    from pytxt.ca_client.bpm_reader import BpmReader
    fake_bpm_ioc.take_offline("FAKE:BPM1")

    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=0.5)
    await reader.start()
    try:
        result = await reader.read_all()
    finally:
        await reader.stop()

    assert result["FAKE:BPM1"] is None
    assert result["FAKE:BPM2"] is not None
```

- [ ] **Step 3: Run.**

```bash
pytest tests/integration/test_fake_bpm_ioc.py -v
```
Expected: all pass.

- [ ] **Step 4: Commit.**

```bash
git add tests/fixtures/fake_bpm_ioc.py tests/integration/test_fake_bpm_ioc.py
git commit -m "test(fixtures): fault injection (take_offline) on fake BPM IOC"
```

---

### Task M3-2: Integration test — handler produces correct partial-fail status

**Files:**
- Create: `tests/integration/test_acquire_via_ca.py`

- [ ] **Step 1: Write the test.**

```python
"""Integration: CA write to CMD:ACQUIRE with one BPM offline produces PARTIAL status."""
import asyncio
import pytest
from caproto.asyncio.client import Context as ClientContext

from pytxt.api.schemas.result import STATUS_INT_TO_STR


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [["FAKE:BPM1", "FAKE:BPM2"]], indirect=True)
async def test_ca_acquire_with_one_offline_returns_partial(test_pv_prefix, fake_bpm_ioc):
    from pytxt.state.app_state import AppState
    from pytxt.ca_client.bpm_reader import BpmReader
    from pytxt.ioc.server import PyTxTIOC
    import time

    fake_bpm_ioc.take_offline("FAKE:BPM1")

    state = AppState(version="0.1.0", started_at=time.time(),
                     bpm_prefixes=fake_bpm_ioc.prefixes)
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=0.5)
    await reader.start()

    ioc = PyTxTIOC(prefix=test_pv_prefix, host="127.0.0.1", port=0,
                   repeater_port=0, state=state, reader=reader)
    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    try:
        client = ClientContext()
        cmd_pv, status_pv, fail_count_pv = await client.get_pvs(
            test_pv_prefix + "CMD:ACQUIRE",
            test_pv_prefix + "STATE:LAST_ACQUIRE_STATUS",
            test_pv_prefix + "STATE:LAST_ACQUIRE_FAIL_COUNT",
        )

        await cmd_pv.write(1)
        await asyncio.sleep(1.0)  # wait for read timeouts + handler

        status_read = await status_pv.read()
        fail_count_read = await fail_count_pv.read()

        assert STATUS_INT_TO_STR[status_read.data[0]] == "PARTIAL"
        assert fail_count_read.data[0] == 1
    finally:
        await reader.stop()
        server_task.cancel()
        try: await server_task
        except asyncio.CancelledError: pass
```

- [ ] **Step 2: Run.**

```bash
pytest tests/integration/test_acquire_via_ca.py -v
```
Expected: 1 passed.

- [ ] **Step 3: Commit.**

```bash
git add tests/integration/test_acquire_via_ca.py
git commit -m "test(integration): CA ACQUIRE with one BPM offline → PARTIAL status PV"
```

---

### Task M3-3: Verify concurrent ACQUIRE returns 409 via REST

**Files:**
- Append to `tests/integration/test_acquire_via_rest.py`

- [ ] **Step 1: Append the test (already in M1-T10 as a basic case; here verify the full handshake when reader is realistic).**

The basic 409 case is already tested in `test_post_acquire_concurrent_returns_409`. Skip if already green.

- [ ] **Step 2: Run.**

```bash
pytest tests/integration/test_acquire_via_rest.py -v
```
Expected: all pass.

- [ ] **Step 3 (optional): Append a "two-concurrent-real-acquires-collide" test.**

```python
@pytest.mark.asyncio
async def test_two_concurrent_acquires_one_returns_409():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState
    from unittest.mock import AsyncMock
    from datetime import datetime, timezone
    import asyncio
    import numpy as np
    from pytxt.domain.types import RawBPM

    state = AppState(version="0.1.0", bpm_prefixes=["A"])

    # Reader that blocks for 0.5s so the two requests overlap
    sum_wf = np.full(100000, 1000, dtype=np.int32); sum_wf[1370:] = 200000
    raw = RawBPM(prefix="A",
        x_wf=np.zeros(100000, dtype=np.int32),
        y_wf=np.zeros(100000, dtype=np.int32),
        sum_wf=sum_wf, armed=0, read_timestamp=datetime.now(timezone.utc))
    reader = AsyncMock()
    async def _slow_read():
        await asyncio.sleep(0.5)
        return {"A": raw}
    reader.read_all = _slow_read

    app = create_app(state=state)
    app.state.bpm_reader = reader

    async def _post():
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            return await ac.post("/api/v1/cmd/acquire", json={})

    r1, r2 = await asyncio.gather(_post(), _post())
    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [200, 409], f"expected one 200 and one 409, got {codes}"
```

- [ ] **Step 4: Commit (only if you added the new test).**

```bash
git add tests/integration/test_acquire_via_rest.py
git commit -m "test(integration): two concurrent /cmd/acquire requests → one 409"
```

---

### Task M3-4: Manual DoD validation (M3)

**Files:** none — manual.

- [ ] **Step 1 (appsdev2-only): trigger ACQUIRE while one BPM is unreachable.** Easiest path: edit `pytxt/config/bpm_prefixes.txt` to include `SR99Z:NONEXISTENT` as an extra prefix, restart, ACQUIRE. Confirm: result returns PARTIAL, `STATE:LAST_ACQUIRE_FAIL_COUNT=1`, frontend shows the gap.
- [ ] **Step 2: Double-click ACQUIRE.** Confirm the second click returns 409 cleanly (no state corruption).
- [ ] **Step 3: Append decision-log entry.**
- [ ] **Step 4: Tag.**

```bash
git tag phase-2-m3-complete
```

---

## Milestone 4 — Raw REST endpoint, UI polish, e2e

### Task M4-1: Implement `GET /api/v1/result/bpm/raw`

**Files:**
- Modify: `pytxt/api/routes/result.py`
- Create: `tests/integration/test_result_raw_endpoint.py`

- [ ] **Step 1: Write failing tests.**

Create `tests/integration/test_result_raw_endpoint.py`:

```python
"""Integration: GET /api/v1/result/bpm/raw?bpm=<prefix>."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport

from pytxt.domain.types import RawBPM


def _raw(prefix):
    return RawBPM(
        prefix=prefix,
        x_wf=np.arange(100000, dtype=np.int32),
        y_wf=np.arange(100000, dtype=np.int32) * 2,
        sum_wf=np.full(100000, 1000, dtype=np.int32),
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_get_raw_returns_200():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["A"])
    state.last_acquire_raws = {"A": _raw("A")}
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw?bpm=A")
    assert r.status_code == 200
    body = r.json()
    assert body["bpm_prefix"] == "A"
    assert len(body["x_nm"]) == 100000
    assert body["armed"] == 0


@pytest.mark.asyncio
async def test_get_raw_missing_query_returns_400():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["A"])
    state.last_acquire_raws = {"A": _raw("A")}
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw")
    assert r.status_code == 422 or r.status_code == 400  # FastAPI returns 422 for missing required query


@pytest.mark.asyncio
async def test_get_raw_unknown_bpm_returns_404():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["A"])
    state.last_acquire_raws = {"A": _raw("A")}
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw?bpm=NOPE")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_raw_no_acquire_returns_409():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["A"])
    # last_acquire_raws stays empty
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw?bpm=A")
    assert r.status_code == 409
```

- [ ] **Step 2: Run to verify failing.**

```bash
pytest tests/integration/test_result_raw_endpoint.py -v
```
Expected: 4 failing (404 or wrong codes from stub router).

- [ ] **Step 3: Implement the endpoint.**

Replace `pytxt/api/routes/result.py`:

```python
"""GET /api/v1/result/* — read-only result endpoints."""
from fastapi import APIRouter, HTTPException, Query, Request

from pytxt.api.schemas.result import BpmRawWaveforms

router = APIRouter(prefix="/api/v1", tags=["result"])


@router.get("/result/bpm/raw", response_model=BpmRawWaveforms)
async def get_bpm_raw(
    request: Request,
    bpm: str = Query(..., description="BPM PV prefix, e.g. 'SR01C:BPM1'"),
) -> BpmRawWaveforms:
    state = request.app.state.app_state
    if bpm not in state.bpm_prefixes:
        raise HTTPException(404, f"BPM {bpm!r} not in configured list")
    if not state.last_acquire_raws:
        raise HTTPException(409, "no acquisition has completed yet")
    raw = state.last_acquire_raws.get(bpm)
    if raw is None:
        raise HTTPException(409, f"BPM {bpm!r} failed in the most recent acquisition")
    return BpmRawWaveforms(
        bpm_prefix=raw.prefix,
        x_nm=raw.x_wf.tolist(),
        y_nm=raw.y_wf.tolist(),
        sum_au=raw.sum_wf.tolist(),
        armed=raw.armed,
        read_timestamp=raw.read_timestamp,
    )
```

- [ ] **Step 4: Run to verify pass.**

```bash
pytest tests/integration/test_result_raw_endpoint.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit.**

```bash
git add pytxt/api/routes/result.py tests/integration/test_result_raw_endpoint.py
git commit -m "feat(api): GET /api/v1/result/bpm/raw with 200/404/409 semantics"
```

---

### Task M4-2: Frontend polish — axis ticks, hover tooltip

**Files:**
- Modify: `pytxt/frontend/js/trajectory.js`
- Modify: `pytxt/frontend/trajectory.html` (add tooltip element)

- [ ] **Step 1: Add a hover tooltip element to `trajectory.html`.**

Inside `<main>`, append after the `.trajectory-panel` section:

```html
<div id="tooltip" class="tooltip" hidden></div>
```

- [ ] **Step 2: Add tooltip styles to `pytxt/frontend/css/theme.css`.**

```css
.tooltip {
  position: fixed;
  pointer-events: none;
  background: rgba(20, 20, 20, 0.95);
  color: #eee;
  padding: 4px 8px;
  border-radius: 4px;
  font-family: "SF Mono", Menlo, monospace;
  font-size: 0.78em;
  border: 1px solid #444;
  z-index: 100;
}
```

- [ ] **Step 3: Extend `trajectory.js` with axis ticks + hover handling.**

Append inside `bootstrap()`:

```javascript
    const tooltip = document.getElementById('tooltip');

    function attachHover(canvas, dataKey) {
      canvas.addEventListener('mousemove', (e) => {
        const data = state[dataKey];
        if (!data || !data.length) return;
        const rect = canvas.getBoundingClientRect();
        const xFrac = (e.clientX - rect.left) / rect.width;
        const idx = Math.min(data.length - 1, Math.max(0, Math.round(xFrac * (data.length - 1))));
        const value = data[idx];
        const name = state.names[idx] || `BPM ${idx}`;
        tooltip.hidden = false;
        tooltip.textContent = Number.isFinite(value)
          ? `${name}  →  ${value.toFixed(3)} mm`
          : `${name}  →  NaN`;
        tooltip.style.left = (e.clientX + 12) + 'px';
        tooltip.style.top = (e.clientY + 12) + 'px';
      });
      canvas.addEventListener('mouseleave', () => { tooltip.hidden = true; });
    }
    attachHover(canvasX, 'x');
    attachHover(canvasY, 'y');
```

- [ ] **Step 4: Visual sanity-check.**

```bash
python -m pytxt
# Open browser at http://localhost:8008/trajectory.html
# Hover canvases; tooltip should follow the cursor and show BPM name + value.
```

- [ ] **Step 5: Commit.**

```bash
git add pytxt/frontend/trajectory.html pytxt/frontend/js/trajectory.js pytxt/frontend/css/theme.css
git commit -m "feat(frontend): hover tooltip showing BPM name + mm value"
```

---

### Task M4-3: Playwright e2e — trajectory acquisition flow

**Files:**
- Create: `tests/e2e/trajectory.spec.js`

- [ ] **Step 1: Write the spec.**

```javascript
// @ts-check
const { test, expect } = require('@playwright/test');

test('trajectory page loads and ACQUIRE button works', async ({ page }) => {
  await page.goto('/trajectory.html');

  // Page renders, status indicator goes green within 3s
  await expect(page.locator('#connectionStatus')).toHaveAttribute('data-state', 'connected', { timeout: 3000 });

  // Canvases are present
  await expect(page.locator('#canvasX')).toBeVisible();
  await expect(page.locator('#canvasY')).toBeVisible();

  // Status starts at NEVER
  await expect(page.locator('#trajectoryStatus')).toContainText('NEVER', { timeout: 3000 });

  // Click ACQUIRE — this will fail to read real BPMs locally, but the
  // server will return a response (FAILED status) and the UI updates.
  // For a clean test we'd run against a fake-BPM-IOC server; for now
  // just verify the click triggers a request and the UI moves out of NEVER.
  const responsePromise = page.waitForResponse(r => r.url().endsWith('/api/v1/cmd/acquire'));
  await page.locator('#acquireButton').click();
  const resp = await responsePromise;
  expect(resp.status()).toBe(200);

  // Status should update away from NEVER
  await expect(page.locator('#trajectoryStatus')).not.toContainText('NEVER', { timeout: 5000 });
});
```

- [ ] **Step 2: Add to `tests/e2e/playwright.config.js` if any project changes needed (likely none — same baseURL pattern).**

(No change needed — Playwright auto-discovers `*.spec.js`.)

- [ ] **Step 3: Run the e2e suite.** Requires the app server running.

```bash
# Terminal 1
python -m pytxt

# Terminal 2
cd tests/e2e && npx playwright test trajectory.spec.js
```
Expected: passes if the server returns 200 (FAILED status is fine — the test only asserts the click works and the UI moves out of NEVER).

- [ ] **Step 4: Commit.**

```bash
git add tests/e2e/trajectory.spec.js
git commit -m "test(e2e): trajectory page acquire click + UI update"
```

---

### Task M4-4: Final DoD verification

**Files:** none — manual run-through of the spec's §12 DoD list.

- [ ] **Step 1: Run the full test suite.**

```bash
pytest tests/unit tests/integration -v
```
Expected: all pass.

- [ ] **Step 2: Run e2e.**

```bash
python -m pytxt &
cd tests/e2e && npx playwright test
```
Expected: all e2e specs (smoke, ping, trajectory) pass.

- [ ] **Step 3: Walk through each of the 12 DoD criteria in `docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md` §12.** Tick each one off in the decision log.

- [ ] **Step 4: Update the live roadmap dashboard.** Edit `PyTxT-roadmap.html`:
  - Hero: progress bar `width: 100%`, text "4 / 4 milestones · complete".
  - Stats: "Phases complete" → `2 / 6`, tests count.
  - Phase 2 card class `now` → `done`; Phase 3 → `now`.
  - Architecture diagram: `◯` → `✓` for ACQUIRE, RESULT:BPM:*, etc.
  - Package map: `pytxt/domain/` and `pytxt/ca_client/` → `pkg done` (Filled).
  - Recent activity: refresh with the most recent ~7 commits.

- [ ] **Step 5: Commit roadmap update + tag phase complete.**

```bash
git add PyTxT-roadmap.html
git commit -m "docs(roadmap): phase 2 complete; advance to phase 3"
git tag phase-2-complete
```

- [ ] **Step 6: Final decision-log entry summarising phase 2.**

Append a short "phase 2 retrospective" entry to `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` covering: what landed, surprises encountered, what to revisit, things learned that should inform phase 3.

---

*End of plan. Implementation handoff via `superpowers:subagent-driven-development` or `superpowers:executing-plans`.*
