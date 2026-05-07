"""Integration: WS bridge subscribes to PVs in-process via CA and forwards updates."""
import asyncio
import json
import pytest
import uvicorn
from caproto.asyncio.client import Context as ClientContext
import websockets


async def _start_app(state, prefix):
    from pytxt.ioc.server import PyTxTIOC
    from pytxt.api.server import create_app
    from pytxt.config.settings import Settings

    ioc = PyTxTIOC(prefix=prefix, host="127.0.0.1", port=0, state=state)
    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    settings = Settings(pv_prefix=prefix)
    app = create_app(state=state, ioc=ioc, settings=settings)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    api_task = asyncio.create_task(server.serve())

    # Wait for uvicorn to bind a port
    while not server.started:
        await asyncio.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]

    return ioc, server, server_task, api_task, port


@pytest.mark.asyncio
async def test_ws_subscribe_receives_initial_value(test_pv_prefix):
    """On subscribe, the bridge sends the current value immediately."""
    from pytxt.state.app_state import AppState
    import time

    state = AppState(version="0.1.0", heartbeat=42, started_at=time.time())
    ioc, server, server_task, api_task, port = await _start_app(state, test_pv_prefix)

    try:
        url = f"ws://127.0.0.1:{port}/api/v1/pvs"
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps({
                "action": "subscribe",
                "pvs": [test_pv_prefix + "HEALTH:HEARTBEAT"],
            }))
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            data = json.loads(msg)
            assert data["pv"] == test_pv_prefix + "HEALTH:HEARTBEAT"
            assert data["value"] == 42
            assert "ts" in data
    finally:
        server.should_exit = True
        await api_task
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_ws_receives_updates_on_change(test_pv_prefix):
    """When AppState changes, subscribed WS clients receive broadcast updates."""
    from pytxt.state.app_state import AppState
    import time

    state = AppState(version="0.1.0", started_at=time.time())
    ioc, server, server_task, api_task, port = await _start_app(state, test_pv_prefix)

    try:
        url = f"ws://127.0.0.1:{port}/api/v1/pvs"
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps({
                "action": "subscribe",
                "pvs": [test_pv_prefix + "STATE:PING_COUNT"],
            }))
            initial = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert initial["value"] == 0

            await state.update(ping_count=7)

            update = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
            assert update["pv"] == test_pv_prefix + "STATE:PING_COUNT"
            assert update["value"] == 7
    finally:
        server.should_exit = True
        await api_task
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_ws_unknown_pv_returns_error(test_pv_prefix):
    from pytxt.state.app_state import AppState
    import time

    state = AppState(version="0.1.0", started_at=time.time())
    ioc, server, server_task, api_task, port = await _start_app(state, test_pv_prefix)

    try:
        url = f"ws://127.0.0.1:{port}/api/v1/pvs"
        async with websockets.connect(url) as ws:
            await ws.send(json.dumps({
                "action": "subscribe",
                "pvs": [test_pv_prefix + "STATE:DOES_NOT_EXIST"],
            }))
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
            assert "error" in msg
            assert msg["pv"] == test_pv_prefix + "STATE:DOES_NOT_EXIST"
    finally:
        server.should_exit = True
        await api_task
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
