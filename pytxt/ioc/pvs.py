"""caproto PVGroup defining the phase-1 + phase-2 PV namespaces.

Each pvproperty's `doc` becomes the .DESC field — discoverable to
agents reading the IOC's introspection PVs.
"""
from __future__ import annotations

from typing import Optional

import caproto as ca
from caproto.server import PVGroup, pvproperty

from pytxt.handlers.acquire import AcquisitionInFlightError, handle_acquire
from pytxt.handlers.ping import handle_ping
from pytxt.state.app_state import AppState

_BPM_MAX = 128  # waveform max_length; accommodates ~120 BPMs with headroom


class PyTxTPVGroup(PVGroup):
    # === HEALTH:* ===
    heartbeat = pvproperty(
        value=0, dtype=int, read_only=True,
        name="HEALTH:HEARTBEAT",
        doc="Liveness counter; increments every 1 second",
    )
    uptime_s = pvproperty(
        value=0.0, dtype=float, read_only=True,
        name="HEALTH:UPTIME_S",
        doc="Seconds since process start",
    )

    # === STATE:* (phase 1) ===
    version = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:VERSION",
        doc="Semantic version of the running PyTxT app",
    )
    last_ping_at = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_PING_AT",
        doc="ISO-8601 UTC timestamp of most recent ping; empty before first ping",
    )
    ping_count = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:PING_COUNT",
        doc="Total pings received since startup",
    )

    # === STATE:ACQUIRE_* (phase 2) ===
    acquire_in_flight = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:ACQUIRE_IN_FLIGHT",
        doc="1 while an acquisition is running; rejects concurrent CMD:ACQUIRE writes",
    )
    last_acquire_status = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:LAST_ACQUIRE_STATUS",
        doc="Enum: 0=NEVER, 1=ACQUIRING, 2=OK, 3=PARTIAL, 4=FAILED",
    )
    last_acquire_ok_count = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:LAST_ACQUIRE_OK_COUNT",
        doc="BPMs that returned valid data on the most recent ACQUIRE",
    )
    last_acquire_fail_count = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:LAST_ACQUIRE_FAIL_COUNT",
        doc="BPMs that timed out or returned invalid data on the most recent ACQUIRE",
    )
    last_acquire_timestamp = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_ACQUIRE_TIMESTAMP",
        doc="ISO-8601 UTC timestamp of the most recent acquisition; empty before first ACQUIRE",
    )
    last_acquire_fail_reason = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_ACQUIRE_FAIL_REASON",
        doc="Short error message when LAST_ACQUIRE_STATUS=FAILED; empty otherwise",
    )
    last_acquire_failed_bpm_names = pvproperty(
        value=[""] * _BPM_MAX, dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_ACQUIRE_FAILED_BPM_NAMES",
        max_length=_BPM_MAX,
        doc="Names of failed BPMs from the most recent ACQUIRE",
    )

    # === RESULT:BPM:* (phase 2) ===
    result_bpm_x_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:X_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM X position (mm) at detected injection turn; NaN for failed BPMs",
    )
    result_bpm_y_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:Y_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM Y position (mm) at detected injection turn; NaN for failed BPMs",
    )
    result_bpm_sum_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:SUM_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM sum signal (AU) at detected injection turn; NaN for failed BPMs",
    )
    result_bpm_injection_turn = pvproperty(
        value=[0] * _BPM_MAX, dtype=int, read_only=True,
        name="RESULT:BPM:INJECTION_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM detected injection-turn sample index; -1 for failed BPMs",
    )
    result_bpm_names = pvproperty(
        value=[""] * _BPM_MAX, dtype=ca.ChannelType.STRING, read_only=True,
        name="RESULT:BPM:NAMES",
        max_length=_BPM_MAX,
        doc="Static-after-startup: canonical BPM prefix for each array index",
    )

    # === CMD:* ===
    cmd_ping = pvproperty(
        value=0, dtype=int,
        name="CMD:PING",
        doc="Write any value to issue a ping (value ignored; trigger only)",
    )
    cmd_acquire = pvproperty(
        value=0, dtype=int,
        name="CMD:ACQUIRE",
        doc="Write any value to trigger BPM acquisition (value ignored; trigger only)",
    )

    def __init__(self, *args, state: AppState, reader: Optional[object] = None, **kwargs):
        self._state = state
        self._reader = reader
        super().__init__(*args, **kwargs)

    @cmd_ping.putter
    async def cmd_ping(self, instance, value):
        await handle_ping(self._state)
        return value

    @cmd_acquire.putter
    async def cmd_acquire(self, instance, value):
        """CA write to CMD:ACQUIRE dispatches to the canonical handler.

        If a reader is not configured (e.g., unit-style tests), the
        write is a no-op so the IOC remains testable in isolation.
        AcquisitionInFlightError is swallowed and surfaced via the
        STATE:ACQUIRE_IN_FLIGHT PV — CA writers see no exception.
        """
        if self._reader is None:
            return value
        try:
            await handle_acquire(self._state, self._reader)
        except AcquisitionInFlightError:
            # Already in flight — state PVs reflect that. CA write returns success.
            pass
        return value
