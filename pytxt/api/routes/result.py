"""GET /api/v1/result/* — read-only result endpoints."""
from fastapi import APIRouter, HTTPException, Request

from pytxt.api.schemas.result import BpmRawWaveforms

router = APIRouter(prefix="/api/v1", tags=["result"])


@router.get("/result/bpm/raw", response_model=BpmRawWaveforms)
async def get_bpm_raw(request: Request, bpm: str = "") -> BpmRawWaveforms:
    """Return the most-recent raw TBT waveforms for one BPM.

    Query params:
        bpm: BPM prefix (e.g. ``SR01C:BPM1``). Required and non-empty.

    Returns:
        200: ``BpmRawWaveforms`` with three 100 000-sample int lists.
        400: missing or empty ``bpm`` query parameter.
        404: ``bpm`` is not in the configured prefix list OR no raw data
             is stored for it yet (acquire never ran, or this BPM was in
             the last failed-set so no waveform was kept).

    No 409 path: ``state.last_acquire_raws`` is updated atomically at the
    end of ``handle_acquire`` so readers never see half-written data, even
    during a concurrent acquire.
    """
    if not bpm:
        raise HTTPException(400, "Missing required query parameter: bpm")
    state = request.app.state.app_state
    if bpm not in state.bpm_prefixes:
        raise HTTPException(404, f"Unknown BPM prefix: {bpm!r}")
    raw = state.last_acquire_raws.get(bpm)
    if raw is None:
        raise HTTPException(404, f"No raw waveform data for {bpm!r} yet")
    return BpmRawWaveforms(
        bpm_prefix=raw.prefix,
        x_nm=raw.x_wf.tolist(),
        y_nm=raw.y_wf.tolist(),
        sum_au=raw.sum_wf.tolist(),
        armed=raw.armed,
        read_timestamp=raw.read_timestamp,
    )
