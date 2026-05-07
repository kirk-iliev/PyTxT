"""GET /api/v1/state — full AppState snapshot.

A pure projection of HEALTH:* and STATE:* PVs. Useful for one-shot
agents that don't want to maintain a CA subscription.
"""
from fastapi import APIRouter, Request

from pytxt.api.schemas.state import StateSnapshot

router = APIRouter(prefix="/api/v1", tags=["state"])


@router.get("/state", response_model=StateSnapshot)
async def get_state(request: Request) -> StateSnapshot:
    """Snapshot the full AppState as a single JSON document."""
    state = request.app.state.app_state
    return StateSnapshot(
        version=state.version,
        heartbeat=state.heartbeat,
        uptime_s=state.uptime_s,
        last_ping_at=state.last_ping_at,
        ping_count=state.ping_count,
    )
