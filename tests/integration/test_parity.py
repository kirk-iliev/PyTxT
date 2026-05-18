"""The agentic-parity invariant test.

For every command that exists in PyTxT, issuing it via CA write and via
REST POST must produce bit-identical state effects. This test is the
load-bearing canary for agentic parity. **It must remain green forever.**

Future commands (CMD:LOAD_REF, CMD:CALC_RM, CMD:APPLY_STEP, ...) are
added as parametrize cases on `command`.
"""
import asyncio
import time

import pytest
from caproto.asyncio.client import Context as ClientContext
from httpx import AsyncClient, ASGITransport


def _public_state(state) -> dict:
    """Explicit projection of AppState fields the parity test compares.

    Deliberately not dataclasses.asdict: that recurses into _listeners
    (bound async closures registered by the IOC), relying on deepcopy
    treating functions as atomic — a CPython implementation detail, not
    a documented contract. Listing fields explicitly makes the contract
    obvious and forces a conscious update when AppState grows in phase 2+.

    last_ping_at is normalized to '<set>'/None because the timestamp
    differs by milliseconds between the CA and REST paths; only its
    presence is parity-relevant. started_at is wall-clock and excluded.
    """
    return {
        "heartbeat": state.heartbeat,
        "ping_count": state.ping_count,
        "last_ping_at": "<set>" if state.last_ping_at else None,
        "version": state.version,
        "uptime_s_pushed": state.uptime_s_pushed,
    }


async def _do_via_ca(prefix: str, cmd: str) -> None:
    client = ClientContext()
    pv, = await client.get_pvs(prefix + cmd)
    await pv.write(1)
    await asyncio.sleep(0.1)


async def _do_via_rest(app, path: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(path, json={})
        assert r.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command_name, ca_pv_suffix, rest_path",
    [
        ("ping", "CMD:PING", "/api/v1/cmd/ping"),
        # phase 2+: ("readout", "CMD:READOUT", "/api/v1/cmd/readout"),
        # phase 3+: ("load_ref", "CMD:LOAD_REF", "/api/v1/cmd/load-ref"),
        # ...
    ],
)
async def test_parity_ca_vs_rest(test_pv_prefix, command_name, ca_pv_suffix, rest_path):
    from pytxt.state.app_state import AppState
    from pytxt.ioc.server import PyTxTIOC
    from pytxt.api.server import create_app

    # --- Path 1: CA write ---
    state_ca = AppState(version="0.1.0", started_at=time.time())
    ioc_ca = PyTxTIOC(prefix=test_pv_prefix, host="127.0.0.1", port=0, repeater_port=0, state=state_ca)
    server_task = asyncio.create_task(ioc_ca.run())
    await ioc_ca.wait_until_running()
    try:
        before_ca = _public_state(state_ca)
        await _do_via_ca(test_pv_prefix, ca_pv_suffix)
        after_ca = _public_state(state_ca)
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    diff_ca = {k: (before_ca[k], after_ca[k]) for k in after_ca if before_ca[k] != after_ca[k]}

    # --- Path 2: REST POST ---
    state_rest = AppState(version="0.1.0", started_at=time.time())
    app = create_app(state=state_rest)
    before_rest = _public_state(state_rest)
    await _do_via_rest(app, rest_path)
    after_rest = _public_state(state_rest)
    diff_rest = {k: (before_rest[k], after_rest[k]) for k in after_rest if before_rest[k] != after_rest[k]}

    assert diff_ca == diff_rest, (
        f"Command {command_name!r} produced different effects via CA vs REST.\n"
        f"  CA diff:   {diff_ca}\n"
        f"  REST diff: {diff_rest}\n"
        "The agentic-parity invariant has been violated. The shared handler "
        "import in pytxt/handlers/ should make this impossible — investigate "
        "any duplicate logic in routes or PV putters."
    )
