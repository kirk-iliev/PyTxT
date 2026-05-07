"""GET /health — transport-level liveness probe.

Distinct from HEALTH:* PVs: this is for k8s/load-balancers and always
returns HTTP 200 even when the app is degraded. State-of-the-app
information is in HEALTH:* PVs (and the StateSnapshot).
"""
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health", tags=["health"])
async def health(request: Request) -> dict:
    """Liveness probe. Always HTTP 200; consumers infer health from the JSON body."""
    state = request.app.state.app_state
    return {"status": "ok", "uptime_s": state.uptime_s}
