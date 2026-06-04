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
    LastCMStepResult,
    StepCMResponse,
)
from pytxt.domain.correctors import plan_cm_step
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
