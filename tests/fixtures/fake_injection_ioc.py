"""Caproto fake IOC serving the injection-trigger timing PVs for integration tests.

Serves, on the conftest-pinned ephemeral CA port, the real PV names the de-boxed
srinjectoneshot pokes:
    TimInjReq                       LONG x7   request waveform
    EVG:E1:seqBusy                  DOUBLE    gate (toggles 1 then 0 on reads)
    B0215:EVR1-Out:UDC0:Delay-SP    LONG      fine delay
    bucket:control:cmd              LONG      precondition (0/1)

seqBusy is served by a getter that returns 1 on its first read and 0 thereafter,
so InjectionTrigger.sync_seq_busy() observes a clean 1->0 cycle.
"""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

import pytest_asyncio
from caproto.asyncio.server import Context
from caproto.server import PVGroup, pvproperty


def _make_injection_group(bucket_control_init: int = 0) -> PVGroup:
    # seqBusy: closure counter so the first read is high (1), then low (0).
    state = {"reads": 0}

    async def seq_busy_read(group, instance):
        state["reads"] += 1
        await instance.write(1.0 if state["reads"] == 1 else 0.0)
        return instance.value

    class FakeInjection(PVGroup):
        tim_inj_req = pvproperty(
            value=[57, 4, 40, 0, 0, 0, 19133], dtype=int,
            name="TimInjReq", max_length=7,
        )
        seq_busy = pvproperty(
            seq_busy_read, value=0.0, dtype=float, name="EVG:E1:seqBusy",
        )
        fine_delay = pvproperty(value=0, dtype=int, name="B0215:EVR1-Out:UDC0:Delay-SP")
        bucket_control = pvproperty(
            value=bucket_control_init, dtype=int, name="bucket:control:cmd"
        )

    return FakeInjection(prefix="")


@dataclass
class FakeInjectionIoc:
    _context: Context
    _task: asyncio.Task


@pytest_asyncio.fixture
async def fake_injection_ioc(request) -> FakeInjectionIoc:
    """Serve the injection timing PVs. Param (optional dict): {"bucket_control": 0|1}."""
    param = request.param if hasattr(request, "param") else {}
    bucket_control = int(param.get("bucket_control", 0)) if isinstance(param, dict) else 0

    group = _make_injection_group(bucket_control_init=bucket_control)
    ctx = Context(group.pvdb)
    task = asyncio.create_task(ctx.run(log_pv_names=False))
    await asyncio.sleep(0.2)

    handle = FakeInjectionIoc(_context=ctx, _task=task)
    try:
        yield handle
    finally:
        for sock in list(getattr(ctx, "tcp_sockets", {}).values()):
            with contextlib.suppress(Exception):
                sock.close()
        for sock in list(getattr(ctx, "udp_socks", {}).values()):
            with contextlib.suppress(Exception):
                sock.close()
        for entry in list(getattr(ctx, "beacon_socks", {}).values()):
            sock = entry[1] if isinstance(entry, tuple) and len(entry) > 1 else entry
            with contextlib.suppress(Exception):
                sock.close()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=2.0)
