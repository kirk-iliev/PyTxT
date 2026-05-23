"""Integration: M3 all-fail scenarios — every BPM unreachable.

Two tests cover distinct code paths that both end in status=FAILED:

1. All-offline → BpmReader.start() raises on get_pvs timeout; handle_acquire's
   outer try/except (handle_acquire.py:111-124) sets FAILED. The classification
   logic (_classify) is NOT exercised here — the emergency catch-all is.

2. All-slow → BpmReader.start() succeeds (PVs resolve); read_all returns
   {prefix: None for all} via per-PV wait_for timeouts; handle_acquire reaches
   _classify(ok=0, fail=N) which returns FAILED. This is the classification path.

Both end states are identical from an observer's perspective, but the internal
paths are different and both deserve coverage so a regression in either is
caught.

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
async def test_all_bpms_failed_via_emergency_path(fake_bpm_ioc):
    """All offline → status=FAILED via the handler's emergency catch-all.

    reader.start() raises on get_pvs timeout; handle_acquire then calls
    read_all() which raises RuntimeError("BpmReader not started") because
    _started=False; the handler's outer try/except catches and writes
    status=FAILED with all prefixes in failed_bpm_names (handle_acquire.py
    lines 111-124) before re-raising. Does NOT exercise _classify — see the
    companion all-slow test below for that coverage.
    """
    state = AppState(version="m3-test", bpm_prefixes=fake_bpm_ioc.prefixes)
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=2.0)
    # reader.start() raises CaprotoTimeoutError when all PVs are absent.
    # We deliberately want the handler's outer try/except path next.
    try:
        await reader.start()
    except Exception:
        pass

    try:
        try:
            await handle_acquire(state, reader)
        except RuntimeError:
            # Expected: read_all raised "BpmReader not started" because the
            # earlier start() failed. The handler set FAILED state before
            # re-raising. Truly unexpected exceptions (e.g. a refactor bug
            # that produces TypeError) propagate so the test fails loudly.
            pass
    finally:
        await reader.stop()

    assert state.last_acquire.status == "FAILED", (
        f"expected FAILED, got {state.last_acquire.status} "
        f"(fail_reason={state.last_acquire.fail_reason!r})"
    )
    assert state.last_acquire.ok_count == 0, (
        f"ok_count={state.last_acquire.ok_count}"
    )
    assert state.last_acquire.fail_count == 3, (
        f"fail_count={state.last_acquire.fail_count}"
    )
    assert state.last_acquire.failed_bpm_names == [
        "FAKE:BPM1", "FAKE:BPM2", "FAKE:BPM3",
    ], f"failed_bpm_names={state.last_acquire.failed_bpm_names}"
    assert state.acquire_in_flight is False, (
        f"acquire_in_flight={state.acquire_in_flight}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fake_bpm_ioc",
    [{"n": 3, "slow": ["FAKE:BPM1", "FAKE:BPM2", "FAKE:BPM3"]}],
    indirect=True,
)
async def test_all_bpms_slow_marks_status_failed_via_classify(fake_bpm_ioc):
    """All slow → status=FAILED via _classify(ok=0, fail=N).

    PVs resolve normally on connect (slow only affects per-read), so
    reader.start() succeeds. handle_acquire calls read_all which times out
    on every per-PV wait_for (2.0 s reader timeout < 3.0 s getter sleep);
    read_all returns {prefix: None for all 3}. The handler reaches
    _classify(ok_count=0, fail_count=3) which returns FAILED — the
    classification path the all-offline test deliberately doesn't exercise.

    Wall time is ~2 s (dominated by the client-side wait_for; the server's
    serial dispatch of slow getters runs longer but the client doesn't
    wait for it).
    """
    state = AppState(version="m3-test", bpm_prefixes=fake_bpm_ioc.prefixes)
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=2.0)
    await reader.start()
    try:
        await handle_acquire(state, reader)
    finally:
        await reader.stop()

    assert state.last_acquire.status == "FAILED", (
        f"expected FAILED, got {state.last_acquire.status} "
        f"(fail_reason={state.last_acquire.fail_reason!r}, "
        f"failed={state.last_acquire.failed_bpm_names})"
    )
    assert state.last_acquire.ok_count == 0, (
        f"ok_count={state.last_acquire.ok_count}"
    )
    assert state.last_acquire.fail_count == 3, (
        f"fail_count={state.last_acquire.fail_count}"
    )
    assert state.last_acquire.failed_bpm_names == [
        "FAKE:BPM1", "FAKE:BPM2", "FAKE:BPM3",
    ], f"failed_bpm_names={state.last_acquire.failed_bpm_names}"
    assert state.acquire_in_flight is False, (
        f"acquire_in_flight={state.acquire_in_flight}"
    )
