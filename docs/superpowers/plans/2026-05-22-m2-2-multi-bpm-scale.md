# M2-2 — Multi-BPM scale tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove that PyTxT's read path scales from 1 → 107 BPMs in under 3 s end-to-end, by adding parametric integration tests that exercise `BpmReader.read_all` and `handle_acquire` against the fake BPM IOC at production-realistic N.

**Architecture:** No production code changes are expected. The fake-IOC fixture (`tests/fixtures/fake_bpm_ioc.py`) is already parametric, and `BpmReader.read_all` already uses `asyncio.gather`. This milestone adds (a) a parametric scale test for `BpmReader` at N ∈ {10, 50, 107}, and (b) a full-pipeline ACQUIRE wall-time test through `handle_acquire` at N = 107. Both tests assert correctness and wall-clock budget per the phase-2 spec DoD line 2 (<3 s end-to-end). If the high-N case surfaces a real bug — most likely a connect-timeout shortage during `BpmReader.start()` resolving 428 channels through one caproto Context — fix it inline and log the decision.

**Tech Stack:** pytest, pytest-asyncio, caproto, numpy. Tests run under `make test` like the existing integration tier.

**Spec:** `docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md` §11 (M2), §12 DoD line 2.

**Decision log:** `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` — append entries during execution.

---

## File Structure

**New files:**
- `tests/integration/test_bpm_reader_scale.py` — parametric high-N reader perf test.
- `tests/integration/test_acquire_scale.py` — full-pipeline ACQUIRE wall-time test at N=107.

**Modified files:**
- `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` — append M2-2 entry.
- `PyTxT-roadmap.html` — flip M2-2 from "next" to "done" in milestone card, recent activity, what's next.

**No production code changes are planned.** If execution surfaces a real shortcoming in `pytxt/ca_client/bpm_reader.py` (e.g. shared timeout used for both PV resolution and per-read), add a discrete task to split it, with its own failing test → fix → commit cycle, and log it in the decision file.

---

## Task 1: Parametric BpmReader scale test (10, 50, 107)

**Files:**
- Create: `tests/integration/test_bpm_reader_scale.py`

**Why:** The existing `tests/integration/test_bpm_reader.py` covers N=1 and N=5. Production ships with N=107. We need direct evidence the parallel-`gather` path holds correctness *and* wall-time budget at the real scale, not just an extrapolation from N=5.

**Design:**
- Parametrize the fake-IOC fixture indirectly with `[10, 50, 107]`.
- For each N, start a `BpmReader`, call `read_all()` inside a `time.monotonic()` window, assert:
  1. `len(result) == N` and every value is a `RawBPM` (none are `None`).
  2. Waveform shapes are `(100000,)` for X/Y/sum.
  3. Wall-clock for `read_all()` (the read only — not start/stop) is `< 3.0` seconds.
- Use `per_pv_timeout_s=5.0` to give each individual PV read headroom; the *aggregate* assert is what enforces the 3 s SLA.
- The fixture's prefix generator already returns `["FAKE:BPM1", …, "FAKE:BPMN"]` for an int param — reuse, no fixture changes.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_bpm_reader_scale.py
"""Integration: BpmReader.read_all scales to production N (107 BPMs) under 3 s.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §12 DoD line 2.
"""
import time

import pytest

from pytxt.ca_client.bpm_reader import BpmReader
from pytxt.domain.types import RawBPM


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [10, 50, 107], indirect=True)
async def test_read_all_scales_under_3s(fake_bpm_ioc):
    """Parametric: N=10, 50, 107 — every BPM returns RawBPM; read_all() under 3 s."""
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=5.0)
    await reader.start()
    try:
        t0 = time.monotonic()
        result = await reader.read_all()
        elapsed = time.monotonic() - t0
    finally:
        await reader.stop()

    n = len(fake_bpm_ioc.prefixes)
    assert len(result) == n, f"expected {n} entries, got {len(result)}"
    none_prefixes = [p for p, r in result.items() if r is None]
    assert not none_prefixes, f"BPMs returned None: {none_prefixes[:5]}"
    for prefix, raw in result.items():
        assert isinstance(raw, RawBPM), f"{prefix} returned {type(raw).__name__}"
        assert raw.x_wf.shape == (100000,)
        assert raw.y_wf.shape == (100000,)
        assert raw.sum_wf.shape == (100000,)
    assert elapsed < 3.0, f"read_all of {n} BPMs took {elapsed:.2f}s, expected <3s"
```

- [ ] **Step 2: Run the test to verify it passes (or surface a real issue)**

Run:
```bash
pytest tests/integration/test_bpm_reader_scale.py -v --tb=short
```

Expected outcomes:
- **All three params pass.** The wall-time line will print as part of test output if you add `-s`; useful for spotting regressions later. Proceed to Step 3.
- **N=107 hangs or times out on `reader.start()`.** This means `get_pvs` resolving 428 channels exceeded `per_pv_timeout_s=5.0`. Real bug — investigate `pytxt/ca_client/bpm_reader.py:53` (the `get_pvs` call), consider splitting `per_pv_timeout_s` into a separate `connect_timeout_s`. Add a Task 1.5 with a TDD cycle for the split, log the decision in `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` under tag `[bpm-reader-split-timeouts]`, then re-run.
- **N=107 succeeds but wall time exceeds 3 s.** Investigate before relaxing the bound. Likely causes: fixture startup (`await asyncio.sleep(0.2)` inside the fixture) bleeding into measurement, GC pauses, or genuine caproto serial-dispatch under load. Log findings either way.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_bpm_reader_scale.py
git commit -m "test(ca_client): M2-2 — BpmReader.read_all scales to 107 BPMs under 3s

Parametric integration test at N=10, 50, 107 against the existing
fake_bpm_ioc fixture. Asserts every BPM returns a valid RawBPM and
that read_all() completes within the phase-2 DoD budget (<3 s).

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md
§12 DoD line 2."
```

---

## Task 2: End-to-end ACQUIRE wall-time test at N = 107

**Files:**
- Create: `tests/integration/test_acquire_scale.py`

**Why:** Task 1 only times `BpmReader.read_all`. The phase-2 DoD is "ACQUIRE completes in <3 s end-to-end" — that includes `handle_acquire`'s full work: read, domain `detect_injection_turn` + `extract_first_turn` per BPM, AppState update, listener dispatch. Need a separate test that proves the *handler* budget, not just the reader budget. The handler runs domain code in 107 separate calls — pure numpy is fast, but worth pinning.

**Design:**
- Use the real `BpmReader` against `fake_bpm_ioc` parametrized to N=107.
- Build a real `AppState` with `bpm_prefixes=fake_bpm_ioc.prefixes` (so handler sees the same list reader is bound to).
- Call `handle_acquire(state, reader)` directly (no FastAPI / HTTP overhead — that's M4 territory). Time the entire call.
- Assert: `state.last_acquire.status == "OK"`, `ok_count == 107`, `fail_count == 0`, and wall time `< 3.0` seconds.
- Do not use `unittest.mock` anywhere — this is the first end-to-end integration test of the real read+domain pipeline at production N.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_acquire_scale.py
"""Integration: handle_acquire end-to-end at N=107 — full pipeline under 3 s.

Real BpmReader, real AppState, real domain code, real fake IOC. The only
fake is the upstream BPM IOC (synthesized waveforms with a deterministic
injection step at sample 1370).

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md
§12 DoD line 2.
"""
import time

import pytest

from pytxt.ca_client.bpm_reader import BpmReader
from pytxt.handlers.acquire import handle_acquire
from pytxt.state.app_state import AppState


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [107], indirect=True)
async def test_handle_acquire_end_to_end_under_3s(fake_bpm_ioc):
    """Real reader + real domain + real state. 107 BPMs. <3 s wall."""
    state = AppState(version="m2-2-test", bpm_prefixes=fake_bpm_ioc.prefixes)
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=5.0)
    await reader.start()
    try:
        t0 = time.monotonic()
        await handle_acquire(state, reader)
        elapsed = time.monotonic() - t0
    finally:
        await reader.stop()

    assert state.last_acquire.status == "OK", (
        f"expected OK, got {state.last_acquire.status} "
        f"(fail_reason={state.last_acquire.fail_reason!r}, "
        f"failed={state.last_acquire.failed_bpm_names[:5]})"
    )
    assert state.last_acquire.ok_count == 107
    assert state.last_acquire.fail_count == 0
    assert state.acquire_in_flight is False
    assert elapsed < 3.0, f"handle_acquire of 107 BPMs took {elapsed:.2f}s, expected <3s"
```

- [ ] **Step 2: Run the test**

Run:
```bash
pytest tests/integration/test_acquire_scale.py -v --tb=short -s
```

Expected outcomes:
- **Pass.** Proceed to Step 3.
- **`state.last_acquire.status != "OK"`.** Read the printed `fail_reason` and `failed` list from the assertion message. If specific BPMs failed in `handle_acquire` but not in Task 1's reader test, the fault is in the handler's per-BPM error path or AppState ordering — investigate `pytxt/handlers/acquire.py`, log findings under decision tag `[m2-2-handle-acquire-failure-NN]`, fix, re-run.
- **Wall time > 3 s but reader succeeded fast.** The domain code (`detect_injection_turn`, `extract_first_turn`) is taking real time on 107 BPMs. Profile with `python -m cProfile` or add timing prints. Pure-numpy paths should be sub-second total at this N; if they're not, that's a real finding worth a decision-log entry before deciding whether to relax the bound or optimize.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_acquire_scale.py
git commit -m "test(integration): M2-2 — handle_acquire end-to-end at N=107 under 3s

Real BpmReader + real AppState + real domain code against fake_bpm_ioc
with 107 synthesized BPMs. Asserts last_acquire.status=OK, ok_count=107,
fail_count=0, and wall time <3s — the phase-2 DoD budget.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md
§12 DoD line 2."
```

---

## Task 3: Decision-log entry + roadmap refresh

**Files:**
- Modify: `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` (append entry)
- Modify: `PyTxT-roadmap.html` (flip M2-2 status from "next" to "done")

**Why:** Memory `[[workflow-decision-logs]]` requires a per-spec decision-log entry for every implementation milestone — for context, deviations, and surprises future-readers need to find without re-reading the diff. Memory `[[feedback-roadmap-freshness]]` says keep the roadmap fresh after milestones.

- [ ] **Step 1: Append decision-log entry**

Open `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` and append (after the last existing entry, following the template at the top of the file):

````markdown
## 2026-05-22 — M2-2 multi-BPM scale tests: N=107 ACQUIRE under 3 s confirmed

**Context:** M2-2 task per spec §11 / DoD §12 line 2: prove the read path scales from 1 → 107 BPMs in <3 s end-to-end. Spec didn't prescribe exactly *which* tests; it just specified the integration tier needed multi-BPM coverage and the DoD wall-time bound.

**Decisions:**

1. **Two test files, two scopes.** `tests/integration/test_bpm_reader_scale.py` exercises just `BpmReader.read_all` parametrically at N ∈ {10, 50, 107} — isolates the CA-client transport. `tests/integration/test_acquire_scale.py` exercises the full `handle_acquire` pipeline (real reader + real domain + real state) at N=107 — isolates the handler+domain budget. Both pin the <3 s bound. Two files because the failure modes are distinct: a reader-only failure indicates caproto/network, a handler-only failure indicates domain or state-update overhead.

2. **`per_pv_timeout_s=5.0` in tests, not the default 2.0.** Test reads run against an in-process fake IOC where `caproto`'s first-PV resolution can take ~1 s even on localhost; the *aggregate* `<3 s` assertion is what enforces the SLA, while the per-PV timeout just has to be large enough to avoid spurious flakes on a loaded CI host. Production code keeps the 2 s default.

3. **No production code changes.** The fake-IOC fixture was already parametric (M1 work). `BpmReader.read_all` already uses `asyncio.gather` (M1 work). M2-2 is a pure proof-of-scale milestone; the architecture was load-bearing for the spec's N=107 claim from the start, and these tests are the evidence.

**Observed wall times (filled in after `pytest -s`):**

- N=10 `read_all`: __.__ s
- N=50 `read_all`: __.__ s
- N=107 `read_all`: __.__ s
- N=107 full `handle_acquire`: __.__ s (= read_all + domain + state update)

Copy these directly from the `-s` test output. Keep two decimals.

**Surprises during execution:** *Add this subsection only if something unexpected happened. Each surprise gets its own bullet with what was expected, what happened, and what we did about it. If execution was clean, omit this subsection entirely — the absence of surprises is itself the finding.*

**Spec relationship:** No spec change. M2-2 closes spec §11 M2 ("Tests: ca_client integration tests with multi-BPM fake IOC fixture") and provides the evidence for DoD §12 line 2 wall-time claim.

**Forward impact:**
- M2-3 (frontend polyline) can be developed without re-litigating backend scale.
- M3 (failure handling) will *reuse* `fake_bpm_ioc`'s `bpm_offline`/`bpm_timeout` hooks (already designed into the fixture per its dataclass docstring) plus these scale tests as a regression base. The 3 s wall-time bound should stay green in M3 (no per-BPM serial fallbacks slipped in).

Tag: `[m2-2-scale-tests]`.
````

(If execution surfaces concrete surprises — e.g. real wall times, a connect-timeout split — replace "(Fill in any surprises…)" with the actual data before committing.)

- [ ] **Step 2: Update PyTxT-roadmap.html**

In `PyTxT-roadmap.html`, make these edits:

1. Bump `Last updated:` line to today's date.
2. Hero `<h2>`: change `Phase 2 · Read path (M1 ✓ · M2-1 ✓ · M2-2 next)` to `Phase 2 · Read path (M1 ✓ · M2-1 ✓ · M2-2 ✓ · M2-3 next)`.
3. Hero `<p>`: append a sentence like "M2-2 closed 2026-05-22 — `BpmReader.read_all` and `handle_acquire` both proven at N=107 in <3 s end-to-end via two new integration tests." and update the `Next:` clause to point at M2-3 (frontend polyline).
4. Hero progress bar: width 35% → 42% (rough 3/7 of phase-2 sub-tasks).
5. Milestones list line for `<strong>M2</strong>`: append `; M2-2 ✓ scale tests at N=107 <3 s 2026-05-22`.
6. M2 milestone card (`<div class="ms now">` block around line 769): update the `ms-meta` to read "M2-1 ✓ + M2-2 ✓ (scale tests at N=107 under 3 s 2026-05-22). M2-3 next: frontend polyline render across 107 datapoints."
7. "What's next" / "Immediate — Kirk" `<ol>`: replace the M2-2-kickoff item with "Kick off M2-3 (frontend polyline)."
8. "What's next" / "M2 — code" `<ol>`: prepend `M2-2 ✅` to the M2-2 line, mirroring the M2-1 format.
9. "Recent activity" section: add two new top entries — one for each commit landed in Tasks 1 and 2 (hashes filled in after `git log -2 --oneline`).

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-05-18-phase-2-decisions.md PyTxT-roadmap.html
git commit -m "docs(roadmap+log): M2-2 closed — multi-BPM scale tests pass at N=107

Decision-log entry [m2-2-scale-tests] documents test-file split, timeout
choices, and any execution surprises. Roadmap flipped to show M2-2 ✓
and M2-3 (frontend polyline) as the next immediate task."
```

- [ ] **Step 4: Push**

```bash
git push origin main
```

---

## Done criteria

M2-2 is closed when **all** of:

1. `pytest tests/integration/test_bpm_reader_scale.py -v` is green at N=10, N=50, N=107.
2. `pytest tests/integration/test_acquire_scale.py -v` is green at N=107.
3. Both files appear in `git log` with explanatory commit messages.
4. `docs/superpowers/specs/2026-05-18-phase-2-decisions.md` has the `[m2-2-scale-tests]` entry, filled with the *actual* execution data (not the "fill in" placeholder).
5. `PyTxT-roadmap.html` shows M2-2 ✓ in hero, milestone card, "What's next," and Recent activity.
6. `make test` (full suite) is green — 79 pre-existing + 2 new = 81 (count may differ if either new test parametrizes into multiple cases — currently 3 params for Task 1 = 3 test cases, 1 for Task 2 = 1 case, so 79 + 4 = 83).
7. `origin/main` updated.
