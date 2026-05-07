"""GET /api/v1/state — full AppState snapshot.
GET /api/v1/config — frontend bootstrap config (PV prefix etc.).

Both are pure projections of canonical sources of truth.
"""
from fastapi import APIRouter, Request

from pytxt.api.schemas.state import StateSnapshot

router = APIRouter(prefix="/api/v1", tags=["state"])


@router.get("/state", response_model=StateSnapshot)
async def get_state(request: Request) -> StateSnapshot:
    state = request.app.state.app_state
    return StateSnapshot(
        version=state.version,
        heartbeat=state.heartbeat,
        uptime_s=state.uptime_s,
        last_ping_at=state.last_ping_at,
        ping_count=state.ping_count,
    )


@router.get("/config")
async def get_config(request: Request) -> dict:
    """Frontend bootstrap. Returns the deployed PV prefix so the browser
    knows what names to subscribe to under any namespace (dev/prod)."""
    settings = request.app.state.settings
    prefix = settings.pv_prefix if settings else "OSPREY:TEST:TXT:"
    return {"pv_prefix": prefix}
