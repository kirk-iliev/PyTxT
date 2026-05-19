"""Persistent-connection CA client for reading BPM TBT waveforms.

Holds caproto async PV objects for every configured BPM's four channels
({prefix}:wfr:TBT:{c0,c1,c3,armed}). On ACQUIRE, dispatches all reads in
parallel via asyncio.gather with a per-PV timeout. Missing or
malformed responses produce None in the result dict (the caller — typically
the acquire handler — turns these into NaN sentinels via the domain layer).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from caproto.asyncio.client import Context as ClientContext

from pytxt.domain.types import RawBPM

logger = logging.getLogger(__name__)

_CHANNELS = ("c0", "c1", "c3", "armed")


class BpmReader:
    """Persistent CA client. Open at startup; read_all() on each ACQUIRE."""

    def __init__(self, prefixes: list[str], per_pv_timeout_s: float = 2.0):
        self._prefixes = list(prefixes)
        self._timeout = per_pv_timeout_s
        self._ctx: Optional[ClientContext] = None
        # prefix → dict of {"c0": PV, "c1": PV, "c3": PV, "armed": PV}
        self._pvs: dict[str, dict[str, object]] = {}

    async def start(self) -> None:
        """Open caproto Context and fetch PV objects for all configured BPMs.

        Does NOT block on the first read — caproto resolves PV names lazily.
        We just create the PV objects; read failures show up at read_all time.
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

    async def stop(self) -> None:
        """Close the caproto Context. Idempotent."""
        if self._ctx is not None:
            try:
                await self._ctx.disconnect()
            except Exception:
                logger.exception("BpmReader.stop: error closing caproto context")
            self._ctx = None
            self._pvs = {}

    async def read_all(self) -> dict[str, RawBPM | None]:
        """Read every configured BPM in parallel; return aligned dict."""
        if self._ctx is None:
            raise RuntimeError("BpmReader.read_all() called before start()")

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
