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
