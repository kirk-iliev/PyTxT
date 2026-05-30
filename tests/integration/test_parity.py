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
    counts. Phase 3 (M2): reference status + last_diff summary. Raw waveform
    dicts, timestamps, and diff arrays are normalized because they differ by
    identity / across runs.
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
        # phase 3 (M2): reference status + diff summary. Project last_diff to a
        # stable shape — raw dx/dy arrays differ by identity and break ==.
        "reference_loaded": state.reference_loaded,
        "reference_source": state.reference_source.value,
        "reference_name": state.reference_name,
        "reference_loaded_at": "<set>" if state.reference_loaded_at else None,
        "last_diff": (
            None if state.last_diff is None
            else {"n_valid": state.last_diff.summary.n_valid}
        ),
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


async def _do_via_ca(prefix: str, cmd: str, pre_acquire: bool = False) -> None:
    client = ClientContext()
    try:
        if pre_acquire:
            # Commands like PROMOTE_REF need a prior successful acquire to
            # source from. Trigger one on this same state before the command.
            acq_pv, = await client.get_pvs(prefix + "CMD:ACQUIRE")
            await acq_pv.write(1)
            await asyncio.sleep(0.2)
        pv, = await client.get_pvs(prefix + cmd)
        await pv.write(1)
        await asyncio.sleep(0.2)   # let listener fan-out complete
    finally:
        # Disconnect so background command-queue tasks don't outlive the test
        # and spin against a dead event loop on the next parametrize round.
        try:
            await asyncio.wait_for(client.disconnect(), timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            pass


async def _do_via_rest(app, path: str, pre_acquire: bool = False) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        if pre_acquire:
            ra = await ac.post("/api/v1/cmd/acquire", json={})
            assert ra.status_code == 200, f"REST pre-acquire failed: {ra.status_code} {ra.text}"
        r = await ac.post(path, json={})
        assert r.status_code == 200, f"REST {path} failed: {r.status_code} {r.text}"


# Commands that act on a live acquisition (e.g. PROMOTE_REF) need BPM prefixes
# and a reader on both arms so the pre-acquire can run.
_NEEDS_BPMS = {"acquire", "promote_ref", "clear_ref"}


def _make_state(command_name: str):
    from pytxt.state.app_state import AppState
    bpm = ["A"] if command_name in _NEEDS_BPMS else []
    return AppState(version="0.1.0", started_at=time.time(), bpm_prefixes=bpm)


def _make_reader(command_name: str):
    if command_name not in _NEEDS_BPMS:
        return None
    reader = AsyncMock()
    reader.read_all.return_value = {"A": _fake_raw("A")}
    return reader


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command_name, ca_pv_suffix, rest_path, requires_acquire",
    [
        ("ping", "CMD:PING", "/api/v1/cmd/ping", False),
        ("acquire", "CMD:ACQUIRE", "/api/v1/cmd/acquire", False),
        ("promote_ref", "CMD:PROMOTE_REF", "/api/v1/cmd/promote_ref", True),
        ("clear_ref", "CMD:CLEAR_REF", "/api/v1/cmd/clear_ref", False),
        # phase 3+: ("load_ref", "CMD:LOAD_REF", "/api/v1/cmd/load-ref", False),
    ],
)
async def test_parity_ca_vs_rest(test_pv_prefix, command_name, ca_pv_suffix, rest_path, requires_acquire):
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
        await _do_via_ca(test_pv_prefix, ca_pv_suffix, pre_acquire=requires_acquire)
        after_ca = _public_state(state_ca)
    finally:
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    diff_ca = {k: (before_ca[k], after_ca[k]) for k in after_ca if before_ca[k] != after_ca[k]}

    # --- Path 2: REST POST ---
    state_rest = _make_state(command_name)
    reader_rest = _make_reader(command_name)
    app = create_app(state=state_rest)
    if reader_rest is not None:
        app.state.bpm_reader = reader_rest

    before_rest = _public_state(state_rest)
    await _do_via_rest(app, rest_path, pre_acquire=requires_acquire)
    after_rest = _public_state(state_rest)
    diff_rest = {k: (before_rest[k], after_rest[k]) for k in after_rest if before_rest[k] != after_rest[k]}

    assert diff_ca == diff_rest, (
        f"Command {command_name!r} produced different effects via CA vs REST.\n"
        f"  CA diff:   {diff_ca}\n"
        f"  REST diff: {diff_rest}\n"
        "The agentic-parity invariant has been violated."
    )
