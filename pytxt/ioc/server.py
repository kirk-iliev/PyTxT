"""Soft IOC lifecycle wrapper.

Owns the PVGroup, binds AppState changes to PV writes, and exposes
`run()` for composition.py to await.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
from pathlib import Path
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
    """Convert numpy/list of ints → list, padding to max_len with `fill`."""
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
        reference_dir: Optional[Path] = None,
        corrector_writer: Optional[object] = None,
        injection_trigger: Optional[object] = None,
    ):
        self.prefix = prefix
        self.host = host
        self.port = port
        self.repeater_port = repeater_port
        self.state = state
        self.pvgroup = PyTxTPVGroup(
            prefix=prefix, state=state, reader=reader, reference_dir=reference_dir,
            corrector_writer=corrector_writer, injection_trigger=injection_trigger,
        )
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

        # --- Phase 3 (M2): two-trigger reference publication ---
        # reference_loaded drives the STATE:REF_* status bundle (fires on
        # promote False→True and clear True→False); last_diff drives the diff
        # waveforms (fires every acquire while a ref stays loaded, and on clear
        # → None → NaN-fill). Keeping them on separate triggers means the diff
        # arrays refresh in lockstep with the first-turn arrays each acquire
        # while the status bundle only republishes on load/clear.
        async def _listener_reference_status(value) -> None:
            await self._publish_reference_status()

        self.state.subscribe("reference_loaded", _listener_reference_status)

        async def _listener_diff_arrays(value) -> None:
            await self._publish_diff_arrays(value)

        self.state.subscribe("last_diff", _listener_diff_arrays)

        # --- Phase 4: corrector-step state ---
        cm_in_flight_pv = self.pvgroup.cm_step_in_flight

        async def _write_cm_in_flight(value) -> None:
            try:
                await cm_in_flight_pv.write(int(bool(value)))
            except Exception:
                logger.exception("IOC write to STATE:CM_STEP_IN_FLIGHT failed")

        self.state.subscribe("cm_step_in_flight", _write_cm_in_flight)

        async def _listener_last_cm_step(value) -> None:
            await self._publish_last_cm_step(value)

        self.state.subscribe("last_cm_step", _listener_last_cm_step)

        inj_in_flight_pv = self.pvgroup.inject_in_flight

        async def _write_inj_in_flight(value) -> None:
            try:
                await inj_in_flight_pv.write(int(bool(value)))
            except Exception:
                logger.exception("IOC write to STATE:INJ_IN_FLIGHT failed")

        self.state.subscribe("inject_in_flight", _write_inj_in_flight)

        async def _listener_last_inject(value) -> None:
            await self._publish_last_inject(value)

        self.state.subscribe("last_inject", _listener_last_inject)

    async def _publish_last_acquire(self, value: LastAcquireResult) -> None:
        """Write all PVs derived from a LastAcquireResult.

        All writes are wrapped in a single try/except so a failure in any write
        aborts the rest, preventing partial-publish drift. The handler will
        update last_acquire again on the next ACQUIRE and the publisher will
        retry from scratch.
        """
        try:
            await self.pvgroup.last_acquire_status.write(STATUS_STR_TO_INT[value.status.value])
            await self.pvgroup.last_acquire_ok_count.write(value.ok_count)
            await self.pvgroup.last_acquire_fail_count.write(value.fail_count)
            ts = value.timestamp.isoformat() if value.timestamp else ""
            await self.pvgroup.last_acquire_timestamp.write(ts)
            await self.pvgroup.last_acquire_fail_reason.write(value.fail_reason or "")
            await self.pvgroup.last_acquire_failed_bpm_names.write(
                _pad_string_array(value.failed_bpm_names, max_len=128)
            )

            # Result waveforms: re-derive from state.last_acquire_raws + bpm_prefixes
            # for index alignment. extract_first_turn is microseconds for ~120 entries
            # — cheaper than a separate AppState field to hold the arrays.
            from pytxt.domain.first_turn_extract import extract_first_turn

            raws = self.state.last_acquire_raws
            prefixes = self.state.bpm_prefixes
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
            logger.exception("IOC publish of LastAcquireResult / RESULT:BPM:* failed")

    async def _publish_reference_status(self) -> None:
        """Write the STATE:REF_* status bundle from current AppState.

        Single try/except wraps all writes (matching _publish_last_acquire) so a
        failure in any write aborts the rest, preventing partial-publish drift.
        Triggered by the reference_loaded listener (promote / clear).
        """
        try:
            await self.pvgroup.ref_loaded.write(int(bool(self.state.reference_loaded)))
            await self.pvgroup.ref_name.write(self.state.reference_name or "")
            loaded_at = self.state.reference_loaded_at
            await self.pvgroup.ref_loaded_at.write(
                loaded_at.isoformat() if loaded_at else ""
            )
            await self.pvgroup.ref_source.write(self.state.reference_source.value)
        except Exception:
            logger.exception("IOC publish of STATE:REF_* failed")

    async def _publish_last_cm_step(self, value: Any) -> None:
        """Write the STATE:CM_LAST_* bundle from a LastCMStepResult.

        Single try/except wraps all writes (matching _publish_last_acquire) so a
        partial publish can't drift; the next STEP_CM republishes from scratch.
        """
        try:
            await self.pvgroup.cm_last_status.write(value.status)
            await self.pvgroup.cm_last_family.write(value.family or "")
            await self.pvgroup.cm_last_n_applied.write(int(value.n_applied))
            await self.pvgroup.cm_last_n_clamped.write(int(value.n_clamped))
            ts = value.timestamp.isoformat() if value.timestamp else ""
            await self.pvgroup.cm_last_timestamp.write(ts)
        except Exception:
            logger.exception("IOC publish of STATE:CM_LAST_* failed")

    async def _publish_last_inject(self, value: Any) -> None:
        """Write the STATE:INJ_LAST_* bundle from a LastInjectResult."""
        try:
            await self.pvgroup.inj_last_status.write(value.status)
            await self.pvgroup.inj_last_bucket.write(int(value.bucket))
            await self.pvgroup.inj_last_mode.write(int(value.mode))
            await self.pvgroup.inj_last_inhibit.write(int(value.inhibit))
            await self.pvgroup.inj_last_seq_num.write(int(value.seq_num))
            ts = value.timestamp.isoformat() if value.timestamp else ""
            await self.pvgroup.inj_last_timestamp.write(ts)
        except Exception:
            logger.exception("IOC publish of STATE:INJ_LAST_* failed")

    async def _publish_diff_arrays(self, value: Any) -> None:
        """Write RESULT:BPM:{X,Y}_DIFF_FIRST_TURN from a DiffResult (or None).

        None → NaN-filled arrays (no ref loaded / cleared); otherwise pad the
        DiffResult dx/dy to _BPM_MAX. Triggered by the last_diff listener, so
        the diff arrays refresh on every acquire in lockstep with the first-turn
        arrays. Single try/except matches _publish_last_acquire.
        """
        try:
            if value is None:
                await self.pvgroup.result_bpm_x_diff_first_turn.write(
                    _pad_numeric_array([], max_len=128, fill=math.nan)
                )
                await self.pvgroup.result_bpm_y_diff_first_turn.write(
                    _pad_numeric_array([], max_len=128, fill=math.nan)
                )
            else:
                await self.pvgroup.result_bpm_x_diff_first_turn.write(
                    _pad_numeric_array(value.dx, max_len=128, fill=math.nan)
                )
                await self.pvgroup.result_bpm_y_diff_first_turn.write(
                    _pad_numeric_array(value.dy, max_len=128, fill=math.nan)
                )
        except Exception:
            logger.exception("IOC publish of RESULT:BPM:*_DIFF_FIRST_TURN failed")

    async def run(self) -> None:
        # caproto's server reads EPICS_CA_SERVER_PORT (no S) at Context.__init__
        # to decide both (a) where to bind TCP and (b) where to listen for
        # search broadcasts. We must set it to our IOC port *before* Context()
        # is constructed below — but we restore it immediately after, so the
        # in-process CA client (BpmReader) inherits the operator's normal
        # ring-reachable value (typically unset → caproto default 5064).
        # EPICS_CAS_SERVER_PORT is also set for parity with EPICS-base servers.
        saved_ca_server_port = os.environ.get("EPICS_CA_SERVER_PORT")
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

            # Push phase-3 (M2) reference defaults: empty status bundle +
            # NaN-filled diff arrays, so the PVs read sane values before the
            # first promote.
            try:
                await pvgroup.ref_loaded.write(0)
                await pvgroup.ref_name.write("")
                await pvgroup.ref_loaded_at.write("")
                await pvgroup.ref_source.write("")
                await pvgroup.result_bpm_x_diff_first_turn.write(
                    _pad_numeric_array([], max_len=128, fill=math.nan)
                )
                await pvgroup.result_bpm_y_diff_first_turn.write(
                    _pad_numeric_array([], max_len=128, fill=math.nan)
                )
            except Exception:
                logger.exception("IOC startup: failed to initialise phase-3 REF PVs")

            # Push phase-4 corrector-step + injection defaults (NEVER / empty).
            try:
                await pvgroup.cm_step_in_flight.write(int(state.cm_step_in_flight))
                await pvgroup.cm_last_status.write(state.last_cm_step.status)
                await pvgroup.inject_in_flight.write(int(state.inject_in_flight))
                await pvgroup.inj_last_status.write(state.last_inject.status)
            except Exception:
                logger.exception("IOC startup: failed to initialise phase-4 CM/INJ PVs")

            running_event.set()

        self._context = Context(self.pvgroup.pvdb)
        # Server has now captured `EPICS_CA_SERVER_PORT` into its own state
        # (`self.ca_server_port` on caproto's Context). Restore the env var so
        # the embedded CA client used by BpmReader sees the original value and
        # can search the ring on the standard port.
        if self.port:
            if saved_ca_server_port is None:
                os.environ.pop("EPICS_CA_SERVER_PORT", None)
            else:
                os.environ["EPICS_CA_SERVER_PORT"] = saved_ca_server_port
        try:
            await self._context.run(log_pv_names=False, startup_hook=_startup_hook)
        except asyncio.CancelledError:
            # caproto's own CancelledError handler awaits `tasks.cancel_all()`,
            # which can hang on multi-interface Linux hosts (e.g. appsdev2) when
            # broadcaster_receive_loop is blocked in a UDP recv that doesn't
            # honor cancellation. Force-close every socket the Context owns so
            # those blocked recvs unblock; then re-raise so the task is marked
            # cancelled.
            self._force_close_context_sockets()
            raise

    def _force_close_context_sockets(self) -> None:
        ctx = self._context
        if ctx is None:
            return
        for sock in list(getattr(ctx, "tcp_sockets", {}).values()):
            try:
                sock.close()
            except Exception:
                logger.debug("force-close: TCP sock.close() raised", exc_info=True)
        for sock in list(getattr(ctx, "udp_socks", {}).values()):
            try:
                sock.close()
            except Exception:
                logger.debug("force-close: UDP sock.close() raised", exc_info=True)
        for entry in list(getattr(ctx, "beacon_socks", {}).values()):
            sock = entry[1] if isinstance(entry, tuple) and len(entry) > 1 else entry
            try:
                sock.close()
            except Exception:
                logger.debug("force-close: beacon sock.close() raised", exc_info=True)

    async def wait_until_running(self, timeout: float = 5.0) -> None:
        await asyncio.wait_for(self._running_event.wait(), timeout=timeout)
