"""Integration: a CA write to CMD:PING triggers handle_ping and updates state PVs."""
import asyncio
import pytest
from caproto.asyncio.client import Context as ClientContext


async def _disconnect_quietly(client: ClientContext | None) -> None:
    if client is None:
        return
    try:
        await asyncio.wait_for(client.disconnect(), timeout=2.0)
    except (asyncio.TimeoutError, Exception):
        pass


@pytest.mark.asyncio
async def test_ca_caput_to_cmd_ping_increments_count(test_pv_prefix):
    from pytxt.state.app_state import AppState
    from pytxt.ioc.server import PyTxTIOC
    import time

    state = AppState(version="0.1.0", started_at=time.time())
    ioc = PyTxTIOC(prefix=test_pv_prefix, host="127.0.0.1", port=0, repeater_port=0, state=state)

    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    client: ClientContext | None = None
    try:
        client = ClientContext()
        cmd_pv, count_pv, last_at_pv = await client.get_pvs(
            test_pv_prefix + "CMD:PING",
            test_pv_prefix + "STATE:PING_COUNT",
            test_pv_prefix + "STATE:LAST_PING_AT",
        )

        before = await count_pv.read()
        assert before.data[0] == 0

        await cmd_pv.write(1)
        await asyncio.sleep(0.1)  # let listener fan-out complete

        after_count = await count_pv.read()
        after_last = await last_at_pv.read()
        assert after_count.data[0] == 1
        # last_ping_at was previously empty; should now be a non-empty ISO timestamp
        last_str = after_last.data[0].decode() if isinstance(after_last.data[0], bytes) else after_last.data[0]
        assert last_str
        assert "T" in last_str  # ISO format check
    finally:
        await _disconnect_quietly(client)
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


@pytest.mark.asyncio
async def test_ca_caput_value_is_ignored(test_pv_prefix):
    """The written value to CMD:PING is ignored — it's a trigger, not a setpoint."""
    from pytxt.state.app_state import AppState
    from pytxt.ioc.server import PyTxTIOC
    import time

    state = AppState(version="0.1.0", started_at=time.time())
    ioc = PyTxTIOC(prefix=test_pv_prefix, host="127.0.0.1", port=0, repeater_port=0, state=state)

    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    client: ClientContext | None = None
    try:
        client = ClientContext()
        cmd_pv, count_pv = await client.get_pvs(
            test_pv_prefix + "CMD:PING",
            test_pv_prefix + "STATE:PING_COUNT",
        )

        for written in (1, 42, 99, 0):
            await cmd_pv.write(written)
            await asyncio.sleep(0.05)

        result = await count_pv.read()
        assert result.data[0] == 4  # incremented once per write regardless of value
    finally:
        await _disconnect_quietly(client)
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
