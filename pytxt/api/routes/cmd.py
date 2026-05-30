"""POST /api/v1/cmd/* — REST mirrors of CMD-PV writes.

These endpoints invoke the **same handler functions** the IOC's CMD-PV
dispatcher invokes. The shared import enforces agentic parity
structurally — there is no way for REST and CA paths to diverge.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from pytxt.api.schemas.cmd import PingResponse
from pytxt.api.schemas.reference import ClearRefResponse, PromoteRefResponse
from pytxt.api.schemas.result import AcquireResponse
from pytxt.handlers.acquire import AcquisitionInFlightError, handle_acquire
from pytxt.handlers.ping import handle_ping
from pytxt.handlers.reference import (
    NoLastAcquireError,
    handle_clear_ref,
    handle_promote_ref,
)

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


@router.post("/promote_ref", response_model=PromoteRefResponse)
async def post_promote_ref(request: Request) -> PromoteRefResponse:
    """Promote the current acquisition to an in-memory reference.

    Identical effect to a CA write to CMD:PROMOTE_REF. Returns 422 if there
    has been no successful acquisition to source the reference from.
    """
    state = request.app.state.app_state
    try:
        return await handle_promote_ref(state)
    except NoLastAcquireError as e:
        raise HTTPException(422, str(e))


@router.post("/clear_ref", response_model=ClearRefResponse)
async def post_clear_ref(request: Request) -> ClearRefResponse:
    """Unload the in-memory reference. Identical effect to a CA write to
    CMD:CLEAR_REF. Idempotent — succeeds even when nothing is loaded."""
    return await handle_clear_ref(request.app.state.app_state)
