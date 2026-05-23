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

from pytxt.api.schemas.result import STATUS_STR_TO_INT
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
    [{"n": 5, "slow": ["FAKE:BPM5"]}],
    indirect=True,
)
async def test_acquire_partial_fail_via_timeout(fake_bpm_ioc):
    """One BPM is slow (>per_pv_timeout); ACQUIRE returns PARTIAL via wait_for path.

    The slow BPM is placed last in the prefix list (FAKE:BPM5) because the
    in-process caproto fake IOC runs on the same asyncio event loop as the
    client.  When a slow getter calls asyncio.sleep(3 s) it stalls the
    server's dispatch loop; CA reads that have already been dispatched to the
    server complete normally, while reads that arrive after the sleep starts
    will time out.  Placing the slow BPM last ensures the four fast BPMs get
    their CA read requests enqueued (and answered) before BPM5's getter
    begins sleeping, so only BPM5 times out at 2 s.
    """
    # Machine-enforced guard for the constraint above: if a maintainer ever
    # changes `n` without updating `slow` (or vice versa), this fires before
    # the slow read can produce timing-dependent results that mask the issue.
    assert fake_bpm_ioc.prefixes[-1] == "FAKE:BPM5", (
        "slow BPM must be last in the prefix list; see test docstring for "
        "the shared-event-loop constraint that requires this."
    )

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
    assert state.last_acquire.failed_bpm_names == ["FAKE:BPM5"]
    assert state.acquire_in_flight is False


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

    client: ClientContext | None = None
    server_task: asyncio.Task | None = None
    try:
        await reader.start()

        ioc = PyTxTIOC(
            prefix=test_pv_prefix,
            host="127.0.0.1", port=0, repeater_port=0,
            state=state, reader=reader,
        )
        server_task = asyncio.create_task(ioc.run())
        await ioc.wait_until_running()

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

        expected_status = STATUS_STR_TO_INT["PARTIAL"]
        assert int(status.data[0]) == expected_status, (
            f"expected {expected_status} (PARTIAL), got {int(status.data[0])}"
        )
        assert int(ok.data[0]) == 4
        assert int(fail.data[0]) == 1
    finally:
        await _disconnect_quietly(client)
        await reader.stop()
        if server_task is not None:
            server_task.cancel()
            try:
                await asyncio.wait_for(server_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
