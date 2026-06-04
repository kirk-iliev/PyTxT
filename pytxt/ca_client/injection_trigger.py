"""CA adapter for the de-boxed injection one-shot (Phase 4).

Wraps the timing-system PVs that `srinjectoneshot` pokes (all plain CA — no MML):
    TimInjReq                       DBF_LONG x7   the request waveform (the fire)
    EVG:E1:seqBusy                  DBF_DOUBLE    the gate (wait 1->0 before writing)
    B0215:EVR1-Out:UDC0:Delay-SP    DBF_LONG      extraction fine delay (counts)
    bucket:control:cmd              the precondition (1 = bucket loading / top-off active)

These are real machine PV names (not under the PyTxT prefix); in tests a fake IOC
serves them on the conftest-pinned ephemeral port. The adapter does raw CA only —
the request math is pure (`pytxt.domain.injection`) and the orchestration +
precondition policy live in the handler.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from caproto.asyncio.client import Context as ClientContext

logger = logging.getLogger(__name__)

PV_TIM_INJ_REQ = "TimInjReq"
PV_SEQ_BUSY = "EVG:E1:seqBusy"
PV_FINE_DELAY = "B0215:EVR1-Out:UDC0:Delay-SP"
PV_BUCKET_CONTROL = "bucket:control:cmd"


class SeqBusyTimeoutError(TimeoutError):
    """Raised when EVG:E1:seqBusy does not complete a 1->0 cycle in time."""


class InjectionTrigger:
    """Persistent CA client for the injection one-shot timing PVs."""

    def __init__(self, per_pv_timeout_s: float = 2.0):
        self._timeout = per_pv_timeout_s
        self._ctx: Optional[ClientContext] = None
        self._pvs: dict[str, object] = {}
        self._started = False

    async def start(self) -> None:
        self._ctx = ClientContext()
        names = [PV_TIM_INJ_REQ, PV_SEQ_BUSY, PV_FINE_DELAY, PV_BUCKET_CONTROL]
        pvs = await self._ctx.get_pvs(*names, timeout=self._timeout)
        self._pvs = dict(zip(names, pvs))
        self._started = True

    async def stop(self) -> None:
        self._started = False
        if self._ctx is not None:
            try:
                await self._ctx.disconnect()
            except Exception:
                logger.exception("InjectionTrigger.stop: error closing caproto context")
            self._ctx = None
            self._pvs = {}

    def _pv(self, name: str):
        if not self._started:
            raise RuntimeError("InjectionTrigger.start() must complete before use")
        return self._pvs[name]

    async def read_tim_inj_req(self) -> list[int]:
        resp = await asyncio.wait_for(self._pv(PV_TIM_INJ_REQ).read(), timeout=self._timeout)
        return [int(v) for v in resp.data]

    async def read_bucket_control(self) -> int:
        """Read the bucket-loading/top-off precondition (1 = active)."""
        resp = await asyncio.wait_for(self._pv(PV_BUCKET_CONTROL).read(), timeout=self._timeout)
        return int(resp.data[0])

    async def read_seq_busy(self) -> int:
        resp = await asyncio.wait_for(self._pv(PV_SEQ_BUSY).read(), timeout=self._timeout)
        return int(round(float(resp.data[0])))

    async def write_tim_inj_req(self, req: list[int]) -> None:
        await asyncio.wait_for(
            self._pv(PV_TIM_INJ_REQ).write(list(req)), timeout=self._timeout
        )

    async def write_fine_delay(self, counts: int) -> None:
        await asyncio.wait_for(
            self._pv(PV_FINE_DELAY).write(int(counts)), timeout=self._timeout
        )

    async def sync_seq_busy(self, timeout_s: float = 5.0, poll_s: float = 0.01) -> None:
        """Wait for a seqBusy 1->0 cycle (the timing-sequencer read window).

        Ports the legacy `while ~seqBusy; end; while seqBusy; end`. The handler
        treats a timeout here as non-fatal (the sync is a robustness nicety per
        ReadMe_TimingSystem.m), but the adapter reports it honestly.
        """
        deadline = time.monotonic() + timeout_s
        while await self.read_seq_busy() == 0:          # wait for rising edge
            if time.monotonic() >= deadline:
                raise SeqBusyTimeoutError("seqBusy never went high")
            await asyncio.sleep(poll_s)
        while await self.read_seq_busy() != 0:          # wait for falling edge
            if time.monotonic() >= deadline:
                raise SeqBusyTimeoutError("seqBusy never returned low")
            await asyncio.sleep(poll_s)
