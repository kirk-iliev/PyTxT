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

from pytxt.api.schemas.threading import (
    CMChannelResult,
    InjectOneshotResponse,
    LastCMStepResult,
    LastInjectResult,
    StepCMResponse,
)
from pytxt.ca_client.injection_trigger import SeqBusyTimeoutError
from pytxt.domain.correctors import plan_cm_step
from pytxt.domain.injection import build_tim_inj_req, fine_delay_counts
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)


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
