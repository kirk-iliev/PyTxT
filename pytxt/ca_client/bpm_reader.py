"""Persistent-connection CA client for reading BPM TBT waveforms.

Holds caproto async PV objects for every configured BPM's four channels
({prefix}:wfr:TBT:{c0,c1,c3,armed}). On ACQUIRE, dispatches all reads in
parallel via asyncio.gather with a per-PV timeout. Missing or
malformed responses produce None in the result dict (the caller — typically
the acquire handler — turns these into NaN sentinels via the domain layer).

Phase 4 adds the **active** acquisition path (`setup`/`arm`/`wait_until_ready`)
ported from `SCexp_ALS_{setupBPMs,armBPMs,readoutBPMs}.m`: program the TBT
trigger to latch on timing event 48, arm, wait for the BPMs to disarm after a
shot, then `read_all()`. The control PVs are resolved lazily on first active
use, so purely passive callers (and the existing read-only tests) never touch
them.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from caproto.asyncio.client import Context as ClientContext

from pytxt.domain.types import RawBPM

logger = logging.getLogger(__name__)

# Libera BPM electronics: c0=X position, c1=Y position, c3=sum signal.
# c2 exists in the Libera channel space but is not populated by the ALS
# BPM IOC firmware for TBT acquisition (matches MATLAB SCexp_ALS_readoutBPMs.m
# which also reads only c0/c1/c3). `armed` is the per-BPM acquisition status.
_CHANNELS = ("c0", "c1", "c3", "armed")

# Active-acquisition control PVs (Phase 4), name suffix appended to {prefix}:.
# Values/names ported verbatim from SCexp_ALS_setupBPMs.m / armBPMs.m.
_CTRL_PV_SUFFIXES = {
    "arm": "wfr:TBT:arm",                # write 0 to clear, 1 to arm
    "trigger_mask": "wfr:TBT:triggerMask",
    "acq_count": "wfr:TBT:acqCount",     # number of samples to capture
    "event48trig": "EVR:event48trig",    # latch the TBT trigger on timing event 48
}

# bin2dec('01000000') in the legacy: select timing event 48 (BR Extraction
# Kicker — the BPMs latch on this) for both the TBT trigger mask and the EVR.
_EVENT48_BITMASK = 0b01000000
_DEFAULT_ACQ_COUNT = 100_000


class AcquisitionTimeoutError(TimeoutError):
    """Raised when BPMs do not disarm (wfr:TBT:armed -> 0) within the timeout."""


class BpmReader:
    """Persistent CA client. Open at startup; read_all() on each ACQUIRE."""

    def __init__(self, prefixes: list[str], per_pv_timeout_s: float = 2.0):
        self._prefixes = list(prefixes)
        self._timeout = per_pv_timeout_s
        self._ctx: Optional[ClientContext] = None
        # prefix → dict of {"c0": PV, "c1": PV, "c3": PV, "armed": PV}
        self._pvs: dict[str, dict[str, object]] = {}
        # prefix → dict of control PVs (resolved lazily on first active use)
        self._ctrl_pvs: dict[str, dict[str, object]] = {}
        self._ctrl_resolved: bool = False
        self._started: bool = False

    async def start(self) -> None:
        """Open caproto Context and fetch PV objects for all configured BPMs.

        Sets `self._started = True` only after PV resolution completes. If
        get_pvs raises (or any other startup failure), `_started` stays False
        and `read_all()` will raise rather than silently return all-None.
        """
        self._ctx = ClientContext()
        all_names: list[str] = []
        for prefix in self._prefixes:
            for ch in _CHANNELS:
                all_names.append(f"{prefix}:wfr:TBT:{ch}")
        pvs = await self._ctx.get_pvs(*all_names, timeout=self._timeout)
        # Re-shape flat list back into per-BPM channel dict
        for i, prefix in enumerate(self._prefixes):
            base = i * len(_CHANNELS)
            self._pvs[prefix] = {ch: pvs[base + j] for j, ch in enumerate(_CHANNELS)}
        self._started = True

    async def stop(self) -> None:
        """Close the caproto Context. Idempotent."""
        self._started = False
        self._ctrl_resolved = False
        if self._ctx is not None:
            try:
                await self._ctx.disconnect()
            except Exception:
                logger.exception("BpmReader.stop: error closing caproto context")
            self._ctx = None
            self._pvs = {}
            self._ctrl_pvs = {}

    # --- active acquisition (Phase 4) --------------------------------------

    async def _ensure_control_pvs(self) -> None:
        """Resolve the per-BPM control PVs (arm/triggerMask/acqCount/event48trig).

        Lazy + idempotent: called by setup()/arm() so passive callers never
        resolve these. Requires start() to have run (shares the same Context).
        """
        if not self._started or self._ctx is None:
            raise RuntimeError("BpmReader.start() must complete before active acquisition")
        if self._ctrl_resolved:
            return
        names: list[str] = []
        for prefix in self._prefixes:
            for suffix in _CTRL_PV_SUFFIXES.values():
                names.append(f"{prefix}:{suffix}")
        pvs = await self._ctx.get_pvs(*names, timeout=self._timeout)
        n = len(_CTRL_PV_SUFFIXES)
        keys = list(_CTRL_PV_SUFFIXES.keys())
        for i, prefix in enumerate(self._prefixes):
            base = i * n
            self._ctrl_pvs[prefix] = {keys[j]: pvs[base + j] for j in range(n)}
        self._ctrl_resolved = True

    async def setup(
        self,
        *,
        acq_count: int = _DEFAULT_ACQ_COUNT,
        trigger_mask: int = _EVENT48_BITMASK,
        event48_trig: int = _EVENT48_BITMASK,
    ) -> None:
        """Program every BPM's TBT trigger (legacy SCexp_ALS_setupBPMs.m).

        Per BPM: clear arm, set the TBT trigger mask + EVR event-48 trigger so
        the buffer latches on timing event 48, and set the sample count. Writes
        run in parallel; any per-BPM failure propagates (active commanding must
        fail loudly, not silently half-configure).
        """
        await self._ensure_control_pvs()

        async def _setup_one(prefix: str) -> None:
            ctrl = self._ctrl_pvs[prefix]
            await asyncio.wait_for(ctrl["arm"].write(0), timeout=self._timeout)
            await asyncio.wait_for(ctrl["trigger_mask"].write(trigger_mask), timeout=self._timeout)
            await asyncio.wait_for(ctrl["event48trig"].write(event48_trig), timeout=self._timeout)
            await asyncio.wait_for(ctrl["acq_count"].write(acq_count), timeout=self._timeout)

        await asyncio.gather(*(_setup_one(p) for p in self._prefixes))

    async def arm(self) -> None:
        """Arm every BPM's TBT buffer (legacy SCexp_ALS_armBPMs.m): write
        wfr:TBT:arm = 1. Run setup() first."""
        await self._ensure_control_pvs()

        async def _arm_one(prefix: str) -> None:
            await asyncio.wait_for(
                self._ctrl_pvs[prefix]["arm"].write(1), timeout=self._timeout
            )

        await asyncio.gather(*(_arm_one(p) for p in self._prefixes))

    async def wait_until_ready(
        self,
        timeout_s: float = 10.0,
        poll_interval_s: float = 0.2,
    ) -> None:
        """Block until every BPM disarms (wfr:TBT:armed -> 0) after a shot.

        Ports the legacy `while getpv(...:armed); pause(0.2); end` poll loop.
        Polls all BPMs each round; returns once none remain armed. Raises
        AcquisitionTimeoutError if any BPM is still armed after timeout_s.
        """
        if not self._started:
            raise RuntimeError("BpmReader.start() must complete before wait_until_ready()")
        deadline = time.monotonic() + timeout_s
        pending = list(self._prefixes)
        while pending:
            still_armed: list[str] = []
            results = await asyncio.gather(
                *(self._read_armed(p) for p in pending), return_exceptions=True
            )
            for prefix, armed in zip(pending, results):
                # On read error, treat as still-armed and retry until the deadline.
                if isinstance(armed, Exception) or armed != 0:
                    still_armed.append(prefix)
            pending = still_armed
            if not pending:
                return
            if time.monotonic() >= deadline:
                raise AcquisitionTimeoutError(
                    f"{len(pending)} BPM(s) still armed after {timeout_s}s: "
                    f"{pending[:5]}{'...' if len(pending) > 5 else ''}"
                )
            await asyncio.sleep(poll_interval_s)

    async def _read_armed(self, prefix: str) -> int:
        """Read one BPM's wfr:TBT:armed scalar (0 = data ready)."""
        pv = self._pvs[prefix]["armed"]
        resp = await asyncio.wait_for(pv.read(), timeout=self._timeout)
        return int(resp.data[0])

    async def read_all(self) -> dict[str, RawBPM | None]:
        """Read every configured BPM in parallel; return aligned dict."""
        if not self._started:
            raise RuntimeError(
                "BpmReader.read_all() called before start() completed successfully"
            )

        async def _read_one(prefix: str) -> tuple[str, RawBPM | None]:
            channels = self._pvs.get(prefix)
            if channels is None:
                return prefix, None
            try:
                c0_r, c1_r, c3_r, armed_r = await asyncio.gather(
                    asyncio.wait_for(channels["c0"].read(), timeout=self._timeout),
                    asyncio.wait_for(channels["c1"].read(), timeout=self._timeout),
                    asyncio.wait_for(channels["c3"].read(), timeout=self._timeout),
                    asyncio.wait_for(channels["armed"].read(), timeout=self._timeout),
                )
            except Exception as exc:
                logger.debug("BPM %s read failed: %s: %s", prefix, type(exc).__name__, exc)
                return prefix, None

            try:
                x_wf = np.asarray(c0_r.data, dtype=np.int32)
                y_wf = np.asarray(c1_r.data, dtype=np.int32)
                sum_wf = np.asarray(c3_r.data, dtype=np.int32)
                armed = int(armed_r.data[0])
            except Exception:
                logger.exception("BPM %s data conversion failed", prefix)
                return prefix, None

            if x_wf.shape != (100000,) or y_wf.shape != (100000,) or sum_wf.shape != (100000,):
                logger.warning(
                    "BPM %s wrong waveform shape: x=%s y=%s sum=%s",
                    prefix, x_wf.shape, y_wf.shape, sum_wf.shape,
                )
                return prefix, None

            return prefix, RawBPM(
                prefix=prefix,
                x_wf=x_wf,
                y_wf=y_wf,
                sum_wf=sum_wf,
                armed=armed,
                read_timestamp=datetime.now(timezone.utc),
            )

        pairs = await asyncio.gather(*(_read_one(p) for p in self._prefixes))
        # Preserve prefix order
        return {p: r for p, r in pairs}
