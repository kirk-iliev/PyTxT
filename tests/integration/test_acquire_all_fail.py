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
