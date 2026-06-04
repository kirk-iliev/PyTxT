"""Phase-4 REST + state schemas for threading commands (STEP_CM first).

These models are the single source of truth for both the REST body/response and
the JSON payload accepted on the corresponding CMD-PV — so the CA and REST paths
are structurally identical (north-star #1).
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class StepCMRequest(BaseModel):
    """Body for POST /api/v1/cmd/step_cm and the JSON payload for CMD:STEP_CM.

    `device_list` are 0-based family indices (positions in the committed HCM/VCM
    catalog). `deltas` are incremental changes in amps. `expected_prior_a` is the
    setpoint the caller believes each channel currently holds — the compare-and-set
    guard (Decision D5): the step is refused if any live readback differs by more
    than `tol_a`, so a retry or competing writer can't double-apply.
    """
    family: Literal["HCM", "VCM"] = Field(description="Corrector family")
    device_list: list[int] = Field(description="0-based family indices to step")
    deltas: list[float] = Field(description="Incremental setpoint changes (amps)")
    expected_prior_a: list[float] = Field(
        description="Expected present setpoint per channel (amps); compare-and-set base"
    )
    tol_a: float = Field(
        default=0.05, ge=0.0,
        description="Max allowed |readback - expected| before refusing (amps)",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, plan and clamp but write nothing (returns DRY_RUN)",
    )


class CMChannelResult(BaseModel):
    """Per-channel outcome of a corrector step."""
    name: str
    readback_a: float
    delta_a: float
    new_value_a: float
    clamped: bool


class StepCMResponse(BaseModel):
    """Response for a successful (or dry-run) corrector step."""
    status: Literal["APPLIED", "DRY_RUN"]
    family: Literal["HCM", "VCM"]
    applied: list[CMChannelResult]
    n_clamped: int
    timestamp: datetime


class LastCMStepResult(BaseModel):
    """Summary of the most recent corrector step. Stored in AppState.last_cm_step
    and mirrored to STATE:CM_LAST_* PVs."""
    status: Literal["NEVER", "APPLIED", "DRY_RUN", "REFUSED"] = "NEVER"
    family: str = ""
    n_applied: int = 0
    n_clamped: int = 0
    refused: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None
