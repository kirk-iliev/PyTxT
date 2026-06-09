"""Phase-4 threading command handlers. STEP_CM first (corrector apply).

The handler is the single canonical entry point shared by the CMD-PV putter and
the REST route (north-star #1). It orchestrates: read present setpoints -> decide
(compare-and-set + clamp, pure domain) -> write -> publish state. The
compare-and-set guard (Decision D5) makes the non-idempotent incremental write
safe under agent retry and against competing writers (top-off / operators).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import math

from pytxt.api.schemas.threading import (
    CMChannelResult,
    InjectOneshotResponse,
    LastCMStepResult,
    LastInjectResult,
    StepCMResponse,
    ThreadStartResponse,
    ThreadStateResult,
    ThreadStopResponse,
)
from pytxt.ca_client.injection_trigger import SeqBusyTimeoutError
from pytxt.domain.correctors import plan_cm_step
from pytxt.domain.injection import build_tim_inj_req, fine_delay_counts
from pytxt.domain.threading import calc_cm_step, orbit_rms_mm
from pytxt.handlers.acquire import handle_acquire
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)

# A run is declared DIVERGED if the orbit RMS grows by more than this fraction
# over the previous iteration (the divergence guard, Decision D4).
_DIVERGENCE_EPS = 0.05


class CMStepInFlightError(RuntimeError):
    """Raised when CMD:STEP_CM is issued while one is already applying."""


class CMPreconditionError(Exception):
    """Raised when the compare-and-set guard refuses the step (Decision D5).

    `refused` lists the channel names whose live readback diverged from the
    caller's expected_prior beyond tolerance. No setpoints were written.
    """

    def __init__(self, refused: list[str]):
        self.refused = refused
        super().__init__(
            f"STEP_CM refused: {len(refused)} channel(s) differ from expected "
            f"setpoint (competing writer?): {refused[:5]}"
            f"{'...' if len(refused) > 5 else ''}"
        )


async def handle_step_cm(
    state: AppState,
    writer: object,
    *,
    family: str,
    device_list: list[int],
    deltas: list[float],
    expected_prior_a: list[float],
    tol_a: float = 0.05,
    dry_run: bool = False,
) -> StepCMResponse:
    """Apply one incremental corrector step with compare-and-set + clamp.

    Raises:
        CMStepInFlightError: another STEP_CM is in progress.
        ValueError: malformed request (bad family, index out of range, length
            mismatch) — mapped to HTTP 422.
        CMPreconditionError: compare-and-set guard refused (nothing written) —
            mapped to HTTP 409.
    """
    if state.cm_step_in_flight:
        raise CMStepInFlightError("STEP_CM already in progress")

    if not (len(device_list) == len(deltas) == len(expected_prior_a)):
        raise ValueError(
            "device_list/deltas/expected_prior_a length mismatch "
            f"({len(device_list)}/{len(deltas)}/{len(expected_prior_a)})"
        )
    if not device_list:
        raise ValueError("device_list is empty")

    chans = writer.channels(family)  # raises ValueError on unknown family
    for i in device_list:
        if i < 0 or i >= len(chans):
            raise ValueError(f"{family} index {i} out of range (0..{len(chans) - 1})")
    names = [chans[i].name for i in device_list]
    max_abs = [chans[i].max_abs_amps for i in device_list]

    try:
        await state.update(cm_step_in_flight=True)

        readbacks = await writer.read_setpoints(family, device_list)
        plan = plan_cm_step(names, readbacks, deltas, expected_prior_a, max_abs, tol_a)

        if not plan.ok:
            await state.update(
                last_cm_step=LastCMStepResult(
                    status="REFUSED", family=family, n_applied=0, n_clamped=0,
                    refused=plan.refused,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
            raise CMPreconditionError(plan.refused)

        if not dry_run:
            await writer.write_setpoints(
                family, device_list, [c.new_value_a for c in plan.channels]
            )

        n_clamped = sum(c.clamped for c in plan.channels)
        status = "DRY_RUN" if dry_run else "APPLIED"
        now = datetime.now(timezone.utc)

        await state.update(
            last_cm_step=LastCMStepResult(
                status=status, family=family,
                n_applied=len(plan.channels), n_clamped=n_clamped,
                refused=[], timestamp=now,
            ),
        )

        return StepCMResponse(
            status=status,
            family=family,
            applied=[
                CMChannelResult(
                    name=c.name, readback_a=c.readback_a, delta_a=c.delta_a,
                    new_value_a=c.new_value_a, clamped=c.clamped,
                )
                for c in plan.channels
            ],
            n_clamped=n_clamped,
            timestamp=now,
        )
    finally:
        await state.update(cm_step_in_flight=False)


# --- CMD:INJECT_ONESHOT (de-boxed srinjectoneshot) -------------------------


class InjectInFlightError(RuntimeError):
    """Raised when CMD:INJECT_ONESHOT is issued while one is already firing."""


class GunFireNotAllowedError(Exception):
    """Raised when inhibit=0 (real gun fire) is requested without allow_gun_fire
    (Decision D3 — real injection is a deliberate, gated opt-in)."""


class InjectionPreconditionError(Exception):
    """Raised when bucket loading / top-off is active and force is not set.

    TimInjReq has a live competing writer (top-off); writing into it then would
    race that writer, so the shot is refused unless explicitly forced.
    """


async def handle_inject_oneshot(
    state: AppState,
    trigger: object,
    *,
    bucket: int = 308,
    gun_bunches: int = 4,
    mode: int = 40,
    inhibit: int = 1,
    allow_gun_fire: bool = False,
    force: bool = False,
    sync: bool = True,
) -> InjectOneshotResponse:
    """Fire one injection shot via the de-boxed srinjectoneshot CA sequence.

    Safety: real gun fire (inhibit=0) requires allow_gun_fire=True (D3). The
    bucket-loading/top-off precondition is mandatory unless force=True.

    Raises:
        InjectInFlightError: another shot is in progress.
        GunFireNotAllowedError: inhibit=0 without allow_gun_fire (-> HTTP 403).
        InjectionPreconditionError: top-off active and not forced (-> HTTP 409).
    """
    if state.inject_in_flight:
        raise InjectInFlightError("INJECT_ONESHOT already in progress")
    if inhibit == 0 and not allow_gun_fire:
        raise GunFireNotAllowedError(
            "inhibit=0 fires the gun (real injection); set allow_gun_fire=true to permit it"
        )

    try:
        await state.update(inject_in_flight=True)

        # Mandatory precondition: do not race the top-off writer on TimInjReq.
        if not force:
            if await trigger.read_bucket_control() == 1:
                raise InjectionPreconditionError(
                    "bucket loading / top-off active (bucket:control:cmd=1); "
                    "refusing to race the top-off writer — stop bucket loading or force"
                )

        current = await trigger.read_tim_inj_req()
        req = build_tim_inj_req(current, bucket, gun_bunches, mode, inhibit)

        if sync:
            try:
                await trigger.sync_seq_busy()
            except SeqBusyTimeoutError:
                # The seqBusy sync is a robustness nicety (ReadMe_TimingSystem.m),
                # not strictly required to fire. Log and proceed.
                logger.warning("seqBusy sync timed out; firing without sync")

        await trigger.write_tim_inj_req(req)
        delay = fine_delay_counts(bucket)
        await trigger.write_fine_delay(delay)

        # Confirm signal: the per-shot confirm counter (Evt48Cnt vs Evt10Cnt) is
        # pending the control-room camonitor capture (checklist A1). For now we
        # echo the written sequence number + timestamp as the confirmation.
        seq = req[6]
        now = datetime.now(timezone.utc)
        await state.update(
            last_inject=LastInjectResult(
                status="FIRED", bucket=bucket, mode=mode, inhibit=inhibit,
                seq_num=seq, timestamp=now,
            ),
        )
        return InjectOneshotResponse(
            status="FIRED", bucket=bucket, gun_bunches=gun_bunches, mode=mode,
            inhibit=inhibit, seq_num=seq, fine_delay_counts=delay, timestamp=now,
        )
    finally:
        await state.update(inject_in_flight=False)


# --- CMD:THREAD_START / CMD:THREAD_STOP (first-turn threading loop) ---------


class ThreadInFlightError(RuntimeError):
    """Raised when CMD:THREAD_START is issued while a run is already active."""


class ThreadConfigError(Exception):
    """Raised when a dependency for threading is missing (matrix / writer /
    trigger) — mapped to HTTP 503."""


class ThreadNoReferenceError(Exception):
    """Raised when threading is started with no reference (R0) loaded — the
    diff has nothing to steer toward. Mapped to HTTP 422."""


async def _apply_cm_deltas(writer: object, family: str, dphi) -> None:
    """Apply per-corrector incremental deltas for one family within the loop.

    The loop just read these setpoints, so it passes the readbacks as the
    compare-and-set expected_prior (it owns the magnets for the run) — the guard
    can't refuse its own reads. Clamping still applies via plan_cm_step.
    """
    if dphi.size == 0:
        return
    indices = list(range(dphi.size))
    chans = writer.channels(family)
    names = [chans[i].name for i in indices]
    max_abs = [chans[i].max_abs_amps for i in indices]
    readbacks = await writer.read_setpoints(family, indices)
    plan = plan_cm_step(names, readbacks, [float(v) for v in dphi],
                        readbacks, max_abs, tol_a=math.inf)
    await writer.write_setpoints(family, indices, [c.new_value_a for c in plan.channels])


async def handle_thread_start(
    state: AppState,
    *,
    reader: object,
    response_matrix: object,
    corrector_writer: object | None = None,
    injection_trigger: object | None = None,
    max_steps: int = 6,
    gain: float = 0.5,
    fire_each_step: bool = False,
    conv_rms_mm: float | None = None,
    dry_run: bool = False,
    bucket: int = 308,
    inhibit: int = 1,
    allow_gun_fire: bool = False,
) -> ThreadStartResponse:
    """Run the first-turn threading loop to completion (blocking, like ACQUIRE).

    Per iteration: optional fire -> arm/read (via handle_acquire) -> diff ->
    measure RMS -> convergence/divergence check -> calc_cm_step -> apply. Stops on
    convergence (conv_rms_mm), divergence (RMS grows), max_steps, or a concurrent
    CMD:THREAD_STOP. `dry_run` measures + computes but writes/fires nothing.

    Raises:
        ThreadInFlightError: a run is already active (-> 409).
        ThreadConfigError: missing matrix/writer/trigger dependency (-> 503).
        ThreadNoReferenceError: no reference loaded (-> 422).
    """
    if state.thread_running:
        raise ThreadInFlightError("a threading run is already active")
    if response_matrix is None:
        raise ThreadConfigError("no response matrix loaded; cannot thread")
    if not state.reference_loaded:
        raise ThreadNoReferenceError("no reference (R0) loaded; load one before threading")
    if not dry_run and corrector_writer is None:
        raise ThreadConfigError("corrector writer required for a live (non-dry-run) threading run")
    if fire_each_step and not dry_run and injection_trigger is None:
        raise ThreadConfigError("injection trigger required for fire_each_step")

    def _now():
        return datetime.now(timezone.utc)

    await state.update(
        thread_running=True, thread_stop_requested=False,
        thread_state=ThreadStateResult(status="RUNNING", dry_run=dry_run, timestamp=_now()),
    )

    rms_history: list[float] = []
    status = "MAX_STEPS"
    iterations = 0
    final_rms = float("nan")
    rms_prev = math.inf
    last_step = None   # most recent calc_cm_step, surfaced for the step bar chart
    try:
        for i in range(max_steps):
            if state.thread_stop_requested:
                status = "STOPPED"
                break

            if fire_each_step and not dry_run:
                await handle_inject_oneshot(
                    state, injection_trigger, bucket=bucket, inhibit=inhibit,
                    allow_gun_fire=allow_gun_fire,
                )

            await handle_acquire(state, reader)  # populates state.last_diff
            diff = state.last_diff
            if diff is None:
                status = "FAILED"
                break

            rms = orbit_rms_mm(diff.dx, diff.dy)
            iterations = i + 1
            final_rms = rms
            rms_history.append(rms)
            await state.update(
                thread_state=ThreadStateResult(
                    status="RUNNING", iteration=iterations, last_rms_mm=rms,
                    dry_run=dry_run, timestamp=_now(),
                ),
            )

            if conv_rms_mm is not None and not math.isnan(rms) and rms <= conv_rms_mm:
                status = "CONVERGED"
                break
            if not math.isnan(rms) and rms > rms_prev * (1.0 + _DIVERGENCE_EPS):
                status = "DIVERGED"
                break
            rms_prev = rms

            step = calc_cm_step(diff.dx, diff.dy, response_matrix, gain=gain)
            last_step = step
            if not dry_run:
                await _apply_cm_deltas(corrector_writer, "HCM", step.dphi_hcm)
                await _apply_cm_deltas(corrector_writer, "VCM", step.dphi_vcm)

        await state.update(
            thread_state=ThreadStateResult(
                status=status, iteration=iterations, last_rms_mm=final_rms,
                final_rms_mm=final_rms, dry_run=dry_run, timestamp=_now(),
            ),
        )
        return ThreadStartResponse(
            status=status, iterations=iterations, final_rms_mm=final_rms,
            rms_history_mm=rms_history,
            step_hcm_a=last_step.dphi_hcm.tolist() if last_step is not None else [],
            step_vcm_a=last_step.dphi_vcm.tolist() if last_step is not None else [],
            dry_run=dry_run, timestamp=_now(),
        )
    finally:
        await state.update(thread_running=False)


async def handle_thread_stop(state: AppState) -> ThreadStopResponse:
    """Request the active threading run to stop after its current iteration.

    Idempotent: sets the cooperative stop flag (the loop checks it each
    iteration). Safe to call when nothing is running — the flag resets on the
    next THREAD_START.
    """
    await state.update(thread_stop_requested=True)
    return ThreadStopResponse(stop_requested=True)
