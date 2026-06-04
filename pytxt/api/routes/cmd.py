"""POST /api/v1/cmd/* — REST mirrors of CMD-PV writes.

These endpoints invoke the **same handler functions** the IOC's CMD-PV
dispatcher invokes. The shared import enforces agentic parity
structurally — there is no way for REST and CA paths to diverge.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from pytxt.api.schemas.cmd import PingResponse
from pytxt.api.schemas.reference import (
    ClearRefResponse,
    LoadRefRequest,
    LoadRefResponse,
    PromoteRefResponse,
    SaveRefRequest,
    SaveRefResponse,
)
from pytxt.api.schemas.result import AcquireResponse
from pytxt.api.schemas.threading import (
    InjectOneshotRequest,
    InjectOneshotResponse,
    StepCMRequest,
    StepCMResponse,
    ThreadStartRequest,
    ThreadStartResponse,
    ThreadStopResponse,
)
from pytxt.domain.reference import ReferenceLoadError
from pytxt.handlers.acquire import AcquisitionInFlightError, handle_acquire
from pytxt.handlers.ping import handle_ping
from pytxt.handlers.reference import (
    InvalidReferenceNameError,
    NoLastAcquireError,
    ReferenceExistsError,
    ReferenceNotFoundError,
    handle_clear_ref,
    handle_load_ref,
    handle_promote_ref,
    handle_save_ref,
)
from pytxt.handlers.threading import (
    CMPreconditionError,
    CMStepInFlightError,
    GunFireNotAllowedError,
    InjectInFlightError,
    InjectionPreconditionError,
    ThreadConfigError,
    ThreadInFlightError,
    ThreadNoReferenceError,
    handle_inject_oneshot,
    handle_step_cm,
    handle_thread_start,
    handle_thread_stop,
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


@router.post("/load_ref", response_model=LoadRefResponse)
async def post_load_ref(request: Request, body: LoadRefRequest) -> LoadRefResponse:
    """Load a named reference from the library, arming its B − R0 diff.

    Identical effect to a CA write to CMD:LOAD_REF. Returns 422 for an
    unsafe/malformed name or a corrupt .mat, 404 when the file is absent.
    """
    state = request.app.state.app_state
    reference_dir = getattr(request.app.state, "reference_dir", None)
    try:
        return await handle_load_ref(state, reference_dir, body.name)
    except InvalidReferenceNameError as e:
        raise HTTPException(422, str(e))
    except ReferenceNotFoundError as e:
        raise HTTPException(404, str(e))
    except ReferenceLoadError as e:
        raise HTTPException(422, str(e))


@router.post("/save_ref", response_model=SaveRefResponse)
async def post_save_ref(request: Request, body: SaveRefRequest) -> SaveRefResponse:
    """Write the current acquisition to a .mat in the library.

    Identical effect to a CA write to CMD:SAVE_REF. An omitted ``name``
    defaults to the timestamp pattern. Returns 422 when there has been no
    successful acquire or the name is unsafe, 409 when the target exists.
    """
    state = request.app.state.app_state
    reference_dir = getattr(request.app.state, "reference_dir", None)
    try:
        return await handle_save_ref(state, reference_dir, body.name)
    except NoLastAcquireError as e:
        raise HTTPException(422, str(e))
    except InvalidReferenceNameError as e:
        raise HTTPException(422, str(e))
    except ReferenceExistsError as e:
        raise HTTPException(409, str(e))


@router.post("/step_cm", response_model=StepCMResponse)
async def post_step_cm(request: Request, body: StepCMRequest) -> StepCMResponse:
    """Apply one incremental HCM/VCM corrector step (Phase 4).

    Identical effect to a CA write of the same JSON payload to CMD:STEP_CM. The
    compare-and-set guard (`expected_prior_a` + `tol_a`, Decision D5) refuses the
    whole step if any live setpoint diverged — returns 409. Malformed requests
    (bad family/index/lengths) return 422, no corrector writer 503.
    """
    state = request.app.state.app_state
    writer = getattr(request.app.state, "corrector_writer", None)
    if writer is None:
        raise HTTPException(503, "corrector writer not configured")
    try:
        return await handle_step_cm(
            state, writer,
            family=body.family, device_list=body.device_list, deltas=body.deltas,
            expected_prior_a=body.expected_prior_a, tol_a=body.tol_a,
            dry_run=body.dry_run,
        )
    except CMStepInFlightError as e:
        raise HTTPException(409, str(e))
    except CMPreconditionError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/inject_oneshot", response_model=InjectOneshotResponse)
async def post_inject_oneshot(request: Request, body: InjectOneshotRequest) -> InjectOneshotResponse:
    """Fire one injection shot (de-boxed srinjectoneshot). Phase 4.

    Identical effect to a CA write of the same JSON to CMD:INJECT_ONESHOT.
    Defaults are the safe commissioning shot (bucket 308, inhibit=1). Real gun
    fire (inhibit=0) requires allow_gun_fire=true → else 403. Top-off active and
    not forced → 409; another shot in flight → 409; no trigger configured → 503.
    """
    state = request.app.state.app_state
    trigger = getattr(request.app.state, "injection_trigger", None)
    if trigger is None:
        raise HTTPException(503, "injection trigger not configured")
    try:
        return await handle_inject_oneshot(
            state, trigger,
            bucket=body.bucket, gun_bunches=body.gun_bunches, mode=body.mode,
            inhibit=body.inhibit, allow_gun_fire=body.allow_gun_fire, force=body.force,
        )
    except GunFireNotAllowedError as e:
        raise HTTPException(403, str(e))
    except InjectInFlightError as e:
        raise HTTPException(409, str(e))
    except InjectionPreconditionError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/thread_start", response_model=ThreadStartResponse)
async def post_thread_start(request: Request, body: ThreadStartRequest) -> ThreadStartResponse:
    """Run the first-turn threading loop to completion (blocking). Phase 4.

    Identical effect to a CA write of the same JSON to CMD:THREAD_START. Needs a
    loaded response matrix (else 503), a loaded reference (else 422), and a
    corrector writer for live (non-dry-run) runs. A run already active → 409.
    """
    state = request.app.state.app_state
    try:
        return await handle_thread_start(
            state,
            reader=getattr(request.app.state, "bpm_reader", None),
            response_matrix=getattr(request.app.state, "response_matrix", None),
            corrector_writer=getattr(request.app.state, "corrector_writer", None),
            injection_trigger=getattr(request.app.state, "injection_trigger", None),
            max_steps=body.max_steps, gain=body.gain,
            fire_each_step=body.fire_each_step, conv_rms_mm=body.conv_rms_mm,
            dry_run=body.dry_run, bucket=body.bucket, inhibit=body.inhibit,
            allow_gun_fire=body.allow_gun_fire,
        )
    except ThreadInFlightError as e:
        raise HTTPException(409, str(e))
    except ThreadNoReferenceError as e:
        raise HTTPException(422, str(e))
    except ThreadConfigError as e:
        raise HTTPException(503, str(e))


@router.post("/thread_stop", response_model=ThreadStopResponse)
async def post_thread_stop(request: Request) -> ThreadStopResponse:
    """Request the active threading run to stop. Body: ``{}``. Identical effect
    to a CA write to CMD:THREAD_STOP. Idempotent."""
    return await handle_thread_stop(request.app.state.app_state)
