"""GET /api/v1/state — full AppState snapshot.
GET /api/v1/config — frontend bootstrap config (PV prefix etc.).
"""
from fastapi import APIRouter, Request

from pytxt.api.schemas.reference import DiffSummary, ReferenceStatus
from pytxt.api.schemas.state import AnalysisSummary, StateSnapshot
from pytxt.config.corrector_channels import load_corrector_channels

router = APIRouter(prefix="/api/v1", tags=["state"])


@router.get("/state", response_model=StateSnapshot)
async def get_state(request: Request) -> StateSnapshot:
    state = request.app.state.app_state

    # Phase 3: diff summary + reference block. Both null when absent so the
    # snapshot stays phase-2-compatible until a reference is promoted/loaded.
    last_diff = (
        DiffSummary(**state.last_diff.summary.__dict__)
        if state.last_diff is not None
        else None
    )
    reference = None
    if state.reference_loaded:
        n_valid = state.last_diff.summary.n_valid if state.last_diff is not None else 0
        reference = ReferenceStatus(
            loaded=True,
            name=state.reference_name,
            loaded_at=state.reference_loaded_at,
            source=state.reference_source,
            n_aligned=n_valid,
            n_unaligned=max(len(state.bpm_prefixes) - n_valid, 0),
        )

    analysis = (
        AnalysisSummary(**state.last_analysis.__dict__)
        if state.last_analysis is not None
        else None
    )

    return StateSnapshot(
        version=state.version,
        heartbeat=state.heartbeat,
        uptime_s=state.uptime_s,
        last_ping_at=state.last_ping_at,
        ping_count=state.ping_count,
        bpm_prefixes=state.bpm_prefixes,
        acquire_in_flight=state.acquire_in_flight,
        last_acquire=state.last_acquire,
        reference=reference,
        last_diff=last_diff,
        analysis=analysis,
    )


@router.get("/config")
async def get_config(request: Request) -> dict:
    """Frontend bootstrap. Returns the deployed PV prefix so the browser
    knows what names to subscribe to under any namespace (dev/prod)."""
    settings = request.app.state.settings
    prefix = settings.pv_prefix if settings else "OSPREY:TEST:TXT:"
    return {"pv_prefix": prefix}


@router.get("/config/correctors")
async def get_corrector_catalog(request: Request) -> dict:
    """The HCM/VCM corrector catalog: per-family ordered device list with each
    channel's name and |setpoint| limit (amps). The index is the 0-based family
    index used by CMD:STEP_CM and the response matrix. Read-only, no machine I/O
    — drives the Correctors panel's device picker and is discoverable by agents.
    """
    # Prefer the writer's already-loaded channels; fall back to the catalog
    # files so the endpoint works even when no corrector writer is configured.
    writer = getattr(request.app.state, "corrector_writer", None)
    settings = request.app.state.settings
    out: dict[str, list[dict]] = {}
    for family in ("HCM", "VCM"):
        if writer is not None:
            chans = writer.channels(family)
        else:
            path = settings.hcm_channels_path if family == "HCM" else settings.vcm_channels_path
            chans = load_corrector_channels(path, family)
        out[family] = [
            {"index": i, "name": c.name, "max_abs_a": c.max_abs_amps}
            for i, c in enumerate(chans)
        ]
    return out
