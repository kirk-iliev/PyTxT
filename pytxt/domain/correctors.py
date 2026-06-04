"""Corrector-step decision logic (Phase 4, Decision D5 — compare-and-set).

Pure functions: NO caproto/FastAPI/asyncio. Given the *present* corrector
setpoints (read by the adapter above), decide what to write. Two safety rules:

1. **Compare-and-set (D5):** an incremental corrector step is not idempotent, so
   each channel carries the setpoint the caller *expected* to find. If the live
   readback disagrees (beyond a tolerance) a competing writer moved the magnet —
   refuse the **whole** step rather than apply a delta onto an unexpected base.
2. **Clamp:** the resulting setpoint is clamped to the hardware |amps| limit
   (`local_maxsp`) so a bad delta can't command past the magnet's range.

The all-or-nothing refusal keeps a multi-corrector step from partially applying.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CMChannelPlan:
    """The decided write for one corrector channel."""
    name: str
    readback_a: float        # present setpoint read back
    delta_a: float           # requested incremental change
    new_value_a: float       # readback + delta, after clamping
    clamped: bool            # True if the limit truncated the requested value


@dataclass(frozen=True)
class CMApplyPlan:
    """The decided writes for a whole step. `refused` is non-empty iff the
    compare-and-set precondition failed for at least one channel — in which
    case the handler must write nothing."""
    channels: list[CMChannelPlan]
    refused: list[str]       # names whose readback != expected_prior (CAS miss)

    @property
    def ok(self) -> bool:
        return not self.refused

    @property
    def any_clamped(self) -> bool:
        return any(c.clamped for c in self.channels)


def clamp_setpoint(value_a: float, max_abs_a: float) -> tuple[float, bool]:
    """Clamp `value_a` to [-max_abs_a, +max_abs_a]. Returns (clamped_value, was_clamped)."""
    if value_a > max_abs_a:
        return max_abs_a, True
    if value_a < -max_abs_a:
        return -max_abs_a, True
    return value_a, False


def plan_cm_step(
    names: list[str],
    readbacks_a: list[float],
    deltas_a: list[float],
    expected_prior_a: list[float],
    max_abs_a: list[float],
    tol_a: float,
) -> CMApplyPlan:
    """Decide the per-channel writes for one corrector step.

    All five lists must be the same length and aligned. For each channel:
    refuse if ``|readback - expected_prior| > tol_a`` (compare-and-set miss),
    otherwise plan ``clamp(readback + delta)``. If *any* channel is refused the
    returned plan's ``refused`` list is non-empty and the caller writes nothing.
    """
    n = len(names)
    if not (len(readbacks_a) == len(deltas_a) == len(expected_prior_a)
            == len(max_abs_a) == n):
        raise ValueError(
            "plan_cm_step: names/readbacks/deltas/expected_prior/max_abs "
            f"length mismatch ({n}/{len(readbacks_a)}/{len(deltas_a)}/"
            f"{len(expected_prior_a)}/{len(max_abs_a)})"
        )
    if tol_a < 0:
        raise ValueError(f"plan_cm_step: tol_a must be >= 0, got {tol_a}")

    channels: list[CMChannelPlan] = []
    refused: list[str] = []
    for name, rb, delta, expect, mx in zip(
        names, readbacks_a, deltas_a, expected_prior_a, max_abs_a
    ):
        if abs(rb - expect) > tol_a:
            refused.append(name)
        new_value, clamped = clamp_setpoint(rb + delta, mx)
        channels.append(
            CMChannelPlan(
                name=name,
                readback_a=rb,
                delta_a=delta,
                new_value_a=new_value,
                clamped=clamped,
            )
        )

    return CMApplyPlan(channels=channels, refused=refused)
