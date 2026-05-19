"""POST /api/v1/cmd/* — REST mirrors of CMD-PV writes.

These endpoints invoke the **same handler functions** the IOC's CMD-PV
dispatcher invokes. The shared import enforces agentic parity
structurally — there is no way for REST and CA paths to diverge.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from pytxt.api.schemas.cmd import PingResponse
from pytxt.api.schemas.result import AcquireResponse
from pytxt.handlers.acquire import AcquisitionInFlightError, handle_acquire
from pytxt.handlers.ping import handle_ping

router = APIRouter(prefix="/api/v1/cmd", tags=["cmd"])


@router.post("/ping", response_model=PingResponse)
async def post_ping(request: Request) -> PingResponse:
    """Issue a ping. Body: ``{}``. Identical effect to CA write to CMD:PING."""
    state = request.app.state.app_state
    await handle_ping(state)
    return PingResponse(acknowledged_at=datetime.now(timezone.utc).isoformat())


@router.post("/acquire", response_model=AcquireResponse)
async def post_acquire(request: Request) -> AcquireResponse:
    """Trigger BPM acquisition. Body: ``{}``. Identical effect to CA write to CMD:ACQUIRE.

    Returns 409 if an acquisition is already in flight.
    """
    state = request.app.state.app_state
    reader = getattr(request.app.state, "bpm_reader", None)
    if reader is None:
        raise HTTPException(503, "BPM reader not configured")
    try:
        return await handle_acquire(state, reader)
    except AcquisitionInFlightError as e:
        raise HTTPException(409, str(e))
