"""caproto PVGroup defining the phase-1 PV namespace.

Each pvproperty's `doc` becomes the .DESC field — discoverable to
agents reading the IOC's introspection PVs.
"""
import caproto as ca
from caproto.server import PVGroup, pvproperty

from pytxt.handlers.ping import handle_ping
from pytxt.state.app_state import AppState


class PyTxTPVGroup(PVGroup):
    # --- HEALTH:* ---
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

    # --- STATE:* ---
    # Use ChannelType.STRING (EPICS native string) so CA reads return a single
    # element b'<value>' rather than a byte-array, matching the test assertion
    # pattern: v.data[0].decode() == "0.1.0".
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

    # --- CMD:* ---
    cmd_ping = pvproperty(
        value=0, dtype=int,
        name="CMD:PING",
        doc="Write any value to issue a ping (value ignored; trigger only)",
    )

    def __init__(self, *args, state: AppState, **kwargs):
        self._state = state
        super().__init__(*args, **kwargs)

    @cmd_ping.putter
    async def cmd_ping(self, instance, value):
        """CA write to CMD:PING dispatches to the canonical handler."""
        await handle_ping(self._state)
        return value  # the written value itself is ignored
