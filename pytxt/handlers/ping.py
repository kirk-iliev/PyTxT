"""The canonical handler — invoked identically by the IOC CMD-PV
dispatcher (on `CMD:PING` write) and by the REST POST route. The shared
import path enforces agentic parity structurally.
"""
from datetime import datetime, timezone

from pytxt.state.app_state import AppState


async def handle_ping(state: AppState) -> None:
    """Record that a ping was received.

    Side effects: increments ``state.ping_count`` and sets
    ``state.last_ping_at`` to the current UTC ISO-8601 timestamp.
    """
    await state.update(
        last_ping_at=datetime.now(timezone.utc).isoformat(),
        ping_count=state.ping_count + 1,
    )
