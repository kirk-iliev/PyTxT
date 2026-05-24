"""Integration: M3 — CA caput to CMD:ACQUIRE while in-flight raises (CA-side 409).

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §11 M3.
REST equivalent: tests/integration/test_acquire_via_rest.py::
test_post_acquire_concurrent_returns_409.
"""
import asyncio
from unittest.mock import AsyncMock

import pytest
from caproto import CaprotoTimeoutError
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

        # When the putter re-raises AcquisitionInFlightError, caproto's
        # server does not send a write-ACK back to the client. The client
        # therefore times out waiting for the response, raising
        # CaprotoTimeoutError (caproto._utils.CaprotoTimeoutError, exposed
        # at top-level caproto). Pinned on first run with caproto 0.8.x.
        with pytest.raises(CaprotoTimeoutError):
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
