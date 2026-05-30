"""caproto PVGroup defining the phase-1 + phase-2 PV namespaces.

Each pvproperty's `doc` becomes the .DESC field — discoverable to
agents reading the IOC's introspection PVs.
"""
from __future__ import annotations

from typing import Optional

import caproto as ca
from caproto.server import PVGroup, pvproperty

from pytxt.handlers.acquire import handle_acquire
from pytxt.handlers.ping import handle_ping
from pytxt.handlers.reference import (
    NoLastAcquireError,
    handle_clear_ref,
    handle_promote_ref,
)
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

    # === STATE:REF_* (phase 3) ===
    ref_loaded = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:REF_LOADED",
        doc="1 when a reference trajectory is loaded; 0 when none",
    )
    ref_name = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:REF_NAME",
        doc="Name of the loaded reference ('<promoted>' under promote); empty when none",
    )
    ref_loaded_at = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:REF_LOADED_AT",
        doc="ISO-8601 UTC timestamp when the reference was loaded; empty when none",
    )
    ref_source = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:REF_SOURCE",
        doc="Provenance of the loaded reference: 'promoted', 'file', or empty when none",
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
    result_bpm_x_diff_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:X_DIFF_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM X B-R0 (mm); NaN where either side NaN or no ref loaded",
    )
    result_bpm_y_diff_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:Y_DIFF_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM Y B-R0 (mm); NaN where either side NaN or no ref loaded",
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
    cmd_promote_ref = pvproperty(
        value=0, dtype=int,
        name="CMD:PROMOTE_REF",
        doc="Write any value to promote the current acquisition to an in-memory reference (value ignored; trigger only)",
    )
    cmd_clear_ref = pvproperty(
        value=0, dtype=int,
        name="CMD:CLEAR_REF",
        doc="Write any value to unload the current reference (value ignored; trigger only)",
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

        AcquisitionInFlightError is RE-RAISED so caproto surfaces it as a
        CA write error to the client — symmetric to REST's 409 returned
        by POST /api/v1/cmd/acquire when an acquire is in flight. The
        STATE:ACQUIRE_IN_FLIGHT PV continues to publish 1 during the
        busy window for subscribers who prefer observation over retry.
        """
        if self._reader is None:
            return value
        await handle_acquire(self._state, self._reader)
        return value

    @cmd_promote_ref.putter
    async def cmd_promote_ref(self, instance, value):
        """CA write to CMD:PROMOTE_REF promotes the live acquisition to a ref.

        Acts on self._state only — no reader required, unlike CMD:ACQUIRE.
        NoLastAcquireError is RE-RAISED so caproto surfaces it as a CA write
        error — symmetric to REST's 422 from POST /api/v1/cmd/promote_ref.
        STATE:REF_LOADED publishes the outcome for subscribers who prefer
        observation over retry.
        """
        await handle_promote_ref(self._state)
        return value

    @cmd_clear_ref.putter
    async def cmd_clear_ref(self, instance, value):
        """CA write to CMD:CLEAR_REF unloads the current reference.

        Acts on self._state only — no reader required. Idempotent: succeeds
        even when nothing is loaded (mirrors REST's /api/v1/cmd/clear_ref).
        """
        await handle_clear_ref(self._state)
        return value
