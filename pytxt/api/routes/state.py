"""GET /api/v1/state — full AppState snapshot.
GET /api/v1/config — frontend bootstrap config (PV prefix etc.).
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
        bpm_prefixes=state.bpm_prefixes,
        acquire_in_flight=state.acquire_in_flight,
        last_acquire=state.last_acquire,
    )


@router.get("/config")
async def get_config(request: Request) -> dict:
    settings = request.app.state.settings
    prefix = settings.pv_prefix if settings else "OSPREY:TEST:TXT:"
    return {"pv_prefix": prefix}
