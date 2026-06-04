"""Persistent-connection CA client for HCM/VCM corrector setpoints (Phase 4).

Holds caproto async PV objects for every corrector's setpoint channel (the
'AC' Setpoint record, e.g. ``SR01C___HCM1___AC00``) and offers read/write by
*family index* — the position in the committed catalog, which the response
matrix and `CMD:STEP_CM` both use to address correctors.

This adapter does only the raw CA I/O (caget/caput). The compare-and-set and
clamp *decisions* live in the pure `pytxt.domain.correctors` layer; the handler
orchestrates read -> plan -> write.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from caproto.asyncio.client import Context as ClientContext

from pytxt.config.corrector_channels import CorrectorChannel

logger = logging.getLogger(__name__)


class CorrectorWriter:
    """Persistent CA client for corrector setpoints. Open at startup."""

    def __init__(
        self,
        hcm_channels: list[CorrectorChannel],
        vcm_channels: list[CorrectorChannel],
        per_pv_timeout_s: float = 2.0,
    ):
        self._channels: dict[str, list[CorrectorChannel]] = {
            "HCM": list(hcm_channels),
            "VCM": list(vcm_channels),
        }
        self._timeout = per_pv_timeout_s
        self._ctx: Optional[ClientContext] = None
        # family -> list of PV objects, index-aligned with self._channels[family]
        self._pvs: dict[str, list[object]] = {}
        self._started = False

    def channels(self, family: str) -> list[CorrectorChannel]:
        """Ordered CorrectorChannel list for a family ('HCM' or 'VCM')."""
        self._require_family(family)
        return self._channels[family]

    def _require_family(self, family: str) -> None:
        if family not in self._channels:
            raise ValueError(f"unknown corrector family {family!r} (expected HCM or VCM)")

    async def start(self) -> None:
        """Open the caproto Context and resolve every corrector setpoint PV."""
        self._ctx = ClientContext()
        for family, chans in self._channels.items():
            names = [c.name for c in chans]
            pvs = await self._ctx.get_pvs(*names, timeout=self._timeout)
            self._pvs[family] = list(pvs)
        self._started = True

    async def stop(self) -> None:
        """Close the caproto Context. Idempotent."""
        self._started = False
        if self._ctx is not None:
            try:
                await self._ctx.disconnect()
            except Exception:
                logger.exception("CorrectorWriter.stop: error closing caproto context")
            self._ctx = None
            self._pvs = {}

    def _resolve(self, family: str, indices: list[int]) -> list[object]:
        if not self._started:
            raise RuntimeError("CorrectorWriter.start() must complete before read/write")
        self._require_family(family)
        pvs = self._pvs[family]
        out = []
        for i in indices:
            if i < 0 or i >= len(pvs):
                raise IndexError(
                    f"{family} index {i} out of range (0..{len(pvs) - 1})"
                )
            out.append(pvs[i])
        return out

    async def read_setpoints(self, family: str, indices: list[int]) -> list[float]:
        """Read present setpoints (amps) for the given family indices, in order."""
        pvs = self._resolve(family, indices)
        results = await asyncio.gather(
            *(asyncio.wait_for(pv.read(), timeout=self._timeout) for pv in pvs)
        )
        return [float(r.data[0]) for r in results]

    async def write_setpoints(
        self, family: str, indices: list[int], values_a: list[float]
    ) -> None:
        """Write absolute setpoints (amps) for the given family indices.

        Writes run in parallel; any per-channel failure propagates so a partial
        corrector apply fails loudly rather than silently.
        """
        if len(indices) != len(values_a):
            raise ValueError(
                f"indices/values length mismatch ({len(indices)}/{len(values_a)})"
            )
        pvs = self._resolve(family, indices)
        await asyncio.gather(
            *(
                asyncio.wait_for(pv.write(v), timeout=self._timeout)
                for pv, v in zip(pvs, values_a)
            )
        )
