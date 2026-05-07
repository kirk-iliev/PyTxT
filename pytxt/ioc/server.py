"""Soft IOC lifecycle wrapper.

Owns the PVGroup, binds AppState changes to PV writes, and exposes
`run()` for composition.py to await.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from caproto.asyncio.server import Context

from pytxt.ioc.pvs import PyTxTPVGroup
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)

# Map of AppState field → PVGroup attribute name. Adding a new published
# field = add a pvproperty in pvs.py + add a row here.
_FIELD_TO_PV_ATTR = {
    "heartbeat": "heartbeat",
    "uptime_s_pushed": "uptime_s",   # AppState field name → PVGroup attr
    "version": "version",
    "last_ping_at": "last_ping_at",
    "ping_count": "ping_count",
}


class PyTxTIOC:
    """Wraps the caproto PVGroup with state binding and lifecycle.

    Parameters
    ----------
    prefix : str
        The PV name prefix (must end with ':'); e.g., 'TxT:' or 'OSPREY:TEST:TXT:'.
    host : str
        Interface to bind to ('0.0.0.0' for all interfaces, '127.0.0.1' for loopback).
    port : int
        CA server port. Use ``0`` to use whatever EPICS_CA_SERVER_PORT env var
        is set to (tests use the conftest-supplied ephemeral port).
    state : AppState
        The shared AppState; the IOC binds change-notifications and reads it.
    """

    def __init__(self, prefix: str, host: str, port: int, state: AppState):
        self.prefix = prefix
        self.host = host
        self.port = port
        self.state = state
        self.pvgroup = PyTxTPVGroup(prefix=prefix, state=state)
        self._context: Optional[Context] = None
        self._running_event = asyncio.Event()
        self._bind_state_changes()

    def _bind_state_changes(self) -> None:
        """Subscribe to AppState changes; each change writes the new value to the matching PV."""
        for field_name, pv_attr in _FIELD_TO_PV_ATTR.items():
            pv = getattr(self.pvgroup, pv_attr)

            async def _writer(value, _pv=pv, _name=field_name) -> None:
                # Coerce None to an empty string for string PVs.
                if value is None:
                    value = ""
                # Single retry on transient write failures; otherwise log and proceed.
                for attempt in (1, 2):
                    try:
                        await _pv.write(value)
                        return
                    except Exception:
                        if attempt == 1:
                            await asyncio.sleep(0.05)
                            continue
                        logger.exception(
                            "IOC write to PV for AppState field %r failed after retry",
                            _name,
                        )

            self.state.subscribe(field_name, _writer)

    async def run(self) -> None:
        """Start the caproto server. Sets the running event once listening."""
        # Apply per-instance port/host overrides when non-zero/non-empty.
        # These must be set before Context() is constructed because caproto
        # reads env vars at Context.__init__ time.
        if self.port:
            os.environ["EPICS_CAS_SERVER_PORT"] = str(self.port)
            os.environ["EPICS_CA_SERVER_PORT"] = str(self.port)
        if self.host:
            os.environ["EPICS_CAS_INTF_ADDR_LIST"] = self.host

        running_event = self._running_event
        pvgroup = self.pvgroup
        state = self.state

        async def _startup_hook(async_lib) -> None:
            """Push initial AppState values to PVs, then signal readiness."""
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
            running_event.set()

        self._context = Context(self.pvgroup.pvdb)
        await self._context.run(log_pv_names=False, startup_hook=_startup_hook)

    async def wait_until_running(self, timeout: float = 5.0) -> None:
        """Block until `run()` has set the running event (server is listening)."""
        await asyncio.wait_for(self._running_event.wait(), timeout=timeout)
