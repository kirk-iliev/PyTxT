"""Phase-4 REST + state schemas for threading commands (STEP_CM first).

These models are the single source of truth for both the REST body/response and
the JSON payload accepted on the corresponding CMD-PV — so the CA and REST paths
are structurally identical (north-star #1).
"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


# Known injection modes (srinjectoneshot Mode arg). 40 = SR injection (default),
# 42 = "just the SR bumps" (commissioning). See injection-notes §3.
_INJECTION_MODES = (0, 10, 20, 30, 40, 41, 42)


class InjectOneshotRequest(BaseModel):
    """Body for POST /api/v1/cmd/inject_oneshot and the JSON payload for
    CMD:INJECT_ONESHOT (de-boxed srinjectoneshot).

    Defaults are the safe commissioning shot (Decisions D3/D6): bucket 308,
    `inhibit=1` (kicker/bumps fire, gun blocked → no new charge). Firing the gun
    for real (`inhibit=0`) additionally requires `allow_gun_fire=true` — a
    deliberate, explicit opt-in on top of the server-level enable.
    """
    bucket: int = Field(default=308, ge=1, le=328, description="SR RF bucket (D6 default 308)")
    gun_bunches: int = Field(default=4, ge=1, le=16, description="Number of gun bunches")
    mode: int = Field(default=40, description="Injection mode (40=SR inject, 42=bumps only)")
    inhibit: int = Field(
        default=1, ge=0, le=1,
        description="1 = gun blocked (no charge, default); 0 = gun fires (real injection)",
    )
    allow_gun_fire: bool = Field(
        default=False,
        description="Required true to permit inhibit=0 (real gun fire); guards against accidental firing",
    )
    force: bool = Field(
        default=False,
        description="Bypass the bucket-loading/top-off precondition (operator override)",
    )

    @field_validator("mode")
    @classmethod
    def _known_mode(cls, v: int) -> int:
        if v not in _INJECTION_MODES:
            raise ValueError(f"mode {v} not in known modes {_INJECTION_MODES}")
        return v


class InjectOneshotResponse(BaseModel):
    """Response for a fired injection one-shot."""
    status: Literal["FIRED"]
    bucket: int
    gun_bunches: int
    mode: int
    inhibit: int
    seq_num: int = Field(description="TimInjReq sequence number written (echo confirm)")
    fine_delay_counts: int
    timestamp: datetime


class LastInjectResult(BaseModel):
    """Summary of the most recent injection one-shot. Stored in
    AppState.last_inject and mirrored to STATE:INJ_LAST_* PVs."""
    status: Literal["NEVER", "FIRED"] = "NEVER"
    bucket: int = 0
    mode: int = 0
    inhibit: int = 1
    seq_num: int = 0
    timestamp: datetime | None = None


# --- Threading loop controller (CMD:THREAD_START / CMD:THREAD_STOP) ---------

# Terminal status of a threading run.
ThreadStatus = Literal[
    "NEVER", "RUNNING", "CONVERGED", "DIVERGED", "STOPPED", "MAX_STEPS", "FAILED"
]


class ThreadStartRequest(BaseModel):
    """Body for POST /api/v1/cmd/thread_start and the JSON payload for
    CMD:THREAD_START.

    Runs the first-turn threading loop to completion (blocking, like ACQUIRE):
    per iteration arm → optional fire → read → diff → calc_cm_step → apply, with
    damping `gain`, a divergence guard, and an optional RMS convergence exit
    (Decision D4). A reference (R0) must be loaded. `dry_run` measures and
    computes but writes no correctors and fires nothing.
    """
    max_steps: int = Field(default=6, ge=1, le=100, description="Hard iteration cap")
    gain: float = Field(default=0.5, gt=0.0, le=1.0, description="Loop damping (legacy 0.5)")
    fire_each_step: bool = Field(
        default=False, description="Fire an injection shot before each read"
    )
    conv_rms_mm: float | None = Field(
        default=None, ge=0.0,
        description="Stop early once combined orbit RMS (mm) falls to/below this",
    )
    dry_run: bool = Field(
        default=False, description="Measure + compute only; write no correctors, fire nothing"
    )
    # Forwarded to the per-step injection shot when fire_each_step is true.
    bucket: int = Field(default=308, ge=1, le=328)
    inhibit: int = Field(default=1, ge=0, le=1)
    allow_gun_fire: bool = Field(default=False)


class ThreadStartResponse(BaseModel):
    """Response when a threading run completes."""
    status: ThreadStatus
    iterations: int
    final_rms_mm: float
    rms_history_mm: list[float]
    # Last computed corrector step (incremental amps), for the step bar chart
    # (manual step 16). Empty if the run ended before any step was computed.
    step_hcm_a: list[float] = Field(default_factory=list)
    step_vcm_a: list[float] = Field(default_factory=list)
    dry_run: bool
    timestamp: datetime


class ThreadStopResponse(BaseModel):
    stop_requested: bool


class ThreadStateResult(BaseModel):
    """Threading progress/summary. Stored in AppState.thread_state and mirrored
    to STATE:THREAD_* PVs. `iteration`/`last_rms_mm` update live during a run."""
    status: ThreadStatus = "NEVER"
    iteration: int = 0
    last_rms_mm: float = 0.0
    final_rms_mm: float = 0.0
    dry_run: bool = False
    timestamp: datetime | None = None
