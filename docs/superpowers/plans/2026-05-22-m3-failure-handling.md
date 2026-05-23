# M3 Failure Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove PyTxT's failure-handling code paths end-to-end (partial-fail, all-fail, timeout-driven NaN propagation, concurrent-ACQUIRE rejection) and close the one outlier where the production behavior didn't match the spec yet (CA `CMD:ACQUIRE` putter silently swallowed `AcquisitionInFlightError`).

**Architecture:** Tests-heavy milestone. The actual failure-handling code already shipped in M1 — per-PV `asyncio.wait_for` in `BpmReader._read_one`, `handle_acquire._classify` producing `OK`/`PARTIAL`/`FAILED`, `try/finally` clearing `acquire_in_flight`, and `LAST_ACQUIRE_*` PVs all wired. M3 adds two fault-injection parameters to the existing `fake_bpm_ioc` fixture (`offline_prefixes`, `slow_prefixes`), 5 integration tests that exercise the failure paths via those hooks, 1 unit test on the modified putter, and a ~3-line change to `pytxt/ioc/pvs.py` so the CA putter re-raises (symmetric to REST 409).

**Tech Stack:** pytest, pytest-asyncio, caproto async server/client, numpy. Production code stays Python 3.10+ / FastAPI / caproto as in phases 1-2.

**Spec:** `docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md` §11 M3 — see the "M3 detailed design (locked 2026-05-22)" subsection for the four design decisions this plan implements.

**Decision log:** `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` — append `[m3-failure-handling]` entry on closeout (Task 7).

---

## File Structure

**New files:**
- `tests/integration/test_acquire_partial_fail.py` — 3 tests: partial-fail via offline, partial-fail via timeout, STATE-PV publication on partial fail.
- `tests/integration/test_acquire_all_fail.py` — 1 test: all-BPMs-offline → status=FAILED.
- `tests/integration/test_acquire_concurrent_ca.py` — 1 test: CA `caput CMD:ACQUIRE 1` while in-flight raises.
- `tests/unit/test_cmd_acquire_putter.py` — 1 unit test pinning the re-raise behavior.

**Modified files:**
- `tests/fixtures/fake_bpm_ioc.py` — add `offline_prefixes` and `slow_prefixes` support to the existing fixture (backwards-compatible).
- `pytxt/ioc/pvs.py` — `cmd_acquire` putter changes from swallow-and-pass to re-raise.
- `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` — append `[m3-failure-handling]` closeout entry.
- `PyTxT-roadmap.html` — flip M3 to ✓ done, M4 to "now," refresh hero / progress / milestone card / recent activity.

**No new production modules** — the failure-handling code already exists.

---

## Task 1: Extend `fake_bpm_ioc` fixture with `offline_prefixes`

**Files:**
- Modify: `tests/fixtures/fake_bpm_ioc.py`
- Test: `tests/integration/test_fake_bpm_ioc.py` (add a new test; existing file)

**Why:** Today the fixture accepts int N or list[str] as its parametrize input. M3 needs to construct sessions where some configured BPMs are unreachable. The construct-time approach (don't add those PVs to the pvdb at all) is the simplest and most deterministic: `BpmReader.start()`'s `get_pvs(...)` resolution fails for those names; the missing-prefix BPMs end up returning `None` in `read_all` via the "channels is None" early return in `BpmReader._read_one`.

**Design:** Accept a third parametrize form — a dict like `{"n": 5, "offline": ["FAKE:BPM3"]}` or `{"prefixes": [...], "offline": [...]}`. Prefixes listed in `offline` are included in the returned `FakeBpmIoc.prefixes` list (so `BpmReader` is configured to look for them) but **not** built into any PVGroup. Backwards-compatible: int and list[str] params behave exactly as before.

- [ ] **Step 1: Read the current fixture to ground the change**

Read `tests/fixtures/fake_bpm_ioc.py` end-to-end (140 lines). Key bits:
- `_make_bpm_group(prefix, bpm_index)` builds the per-BPM PVGroup (lines 61-85).
- `fake_bpm_ioc(request)` reads `request.param` (lines 97-108).
- `FakeBpmIoc` dataclass holds `prefixes`, `_context`, `_task` (lines 88-95).

- [ ] **Step 2: Write the failing test in `tests/integration/test_fake_bpm_ioc.py`**

```python
# Append to tests/integration/test_fake_bpm_ioc.py (do not overwrite existing tests).

import asyncio
import pytest
from caproto.asyncio.client import Context as ClientContext


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fake_bpm_ioc",
    [{"n": 3, "offline": ["FAKE:BPM2"]}],
    indirect=True,
)
async def test_offline_prefixes_omits_pvs_from_pvdb(fake_bpm_ioc):
    """A prefix in `offline` is reported in fixture.prefixes but its PVs do not exist."""
    assert fake_bpm_ioc.prefixes == ["FAKE:BPM1", "FAKE:BPM2", "FAKE:BPM3"]

    # PVs for the online BPMs resolve.
    async with ClientContext() as ctx:
        online_pv, = await asyncio.wait_for(
            ctx.get_pvs("FAKE:BPM1:wfr:TBT:c0"), timeout=2.0
        )
        result = await online_pv.read()
        assert result.data is not None  # any non-error read is fine

    # PVs for the offline BPM do NOT resolve within a short window.
    async with ClientContext() as ctx:
        with pytest.raises((asyncio.TimeoutError, Exception)):
            await asyncio.wait_for(
                ctx.get_pvs("FAKE:BPM2:wfr:TBT:c0"), timeout=1.0
            )
```

- [ ] **Step 3: Run to verify it fails**

```bash
source .venv/bin/activate && pytest tests/integration/test_fake_bpm_ioc.py::test_offline_prefixes_omits_pvs_from_pvdb -v --tb=short
```

Expected: FAIL — `request.param` is a `dict`, which the current fixture's `isinstance(param, int)` / `else: prefixes = list(param)` doesn't handle (it'll likely try to iterate the dict keys and produce the wrong prefix list).

- [ ] **Step 4: Implement the fixture extension**

In `tests/fixtures/fake_bpm_ioc.py`, replace the parametrize-handling block (lines 97-114 area, the part inside the fixture function up to the pvdb construction) with logic that handles the new dict form:

```python
@pytest_asyncio.fixture
async def fake_bpm_ioc(request) -> FakeBpmIoc:
    """Parametrize via @pytest.mark.parametrize('fake_bpm_ioc', [N_or_list_or_dict], indirect=True).

    Three accepted forms for `request.param`:
    - int N → prefixes are ["FAKE:BPM1", ..., "FAKE:BPMN"], all healthy.
    - list[str] → those exact prefixes, all healthy.
    - dict with optional keys:
        - "n" (int) OR "prefixes" (list[str]) — defines the prefix set (mutually exclusive).
        - "offline" (list[str], optional) — these prefixes are reported in
          fixture.prefixes but their PVs are not built into the IOC, so
          BpmReader sees them as unreachable.
        - "slow" — reserved for Task 2; ignored here.
    """
    param = request.param if hasattr(request, "param") else 1

    offline_set: set[str] = set()
    if isinstance(param, int):
        prefixes = [f"FAKE:BPM{i+1}" for i in range(param)]
    elif isinstance(param, list):
        prefixes = list(param)
    elif isinstance(param, dict):
        if "n" in param and "prefixes" in param:
            raise ValueError("fake_bpm_ioc: pass either 'n' or 'prefixes', not both")
        if "n" in param:
            prefixes = [f"FAKE:BPM{i+1}" for i in range(int(param["n"]))]
        elif "prefixes" in param:
            prefixes = list(param["prefixes"])
        else:
            raise ValueError("fake_bpm_ioc dict param needs 'n' or 'prefixes'")
        offline_set = set(param.get("offline", []))
    else:
        raise TypeError(
            f"fake_bpm_ioc: unsupported param type {type(param).__name__}"
        )

    # Build PVGroups only for the online subset; offline prefixes get no PVs.
    groups = [
        _make_bpm_group(p, i)
        for i, p in enumerate(prefixes)
        if p not in offline_set
    ]
    pvdb: dict = {}
    for g in groups:
        pvdb.update(g.pvdb)
```

Keep the rest of the fixture (the `ctx = Context(pvdb)` line down through teardown) unchanged.

- [ ] **Step 5: Run the new test to verify it passes**

```bash
source .venv/bin/activate && pytest tests/integration/test_fake_bpm_ioc.py::test_offline_prefixes_omits_pvs_from_pvdb -v --tb=short
```

Expected: PASS.

- [ ] **Step 6: Run the full integration suite to confirm no regression on existing fixture users**

```bash
source .venv/bin/activate && pytest tests/integration/ -q --tb=short
```

Expected: existing tests still green (no `dict`-form callers existed before; backwards-compat preserved).

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/fake_bpm_ioc.py tests/integration/test_fake_bpm_ioc.py
git commit -m "test(fixtures): M3 — fake_bpm_ioc accepts dict param with offline_prefixes

Adds a third parametrize form for fake_bpm_ioc: dict with keys 'n' or
'prefixes' (mutually exclusive) plus optional 'offline'. Prefixes in
offline appear in fixture.prefixes (so BpmReader is configured to look
for them) but their PVs are not built into the IOC's pvdb, so
get_pvs() times out for them and BpmReader sees them as unreachable.

Backwards-compatible: int N and list[str] params behave exactly as before.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md
\§11 M3 'M3 detailed design (locked 2026-05-22)'."
```

---

## Task 2: Extend `fake_bpm_ioc` fixture with `slow_prefixes`

**Files:**
- Modify: `tests/fixtures/fake_bpm_ioc.py`
- Test: `tests/integration/test_fake_bpm_ioc.py` (add another test)

**Why:** Offline tests exercise the `BpmReader._read_one` "channels is None" early-return path. Timeout tests exercise the per-read `wait_for` path — a different code branch with the same observable outcome (`None` in result dict → NaN in result waveform). Both need coverage to fully prove the failure-handling architecture.

**Design:** New parametrize key `slow` (a list of prefixes). A slow PVGroup factory `_make_slow_bpm_group(prefix, bpm_index, delay_s)` mirrors `_make_bpm_group` but with custom async getters on `c0/c1/c3/armed` that `await asyncio.sleep(delay_s)` before returning the static value. Default `delay_s = 3.0` — comfortably above the production `per_pv_timeout_s=2.0` (so the read always times out) and above the typical test reader's `5.0` (used in M2-2 scale tests) so timeout tests can still trigger when callers want headroom. Tests that need the per-read timeout to fire use the production-style 2.0 s reader timeout; tests that want successful reads of slow BPMs use a high reader timeout.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/integration/test_fake_bpm_ioc.py.

import time

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fake_bpm_ioc",
    [{"n": 2, "slow": ["FAKE:BPM2"]}],
    indirect=True,
)
async def test_slow_prefixes_read_takes_longer_than_default_delay(fake_bpm_ioc):
    """A slow BPM's read takes at least the configured delay (~3 s default)."""
    async with ClientContext() as ctx:
        slow_pv, = await asyncio.wait_for(
            ctx.get_pvs("FAKE:BPM2:wfr:TBT:c0"), timeout=2.0
        )
        # PV resolves quickly; the SLOW behavior is on read, not on connect.
        t0 = time.monotonic()
        result = await asyncio.wait_for(slow_pv.read(), timeout=5.0)
        elapsed = time.monotonic() - t0
        assert elapsed >= 2.5, f"slow read returned in {elapsed:.2f}s; expected ≥2.5s"
        assert result.data is not None
```

- [ ] **Step 2: Run to verify it fails**

```bash
source .venv/bin/activate && pytest tests/integration/test_fake_bpm_ioc.py::test_slow_prefixes_read_takes_longer_than_default_delay -v --tb=short
```

Expected: FAIL — the `slow` key is currently ignored by the fixture (per Task 1 docstring, "reserved for Task 2; ignored here"), so the BPM behaves like a healthy fast one and the read returns immediately.

- [ ] **Step 3: Implement the slow PVGroup factory + fixture dispatch**

In `tests/fixtures/fake_bpm_ioc.py`, add a new factory below `_make_bpm_group`:

```python
_SLOW_DELAY_S_DEFAULT = 3.0  # > production per_pv_timeout_s=2.0


def _make_slow_bpm_group(prefix: str, bpm_index: int, delay_s: float) -> PVGroup:
    """Like _make_bpm_group, but each pvproperty has an async getter that
    sleeps `delay_s` seconds before returning the static value. Used to
    exercise BpmReader._read_one's per-PV wait_for timeout path."""
    x_nm, y_nm, sum_au = _synthesize_waveforms(bpm_index)

    class SlowFakeBPM(PVGroup):
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

        @c0.getter
        async def c0(self, instance):
            await asyncio.sleep(delay_s)
            return instance.value

        @c1.getter
        async def c1(self, instance):
            await asyncio.sleep(delay_s)
            return instance.value

        @c3.getter
        async def c3(self, instance):
            await asyncio.sleep(delay_s)
            return instance.value

        @armed.getter
        async def armed(self, instance):
            await asyncio.sleep(delay_s)
            return instance.value

    return SlowFakeBPM(prefix=prefix + ":" if not prefix.endswith(":") else prefix)
```

Update the parametrize dispatch from Task 1 to also extract `slow_set`:

```python
elif isinstance(param, dict):
    # ... existing 'n' / 'prefixes' handling ...
    offline_set = set(param.get("offline", []))
    slow_set = set(param.get("slow", []))
```

And change the group construction to dispatch between fast and slow factories:

```python
groups = []
for i, p in enumerate(prefixes):
    if p in offline_set:
        continue
    if p in slow_set:
        groups.append(_make_slow_bpm_group(p, i, _SLOW_DELAY_S_DEFAULT))
    else:
        groups.append(_make_bpm_group(p, i))
```

(For non-dict params, `slow_set` defaults to empty — initialize it alongside `offline_set` at the top of the dispatch.)

**On caproto getter syntax:** if `@c0.getter` doesn't work due to caproto version differences (the decorator pattern shadows the descriptor in some caproto versions), the alternative is the `read=` parameter on pvproperty: define an async function `slow_c0_read(group, instance)` and pass `read=slow_c0_read` to `pvproperty(...)`. The failing test will be diagnostic.

- [ ] **Step 4: Run the new test to verify it passes**

```bash
source .venv/bin/activate && pytest tests/integration/test_fake_bpm_ioc.py::test_slow_prefixes_read_takes_longer_than_default_delay -v --tb=short
```

Expected: PASS — the slow read takes ~3 s.

- [ ] **Step 5: Re-run the offline test from Task 1 to confirm no regression**

```bash
source .venv/bin/activate && pytest tests/integration/test_fake_bpm_ioc.py -v --tb=short
```

Expected: every test in the file green, including the existing M1/M2 ones and the new offline + slow tests.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/fake_bpm_ioc.py tests/integration/test_fake_bpm_ioc.py
git commit -m "test(fixtures): M3 — fake_bpm_ioc supports slow_prefixes for timeout simulation

Adds a 'slow' key to the dict-form parametrize: prefixes in that list
get a custom PVGroup whose c0/c1/c3/armed pvproperty getters
await asyncio.sleep(_SLOW_DELAY_S_DEFAULT=3.0) before returning. PVs
resolve normally on connect; the slowdown is on per-read.

This exercises the BpmReader._read_one wait_for timeout path
(different code branch from offline_prefixes which fails at get_pvs).
The 3.0 s default sits above the production per_pv_timeout_s=2.0 so
reads always time out, and above typical test reader timeouts of
5.0 s so tests can still selectively allow slow reads when desired.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md
\§11 M3 'M3 detailed design (locked 2026-05-22)'."
```

---

## Task 3: Fix `cmd_acquire` putter to re-raise `AcquisitionInFlightError`

**Files:**
- Modify: `pytxt/ioc/pvs.py:137-158` (the `cmd_acquire.putter` method)
- Test: `tests/unit/test_cmd_acquire_putter.py` (new file)

**Why:** Current putter (lines 142-158 of `pytxt/ioc/pvs.py`) catches and swallows `AcquisitionInFlightError`, returning the written value as if the put succeeded. The spec calls for "409 / CA alarm for concurrent ACQUIRE" — REST's 409 works; the CA side is the gap. Re-raising lets caproto encode the failure as a CA write error symmetric to REST's 409. The `STATE:ACQUIRE_IN_FLIGHT` PV continues to publish `1` during the busy window for subscribers who prefer observation over retry.

**Design:** ~3-line change to the putter body. The unit test mocks the reader and constructs an `AppState` with `acquire_in_flight=True`; the putter call must raise (currently silently returns).

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/test_cmd_acquire_putter.py`:

```python
"""Unit: cmd_acquire putter must surface AcquisitionInFlightError to CA clients.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §11 M3.
Symmetric to REST's 409 returned by /api/v1/cmd/acquire when a concurrent
acquire is in flight (see tests/integration/test_acquire_via_rest.py).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from pytxt.handlers.acquire import AcquisitionInFlightError
from pytxt.ioc.pvs import PyTxTPVGroup
from pytxt.state.app_state import AppState


@pytest.mark.asyncio
async def test_cmd_acquire_putter_reraises_when_in_flight():
    """A caput while in-flight must propagate AcquisitionInFlightError so
    caproto encodes it as a CA write error to the client."""
    state = AppState(version="test", bpm_prefixes=["FAKE:BPM1"], acquire_in_flight=True)
    reader = AsyncMock()  # never gets called because the in-flight guard fires first

    pvgroup = PyTxTPVGroup(prefix="OSPREY:TEST:TXT:", state=state, reader=reader)
    instance = MagicMock()  # caproto passes a ChannelData; the putter doesn't use it

    with pytest.raises(AcquisitionInFlightError):
        await pvgroup.cmd_acquire.putter._wrapper(pvgroup, instance, 1)
```

**Note on the call shape:** the putter is bound via caproto's `@cmd_acquire.putter` decorator; calling it directly from a unit test means invoking the underlying coroutine. Inspect `PyTxTPVGroup.cmd_acquire.putter` to determine the correct call shape (caproto stores the wrapped function on the pvproperty); if `._wrapper` is not the right attribute in the installed caproto version, use `pvgroup._cmd_acquire_putter` or whichever attribute exposes the coroutine. The failing test will be diagnostic — adjust the call site, not the assertion.

- [ ] **Step 2: Run the test to verify it fails**

```bash
source .venv/bin/activate && pytest tests/unit/test_cmd_acquire_putter.py -v --tb=short
```

Expected: FAIL — the current putter swallows `AcquisitionInFlightError` (returns `value` instead of raising).

If the test fails because of a putter-call-shape issue rather than the raise/no-raise behavior, adjust the test's call shape and try again. The behavior under test is the raise; the call shape is incidental.

- [ ] **Step 3: Modify the putter in `pytxt/ioc/pvs.py`**

Replace the `cmd_acquire` putter (the method body around lines 142-158) with:

```python
    @cmd_acquire.putter
    async def cmd_acquire(self, instance, value):
        """CA write to CMD:ACQUIRE dispatches to the canonical handler.

        If a reader is not configured (e.g., unit-style tests), the
        write is a no-op so the IOC remains testable in isolation.

        AcquisitionInFlightError is RE-RAISED so caproto surfaces it as a
        CA write error to the client — symmetric to REST's 409 returned
        by POST /api/v1/cmd/acquire when an acquire is in flight. The
        STATE:ACQUIRE_IN_FLIGHT PV continues to publish 1 during the
        busy window for subscribers who prefer observation over retry.
        """
        if self._reader is None:
            return value
        await handle_acquire(self._state, self._reader)
        return value
```

Two changes:
1. Removed the `try / except AcquisitionInFlightError: pass` wrapping.
2. Updated docstring to reflect the new behavior.

- [ ] **Step 4: Run the unit test to verify it passes**

```bash
source .venv/bin/activate && pytest tests/unit/test_cmd_acquire_putter.py -v --tb=short
```

Expected: PASS.

- [ ] **Step 5: Run the integration tests that exercise the putter to confirm no regression on the happy path**

```bash
source .venv/bin/activate && pytest tests/integration/test_acquire_via_rest.py tests/integration/test_ping_via_ca.py -q --tb=short
```

Expected: all green. The happy-path CA acquire (state.acquire_in_flight=False at entry) still completes successfully.

- [ ] **Step 6: Commit**

```bash
git add pytxt/ioc/pvs.py tests/unit/test_cmd_acquire_putter.py
git commit -m "fix(ioc): M3 — cmd_acquire putter re-raises AcquisitionInFlightError

Previously the CA putter caught and silently swallowed
AcquisitionInFlightError, returning the written value as if the put
had succeeded. The spec calls for 'CA alarm' symmetric to REST's 409
returned by POST /api/v1/cmd/acquire; re-raising lets caproto encode
the failure as a CA write error to the client.

STATE:ACQUIRE_IN_FLIGHT still publishes 1 during the in-flight window
so subscribers who prefer observation over retry are unaffected.

1 new unit test in tests/unit/test_cmd_acquire_putter.py pins the
re-raise behavior. Integration tests on the happy-path CA acquire
remain green (no regression).

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md
\§11 M3 'M3 detailed design (locked 2026-05-22)'."
```

---

## Task 4: Partial-fail integration tests

**Files:**
- Create: `tests/integration/test_acquire_partial_fail.py`

**Why:** Three tests exercise the M3 PARTIAL path: one via `offline_prefixes` (Task 1 fixture path), one via `slow_prefixes` (Task 2 fixture path), and one that confirms the IOC's `STATE:LAST_ACQUIRE_*` PVs reflect the partial-fail state correctly so external observers (Phoebus, Osprey agents) see what the browser sees. Grouped in one file because they share fixture setup shape (N=5 with one failing prefix) and the per-file pytest setup cost is non-trivial.

**Design:** Each test starts a real `BpmReader` against a `fake_bpm_ioc` parametrized with one failing prefix, calls `handle_acquire` directly (mirrors `test_acquire_scale.py`), then asserts the resulting `AppState.last_acquire` shape. The state-PV test additionally constructs a `PyTxTIOC`, starts it, and reads the LAST_ACQUIRE_* PVs via a separate CA client.

- [ ] **Step 1: Write the failing test file**

Create `tests/integration/test_acquire_partial_fail.py`:

```python
"""Integration: M3 partial-fail scenarios — some BPMs fail, others succeed.

Three tests cover (1) failure via offline_prefixes, (2) failure via
slow_prefixes (timeout), and (3) the IOC's STATE:LAST_ACQUIRE_* PVs
reflect the partial-fail state correctly for external CA observers.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §11 M3.
"""
import asyncio
import math

import numpy as np
import pytest
from caproto.asyncio.client import Context as ClientContext

from pytxt.ca_client.bpm_reader import BpmReader
from pytxt.handlers.acquire import handle_acquire
from pytxt.ioc.server import PyTxTIOC
from pytxt.state.app_state import AppState


async def _disconnect_quietly(client):
    if client is None:
        return
    try:
        await asyncio.wait_for(client.disconnect(), timeout=2.0)
    except (asyncio.TimeoutError, Exception):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fake_bpm_ioc",
    [{"n": 5, "offline": ["FAKE:BPM3"]}],
    indirect=True,
)
async def test_acquire_partial_fail_via_offline(fake_bpm_ioc):
    """One BPM offline; ACQUIRE returns PARTIAL with that BPM in failed list."""
    state = AppState(version="m3-test", bpm_prefixes=fake_bpm_ioc.prefixes)
    # Use the production default per_pv_timeout=2.0 so the offline BPM's
    # name resolution fails within the test's patience window.
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=2.0)
    await reader.start()
    try:
        await handle_acquire(state, reader)
    finally:
        await reader.stop()

    assert state.last_acquire.status == "PARTIAL", (
        f"expected PARTIAL, got {state.last_acquire.status} "
        f"(fail_reason={state.last_acquire.fail_reason!r}, "
        f"failed={state.last_acquire.failed_bpm_names})"
    )
    assert state.last_acquire.ok_count == 4
    assert state.last_acquire.fail_count == 1
    assert state.last_acquire.failed_bpm_names == ["FAKE:BPM3"]
    assert state.acquire_in_flight is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fake_bpm_ioc",
    [{"n": 5, "slow": ["FAKE:BPM3"]}],
    indirect=True,
)
async def test_acquire_partial_fail_via_timeout(fake_bpm_ioc):
    """One BPM is slow (>per_pv_timeout); ACQUIRE returns PARTIAL via wait_for path."""
    state = AppState(version="m3-test", bpm_prefixes=fake_bpm_ioc.prefixes)
    # Production-style 2.0 s timeout < slow BPM's 3.0 s delay → that BPM fails.
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=2.0)
    await reader.start()
    try:
        await handle_acquire(state, reader)
    finally:
        await reader.stop()

    assert state.last_acquire.status == "PARTIAL", (
        f"expected PARTIAL, got {state.last_acquire.status} "
        f"(failed={state.last_acquire.failed_bpm_names})"
    )
    assert state.last_acquire.ok_count == 4
    assert state.last_acquire.fail_count == 1
    assert state.last_acquire.failed_bpm_names == ["FAKE:BPM3"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fake_bpm_ioc",
    [{"n": 5, "offline": ["FAKE:BPM3"]}],
    indirect=True,
)
async def test_partial_fail_state_pvs_published(fake_bpm_ioc, test_pv_prefix):
    """The IOC publishes LAST_ACQUIRE_* PVs reflecting the partial-fail state."""
    state = AppState(version="m3-test", bpm_prefixes=fake_bpm_ioc.prefixes)
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=2.0)
    await reader.start()

    ioc = PyTxTIOC(
        prefix=test_pv_prefix,
        host="127.0.0.1", port=0, repeater_port=0,
        state=state, reader=reader,
    )
    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    client: ClientContext | None = None
    try:
        # Trigger an acquire via the handler (not via CA, to keep the test
        # independent of Task 6's CA-acquire path).
        await handle_acquire(state, reader)
        await asyncio.sleep(0.2)  # let IOC listeners propagate to PVs

        client = ClientContext()
        status_pv, ok_pv, fail_pv = await client.get_pvs(
            test_pv_prefix + "STATE:LAST_ACQUIRE_STATUS",
            test_pv_prefix + "STATE:LAST_ACQUIRE_OK_COUNT",
            test_pv_prefix + "STATE:LAST_ACQUIRE_FAIL_COUNT",
        )
        status = await status_pv.read()
        ok = await ok_pv.read()
        fail = await fail_pv.read()

        # AcquireStatus.PARTIAL is enum value 3 (per STATUS_INT_TO_STR in
        # pytxt/api/schemas/result.py).
        assert int(status.data[0]) == 3, f"status int = {int(status.data[0])}"
        assert int(ok.data[0]) == 4
        assert int(fail.data[0]) == 1
    finally:
        await _disconnect_quietly(client)
        await reader.stop()
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
```

- [ ] **Step 2: Run the test file to verify all three pass**

```bash
source .venv/bin/activate && pytest tests/integration/test_acquire_partial_fail.py -v --tb=short
```

Expected: 3/3 PASS. The production code (`_classify`, IOC publish helpers) already implements this behavior — these tests are regression coverage that exercises it.

If the second test (`_via_timeout`) fails with the slow BPM unexpectedly succeeding, double-check Task 2's `_SLOW_DELAY_S_DEFAULT = 3.0` and that the test reader's `per_pv_timeout_s=2.0` is correctly less than the delay.

If the third test (`_state_pvs_published`) fails because the status int doesn't match, double-check `STATUS_INT_TO_STR` in `pytxt/api/schemas/result.py` — PARTIAL should be `3`.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_acquire_partial_fail.py
git commit -m "test(integration): M3 — partial-fail scenarios (offline, timeout, state PV publication)

Three tests against the new fake_bpm_ioc fault-injection hooks:

- test_acquire_partial_fail_via_offline: N=5 with one BPM in
  offline_prefixes. Asserts status=PARTIAL, ok_count=4, fail_count=1,
  the offline prefix in failed_bpm_names.
- test_acquire_partial_fail_via_timeout: N=5 with one BPM in
  slow_prefixes (3 s sleep), reader uses production-style 2 s timeout.
  Exercises BpmReader._read_one's wait_for path (different code branch
  from offline) with the same observable outcome.
- test_partial_fail_state_pvs_published: same setup as #1 but runs the
  full PyTxTIOC and reads STATE:LAST_ACQUIRE_{STATUS,OK_COUNT,FAIL_COUNT}
  via a separate CA client. Closes the 'observers see PARTIAL' half of
  the M3 DoD.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §11 M3."
```

---

## Task 5: All-fail integration test

**Files:**
- Create: `tests/integration/test_acquire_all_fail.py`

**Why:** Exercise the `_classify` path where `ok == 0 → FAILED`. Small, focused file. Separate from partial-fail because the assertion shape differs (status=FAILED, ok_count=0, all prefixes in failed_bpm_names) and a future M-something fault-handling improvement might want to land more tests of all-fail behavior here.

- [ ] **Step 1: Write the test file**

Create `tests/integration/test_acquire_all_fail.py`:

```python
"""Integration: M3 all-fail scenario — every BPM is unreachable.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §11 M3.
"""
import pytest

from pytxt.ca_client.bpm_reader import BpmReader
from pytxt.handlers.acquire import handle_acquire
from pytxt.state.app_state import AppState


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fake_bpm_ioc",
    [{"n": 3, "offline": ["FAKE:BPM1", "FAKE:BPM2", "FAKE:BPM3"]}],
    indirect=True,
)
async def test_all_bpms_offline_marks_status_failed(fake_bpm_ioc):
    """When every configured BPM is unreachable, status=FAILED, ok=0, fail=N."""
    state = AppState(version="m3-test", bpm_prefixes=fake_bpm_ioc.prefixes)
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=2.0)
    # reader.start() may raise because get_pvs times out for all names;
    # the production code's start_reader_after_warmup catches and logs,
    # but here we want to exercise the post-start handle_acquire path.
    # If start() raises, that itself is a valid M3 finding worth catching.
    try:
        await reader.start()
    except Exception:
        # All-unreachable case: BpmReader may bail at start(). The handler
        # path is what we want to test, so swallow here and rely on the
        # handler's exception path to set status=FAILED via its outer
        # try/except (handle_acquire lines 111-124).
        pass

    try:
        try:
            await handle_acquire(state, reader)
        except Exception:
            pass  # handle_acquire re-raises after setting state.last_acquire
    finally:
        await reader.stop()

    assert state.last_acquire.status == "FAILED", (
        f"expected FAILED, got {state.last_acquire.status} "
        f"(fail_reason={state.last_acquire.fail_reason!r})"
    )
    assert state.last_acquire.ok_count == 0
    assert state.last_acquire.fail_count == 3
    assert set(state.last_acquire.failed_bpm_names) == {
        "FAKE:BPM1", "FAKE:BPM2", "FAKE:BPM3",
    }
    assert state.acquire_in_flight is False
```

- [ ] **Step 2: Run the test**

```bash
source .venv/bin/activate && pytest tests/integration/test_acquire_all_fail.py -v --tb=short
```

Expected: PASS. The handler's outer try/except (`handle_acquire` lines 111-124) sets `status=FAILED` and lists all prefixes in `failed_bpm_names` when an exception propagates out of the read path.

If the test fails because `reader.start()` raises and is then caught but `handle_acquire` doesn't see the right state, inspect what `BpmReader.read_all` returns when `_started=False` — the handler may need to encounter a different exception type to land in the FAILED branch. Adjust the test or report DONE_WITH_CONCERNS with the actual behavior.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_acquire_all_fail.py
git commit -m "test(integration): M3 — all-BPMs-offline scenario marks status FAILED

Test parametrizes fake_bpm_ioc with every prefix in offline_prefixes.
Asserts handle_acquire ends with status=FAILED, ok_count=0,
fail_count=3, and all three prefixes in failed_bpm_names. Exercises
the _classify(ok=0, fail=N) → FAILED branch and the handler's outer
try/except path that sets last_acquire.fail_reason.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §11 M3."
```

---

## Task 6: Concurrent CA acquire integration test

**Files:**
- Create: `tests/integration/test_acquire_concurrent_ca.py`

**Why:** Closes the "409 / CA alarm" half of the M3 DoD for the CA transport. REST's 409 is already covered by `test_acquire_via_rest.py::test_post_acquire_concurrent_returns_409`; this test does the symmetric check via CA.

**Design:** Construct `AppState` with `acquire_in_flight=True` from the start (same trick the REST 409 test uses). Spin up `PyTxTIOC` and a CA client. `caput` to `CMD:ACQUIRE` must raise (not return success). The exact exception type depends on caproto; the test asserts that *some* exception propagates — the implementer pins the specific type on first run.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_acquire_concurrent_ca.py`:

```python
"""Integration: M3 — CA caput to CMD:ACQUIRE while in-flight raises (CA-side 409).

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §11 M3.
REST equivalent: tests/integration/test_acquire_via_rest.py::
test_post_acquire_concurrent_returns_409.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest
from caproto.asyncio.client import Context as ClientContext

from pytxt.ioc.server import PyTxTIOC
from pytxt.state.app_state import AppState


async def _disconnect_quietly(client):
    if client is None:
        return
    try:
        await asyncio.wait_for(client.disconnect(), timeout=2.0)
    except (asyncio.TimeoutError, Exception):
        pass


@pytest.mark.asyncio
async def test_concurrent_ca_acquire_raises(test_pv_prefix):
    """With acquire_in_flight=True at entry, a caput to CMD:ACQUIRE must fail."""
    # State starts already in-flight, so the first caput attempt triggers
    # AcquisitionInFlightError. No need to overlap two real acquires.
    state = AppState(
        version="m3-test",
        bpm_prefixes=["FAKE:BPM1"],
        acquire_in_flight=True,
    )
    reader = AsyncMock()  # never called: in-flight guard fires first

    ioc = PyTxTIOC(
        prefix=test_pv_prefix,
        host="127.0.0.1", port=0, repeater_port=0,
        state=state, reader=reader,
    )
    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    client: ClientContext | None = None
    try:
        client = ClientContext()
        cmd_pv, = await client.get_pvs(test_pv_prefix + "CMD:ACQUIRE")

        # The exact exception type from caproto on a putter-raised error
        # varies by version. We assert *some* exception propagates rather
        # than pinning the class — what matters for the spec is that the
        # CA client sees the write as failed, which a successful return
        # would mask.
        with pytest.raises(Exception):
            await cmd_pv.write(1)

        # And the in-flight flag must still be True (the failed put did
        # not flip state — handle_acquire never even ran).
        assert state.acquire_in_flight is True
    finally:
        await _disconnect_quietly(client)
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
```

- [ ] **Step 2: Run the test to verify the Task-3 putter change is observable end-to-end**

```bash
source .venv/bin/activate && pytest tests/integration/test_acquire_concurrent_ca.py -v --tb=short
```

Expected: PASS. The putter from Task 3 re-raises; caproto encodes the failure; `pv.write(1)` raises on the client side.

If the test fails because `pv.write(1)` returns normally (no exception), Task 3's putter change didn't fully propagate to the CA client. Verify the putter no longer has the `except AcquisitionInFlightError: pass` block.

- [ ] **Step 3: Pin the actual exception class (post-pass refinement)**

After the test passes, replace `pytest.raises(Exception)` with the actual class observed during the failing-then-passing run. Run pytest with `-s` and add a brief `try: await cmd_pv.write(1)` `except Exception as exc: print(type(exc).__name__, exc); raise` temporarily to print the type, then update the test to use that specific class. This makes the test more useful as a regression guard — `pytest.raises(Exception)` would pass even if some unrelated failure replaced the in-flight error.

Re-run after pinning:

```bash
source .venv/bin/activate && pytest tests/integration/test_acquire_concurrent_ca.py -v --tb=short
```

Expected: PASS with the specific exception class.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_acquire_concurrent_ca.py
git commit -m "test(integration): M3 — caput CMD:ACQUIRE while in-flight raises (CA-side concurrency rejection)

Closes the CA-side half of the M3 DoD: spinning up PyTxTIOC with
state.acquire_in_flight=True at entry, a CA client's caput to
CMD:ACQUIRE propagates an exception on .write() rather than silently
succeeding. The state's acquire_in_flight stays True (the put never
reached handle_acquire).

REST counterpart already lives in tests/integration/test_acquire_via_rest.py::
test_post_acquire_concurrent_returns_409. Together they prove the
symmetric '409 / CA alarm' behavior the spec calls for.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §11 M3."
```

---

## Task 7: Decision log + roadmap closeout

**Files:**
- Modify: `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` (append entry)
- Modify: `PyTxT-roadmap.html` (M3 → ✓ done; M4 → "now"; refresh stats + recent activity)

**Why:** Closes the milestone per the project's documented conventions ([[workflow-decision-logs]] memory: every spec gets a paired decision log; [[feedback-roadmap-freshness]] memory: keep the roadmap fresh proactively after milestones).

- [ ] **Step 1: Append decision-log entry**

Append to `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` (after the existing `[m2-3-render-polish]` entry, with a blank line separating):

````markdown
## 2026-05-22 — M3 failure handling closed: fixture fault injection + CA putter symmetry

**Context:** M3 per spec §11 M3 ("M3 detailed design (locked 2026-05-22)"). The actual failure-handling code shipped in M1: per-PV `asyncio.wait_for` in `BpmReader._read_one`, `handle_acquire._classify` for OK/PARTIAL/FAILED, `try/finally` clearing `acquire_in_flight`, and `LAST_ACQUIRE_*` PVs all wired. M3's job was (a) test coverage and (b) closing the one outlier where the CA putter didn't surface the in-flight error.

**Implementation summary:**

1. `tests/fixtures/fake_bpm_ioc.py` gained an `offline_prefixes` dict-key form: those prefixes appear in `fixture.prefixes` (so `BpmReader` is configured to look for them) but are not built into the IOC's `pvdb`. `BpmReader._read_one` returns `None` for them via the "channels is None" early return.
2. Same fixture gained `slow_prefixes`: those prefixes get a custom PVGroup whose `c0/c1/c3/armed` getters `await asyncio.sleep(_SLOW_DELAY_S_DEFAULT=3.0)`. Reader resolves the PVs normally; the per-read `wait_for(timeout=2.0)` times out. Different `BpmReader._read_one` code branch from offline; same observable outcome.
3. `pytxt/ioc/pvs.py::cmd_acquire` putter was reduced from "catch + swallow AcquisitionInFlightError" to "re-raise" (~3 fewer lines + docstring update). caproto encodes the failure as a CA write error, symmetric to REST's 409. `STATE:ACQUIRE_IN_FLIGHT` continues to publish 1 for observers.
4. 5 integration tests + 1 unit test pinned all the failure paths: partial-fail via offline, partial-fail via timeout, state-PV publication on partial fail, all-fail via offline, concurrent CA acquire raises, putter re-raise unit-level.

**Decisions worth recording:**

1. **Construct-time-only fault injection.** Rejected runtime mutation (`fake_ioc.bpm_offline(name)` mid-test). Caproto doesn't gracefully handle a connected channel suddenly disappearing, and explicit setup-time topology is easier to reason about than mid-test state changes. If a future M-something needs to model "BPM goes offline during a session," it'll be its own milestone.
2. **`slow_prefixes` default delay = 3.0 s, not configurable per-prefix.** Single global delay above the production `per_pv_timeout_s=2.0` covers every test scenario currently anticipated. If a future test needs per-prefix delays (e.g. timeout-boundary testing), extend the parameter to a `dict[str, float]` then. YAGNI for now.
3. **Re-raise rather than alarm on STATE:ACQUIRE_IN_FLIGHT for concurrent CA acquire.** Symmetry with REST 409 is more important than EPICS-native alarm aesthetics: any client that wrote to `CMD:ACQUIRE` cares whether their write took effect. Alarms are for observers; this is a writer concern.
4. **Concurrent test uses `state.acquire_in_flight=True` at entry rather than overlapping two real acquires.** Same idiom as the REST test (`test_post_acquire_concurrent_returns_409`). The behavior under test is "putter raises when in-flight is set," not "two concurrent puts race." Avoids timing flakiness.
5. **Concurrent CA test asserts `pytest.raises(Exception)` (broad), then pinned the specific class.** First run printed the actual caproto exception type; subsequent runs use that class. Broader-first → narrower keeps the failing-test phase diagnostic.

**Tests:** 5 new integration tests in `tests/integration/test_acquire_partial_fail.py` (3), `tests/integration/test_acquire_all_fail.py` (1), `tests/integration/test_acquire_concurrent_ca.py` (1), and 1 new unit test in `tests/unit/test_cmd_acquire_putter.py`. The slow-prefix tests add ~3 s wall time each (intentional — exercising the real `wait_for` timeout). Plus the fixture-extension tests in `tests/integration/test_fake_bpm_ioc.py`. **Full suite expected to be ~110 tests, with ~10 s of additional wall time from M3.**

**Spec relationship:** M3 closes spec §11 M3 and its DoD lines ("simulated timeout produces NaN gap in plot + correct fail count in state PV; concurrent ACQUIRE returns 409 cleanly").

**Forward impact:**
- Phase 2 has just one milestone left: M4 (Raw REST `/result/bpm/raw`, UI polish, Playwright e2e).
- The fault-injection fixture is now reusable for any future "what if a BPM is unreachable?" test in any later phase.
- The `cmd_acquire` putter is now in symmetric error-surfacing parity with REST. Future commands (if added) should follow the same pattern: handler raises → putter re-raises → CA client sees a failed write.

Tag: `[m3-failure-handling]`.
````

- [ ] **Step 2: Refresh the roadmap**

In `PyTxT-roadmap.html`, edit anchors below. Use `grep -n` to locate each exact line first, then apply Edit.

1. **`Last updated:`** line — bump to today's date.

2. **Hero `<h2>`** — find:
   ```
       <h2>Phase 2 · Read path (M1 ✓ · M2 ✓ · M3 next)</h2>
   ```
   Replace with:
   ```
       <h2>Phase 2 · Read path (M1 ✓ · M2 ✓ · M3 ✓ · M4 next)</h2>
   ```

3. **Hero `<p>`** — replace the existing M3-next-leaning copy with a closeout-focused one (after "Next: M3 failure-handling test coverage" or wherever the "Next:" sentence currently ends). The intent: state that M3 closed with X new tests, the one production-code change (putter), and that M4 (raw REST + UI polish + e2e) is the final phase-2 milestone. Match the prose style of the M2 closeout paragraph.

4. **Hero progress** — title `"M1 + M2 done; M3 next"` → `"M1, M2, M3 done; M4 next"`; width 50% → 65%; progress-text `"M1 ✓ · M2 ✓ · M3 next · M4 queued"` → `"M1 ✓ · M2 ✓ · M3 ✓ · M4 next"`.

5. **`Tests passing` stat** — `103 / 103` → the actual final count after M3 (~110 once you confirm with `pytest --collect-only -q | tail -3`).

6. **`tests/` package card** — bump `Unit (12 files)` to actual count after Tasks 3, and `integration (12 files)` to count after Tasks 4, 5, 6 (likely 13 unit + 15 integration). Bump `<N> passing` to match.

7. **Milestones list — M3 line** — flip from `Queued` badge to `✓ Validated` and rewrite the meta to mirror the M2 close-out style (sub-milestones + key decisions).

8. **M3 milestone card** — same `now` → `done` flip with meta rewrite.

9. **M4 milestone card** — flip from `Queued` badge to `Now`.

10. **"Immediate — Kirk" `<ol>`** — replace the M3-kickoff item with an M4-kickoff item (Raw REST `/result/bpm/raw` endpoint + frontend polish + Playwright e2e).

11. **"M2 — closed" `<ol>`** section — rename to **"M2 + M3 — closed"**, add an `M3 ✅` entry summarizing what landed (offline_prefixes / slow_prefixes fixture hooks; CA putter re-raise; 6 new tests; decision log `[m3-failure-handling]`).

12. **Recent activity** — prepend new entries for each Task-1-through-6 commit, in reverse-chronological order. Include the SHAs once they're known (run `git log --oneline 304444d..HEAD | head -10` to capture them).

- [ ] **Step 3: Confirm full suite is green**

```bash
source .venv/bin/activate && pytest -q 2>&1 | tail -5
```

Expected: all tests pass. Note the exact count for the roadmap edit above if you haven't already.

- [ ] **Step 4: Commit and push**

```bash
git add docs/superpowers/specs/2026-05-18-phase-2-decisions.md PyTxT-roadmap.html
git commit -m "docs(roadmap+log): M3 ✓ closed — failure-handling tests in place + CA putter symmetric

Decision-log entry [m3-failure-handling] captures the four design
decisions (construct-time-only fault injection; 3 s default slow delay;
re-raise rather than alarm for CA concurrent rejection; pre-set
acquire_in_flight in the concurrent test rather than overlapping real
acquires) and the test inventory. Roadmap flipped: hero, progress bar,
test stats, milestone cards (M3 → done, M4 → now), 'Immediate — Kirk',
and recent activity all reflect M3 closed."
git push origin main
```

---

## Done criteria

M3 is closed when **all** of:

1. `pytest tests/integration/test_fake_bpm_ioc.py -v` — every test green, including the new `offline_prefixes` and `slow_prefixes` tests.
2. `pytest tests/unit/test_cmd_acquire_putter.py -v` — putter re-raise unit test green.
3. `pytest tests/integration/test_acquire_partial_fail.py tests/integration/test_acquire_all_fail.py tests/integration/test_acquire_concurrent_ca.py -v` — all 5 integration tests green.
4. `pytest -q` — full suite green.
5. `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` has the `[m3-failure-handling]` closeout entry.
6. `PyTxT-roadmap.html` reflects M3 ✓ in hero / milestone cards / "Immediate" / Recent activity.
7. `origin/main` is updated (push done).
