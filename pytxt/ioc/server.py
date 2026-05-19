"""Soft IOC lifecycle wrapper.

Owns the PVGroup, binds AppState changes to PV writes, and exposes
`run()` for composition.py to await.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
from typing import Any, Optional

import numpy as np
from caproto.asyncio.server import Context

from pytxt.api.schemas.result import STATUS_STR_TO_INT, LastAcquireResult
from pytxt.ioc.pvs import PyTxTPVGroup
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)


# Simple (1:1) AppState field → PVGroup attribute name mappings.
_FIELD_TO_PV_ATTR: dict[str, str] = {
    "heartbeat": "heartbeat",
    "uptime_s_pushed": "uptime_s",
    "version": "version",
    "last_ping_at": "last_ping_at",
    "ping_count": "ping_count",
}


def _coerce_for_write(value: Any) -> Any:
    """Caproto only accepts int/float/str/list. Coerce bools and None."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    return value


def _pad_string_array(items: list[str], max_len: int) -> list[str]:
    """Pad a variable-length string array to max_len with empty strings."""
    padded = list(items[:max_len])
    padded.extend([""] * (max_len - len(padded)))
    return padded


def _pad_numeric_array(
    items: list[float] | np.ndarray, max_len: int, fill: float = 0.0
) -> list[float]:
    """Convert numpy array → list, padding to max_len. NaN passes through caproto float PVs."""
    arr = np.asarray(items, dtype=float).tolist()
    if len(arr) >= max_len:
        return arr[:max_len]
    arr.extend([fill] * (max_len - len(arr)))
    return arr


def _pad_int_array(
    items: list[int] | np.ndarray, max_len: int, fill: int = 0
) -> list[int]:
    arr = [int(v) for v in np.asarray(items).tolist()]
    if len(arr) >= max_len:
        return arr[:max_len]
    arr.extend([fill] * (max_len - len(arr)))
    return arr


class PyTxTIOC:
    """Wraps the caproto PVGroup with state binding and lifecycle."""

    def __init__(
        self,
        prefix: str,
        host: str,
        port: int,
        repeater_port: int,
        state: AppState,
        reader: Optional[object] = None,
    ):
        self.prefix = prefix
        self.host = host
        self.port = port
        self.repeater_port = repeater_port
        self.state = state
        self.pvgroup = PyTxTPVGroup(prefix=prefix, state=state, reader=reader)
        self._context: Optional[Context] = None
        self._running_event = asyncio.Event()
        self._bind_state_changes()

    def _bind_state_changes(self) -> None:
        """Subscribe to AppState changes; mirror to caproto PVs."""

        # --- Simple 1:1 mappings ---
        for field_name, pv_attr in _FIELD_TO_PV_ATTR.items():
            pv = getattr(self.pvgroup, pv_attr)

            async def _writer(value, _pv=pv, _name=field_name) -> None:
                value = _coerce_for_write(value)
                for attempt in (1, 2):
                    try:
                        await _pv.write(value)
                        return
                    except Exception:
                        if attempt == 1:
                            await asyncio.sleep(0.05)
                            continue
                        logger.exception(
                            "IOC write to PV for AppState field %r failed after retry", _name
                        )

            self.state.subscribe(field_name, _writer)

        # --- Phase 2: acquire_in_flight (bool → 0/1 int) ---
        in_flight_pv = self.pvgroup.acquire_in_flight

        async def _write_in_flight(value) -> None:
            try:
                await in_flight_pv.write(int(bool(value)))
            except Exception:
                logger.exception("IOC write to STATE:ACQUIRE_IN_FLIGHT failed")

        self.state.subscribe("acquire_in_flight", _write_in_flight)

        # --- Phase 2: last_acquire → 6 PVs + result waveforms ---
        # Decision: the closure is named _listener_last_acquire (not
        # _publish_last_acquire) to avoid shadowing the method of the same
        # name on this class. The method is called via self._publish_last_acquire
        # which is resolved at call time, but the name collision is confusing
        # and a lint tool would flag it. The rename is a cosmetic clarification
        # with no semantic difference.
        async def _listener_last_acquire(value: LastAcquireResult) -> None:
            await self._publish_last_acquire(value)

        self.state.subscribe("last_acquire", _listener_last_acquire)

        # --- Phase 2: bpm_prefixes → RESULT:BPM:NAMES (one-shot at startup) ---
        async def _publish_bpm_names(value: list[str]) -> None:
            try:
                await self.pvgroup.result_bpm_names.write(
                    _pad_string_array(value, max_len=128)
                )
            except Exception:
                logger.exception("IOC write to RESULT:BPM:NAMES failed")

        self.state.subscribe("bpm_prefixes", _publish_bpm_names)

    async def _publish_last_acquire(self, value: LastAcquireResult) -> None:
        """Write all PVs derived from a LastAcquireResult."""
        try:
            await self.pvgroup.last_acquire_status.write(
                STATUS_STR_TO_INT[value.status.value]
            )
            await self.pvgroup.last_acquire_ok_count.write(value.ok_count)
            await self.pvgroup.last_acquire_fail_count.write(value.fail_count)
            ts = value.timestamp.isoformat() if value.timestamp else ""
            await self.pvgroup.last_acquire_timestamp.write(ts)
            await self.pvgroup.last_acquire_fail_reason.write(value.fail_reason or "")
            await self.pvgroup.last_acquire_failed_bpm_names.write(
                _pad_string_array(value.failed_bpm_names, max_len=128)
            )
        except Exception:
            logger.exception("IOC publish of LastAcquireResult fields failed")

        # Result waveforms: derived from state.last_acquire_raws (the source
        # of truth for the raw data) plus the extracted first-turn arrays
        # which the handler has already pushed into state.last_acquire.
        # We pull from AppState directly to keep this publish atomic-ish.
        raws = self.state.last_acquire_raws
        prefixes = self.state.bpm_prefixes
        try:
            # The first-turn arrays were computed by extract_first_turn in the
            # handler; re-derive them here from raws + the published last_acquire
            # for index alignment. To avoid double work, we use the *already-
            # extracted* values via a small helper on AppState — but since they
            # aren't stored as arrays separately, we re-extract here. This is
            # microseconds for 120 entries. (Acknowledged minor design smell per
            # spec §6.7; intentional, do not refactor.)
            from pytxt.domain.first_turn_extract import extract_first_turn

            aligned: dict[str, object] = {p: raws.get(p) for p in prefixes}
            r = extract_first_turn(aligned)
            await self.pvgroup.result_bpm_x_first_turn.write(
                _pad_numeric_array(r.x_first_turn, max_len=128, fill=math.nan)
            )
            await self.pvgroup.result_bpm_y_first_turn.write(
                _pad_numeric_array(r.y_first_turn, max_len=128, fill=math.nan)
            )
            await self.pvgroup.result_bpm_sum_first_turn.write(
                _pad_numeric_array(r.sum_first_turn, max_len=128, fill=math.nan)
            )
            await self.pvgroup.result_bpm_injection_turn.write(
                _pad_int_array(r.injection_turn, max_len=128, fill=-1)
            )
        except Exception:
            logger.exception("IOC publish of RESULT:BPM:* waveforms failed")

    async def run(self) -> None:
        if self.port:
            os.environ["EPICS_CAS_SERVER_PORT"] = str(self.port)
            os.environ["EPICS_CA_SERVER_PORT"] = str(self.port)
        if self.host:
            os.environ["EPICS_CAS_INTF_ADDR_LIST"] = self.host
        if self.repeater_port:
            os.environ["EPICS_CA_REPEATER_PORT"] = str(self.repeater_port)

        running_event = self._running_event
        pvgroup = self.pvgroup
        state = self.state

        async def _startup_hook(async_lib) -> None:
            # Push phase-1 initial values
            for field_name, pv_attr in _FIELD_TO_PV_ATTR.items():
                value = getattr(state, field_name, None)
                if value is None:
                    value = "" if field_name == "last_ping_at" else 0
                pv = getattr(pvgroup, pv_attr)
                try:
                    await pv.write(value)
                except Exception:
                    logger.exception(
                        "IOC startup: failed to initialise PV for field %r", field_name
                    )

            # Push phase-2 initial values (NAMES is the most important — it's
            # static after startup; status bootstraps to NEVER=0).
            try:
                await pvgroup.result_bpm_names.write(
                    _pad_string_array(state.bpm_prefixes, max_len=128)
                )
                await pvgroup.acquire_in_flight.write(int(state.acquire_in_flight))
                await pvgroup.last_acquire_status.write(
                    STATUS_STR_TO_INT[state.last_acquire.status.value]
                )
            except Exception:
                logger.exception("IOC startup: failed to initialise phase-2 PVs")

            running_event.set()

        self._context = Context(self.pvgroup.pvdb)
        await self._context.run(log_pv_names=False, startup_hook=_startup_hook)

    async def wait_until_running(self, timeout: float = 5.0) -> None:
        await asyncio.wait_for(self._running_event.wait(), timeout=timeout)
