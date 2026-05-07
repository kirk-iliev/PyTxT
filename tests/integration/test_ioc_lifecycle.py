"""Integration: IOC starts, publishes initial PV values, accepts CA reads/writes."""
import asyncio
import pytest
from caproto.asyncio.client import Context as ClientContext


@pytest.mark.asyncio
async def test_ioc_starts_and_publishes_initial_values(test_pv_prefix):
    """The IOC's PVs are reachable via CA and have expected initial values."""
    from pytxt.state.app_state import AppState
    from pytxt.ioc.server import PyTxTIOC
    import time

    state = AppState(version="0.1.0", started_at=time.time())
    ioc = PyTxTIOC(prefix=test_pv_prefix, host="127.0.0.1", port=0, state=state)

    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    try:
        client = ClientContext()
        version_pv, heartbeat_pv = await client.get_pvs(
            test_pv_prefix + "STATE:VERSION",
            test_pv_prefix + "HEALTH:HEARTBEAT",
        )
        v = await version_pv.read()
        h = await heartbeat_pv.read()
        assert v.data[0] == "0.1.0" or v.data[0].decode() == "0.1.0"
        assert h.data[0] == 0
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_appstate_change_propagates_to_pv(test_pv_prefix):
    """When AppState.heartbeat changes, the HEALTH:HEARTBEAT PV reflects it."""
    from pytxt.state.app_state import AppState
    from pytxt.ioc.server import PyTxTIOC
    import time

    state = AppState(version="0.1.0", started_at=time.time())
    ioc = PyTxTIOC(prefix=test_pv_prefix, host="127.0.0.1", port=0, state=state)

    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    try:
        client = ClientContext()
        heartbeat_pv, = await client.get_pvs(test_pv_prefix + "HEALTH:HEARTBEAT")

        await state.update(heartbeat=42)
        # Allow the listener-driven write to propagate
        await asyncio.sleep(0.1)

        result = await heartbeat_pv.read()
        assert result.data[0] == 42
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
