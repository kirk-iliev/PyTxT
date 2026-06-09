"""REST schema: full AppState projection."""
from typing import Optional
from pydantic import BaseModel, Field

from pytxt.api.schemas.reference import DiffSummary, ReferenceStatus
from pytxt.api.schemas.result import AcquireStatus, LastAcquireResult


def _never_last_acquire() -> LastAcquireResult:
    """Default LastAcquireResult for a freshly-started service (no ACQUIRE yet)."""
    return LastAcquireResult(
        status=AcquireStatus.NEVER,
        ok_count=0,
        fail_count=0,
        failed_bpm_names=[],
        injection_turn_median=-1,
        timestamp=None,
    )


class AnalysisSummary(BaseModel):
    """First-turn analysis projection — mirrors RESULT:ANALYSIS:* PVs."""
    x_rms_mm: float
    y_rms_mm: float
    x_max_abs_mm: float
    y_max_abs_mm: float
    n_live_bpms: int
    n_bpms: int
    reach_index: int
    reach_name: str


class StateSnapshot(BaseModel):
    """Projection of AppState fields for `GET /api/v1/state`. Pure
    one-to-one mapping to the published HEALTH:*, STATE:*, and RESULT:* PVs."""
    # Phase 1
    version: str = Field(description="Semantic version of the running app")
    heartbeat: int = Field(description="Liveness counter; increments every 1s")
    uptime_s: float = Field(description="Seconds since process start")
    last_ping_at: Optional[str] = Field(
        default=None, description="ISO-8601 timestamp of most recent ping; null until first ping"
    )
    ping_count: int = Field(description="Pings received since startup")
    # Phase 2
    bpm_prefixes: list[str] = Field(
        default_factory=list,
        description="Configured BPM prefixes; static after startup",
    )
    acquire_in_flight: bool = Field(
        default=False,
        description="True while an acquisition is running",
    )
    last_acquire: LastAcquireResult = Field(
        default_factory=_never_last_acquire,
        description="Outcome of the most recent ACQUIRE; status=NEVER before first",
    )
    # Phase 3 (reference) — optional; null when nothing loaded / no diff yet
    reference: Optional[ReferenceStatus] = Field(
        default=None,
        description="Currently-loaded reference; null when none loaded",
    )
    last_diff: Optional[DiffSummary] = Field(
        default=None,
        description="Summary of the most recent B − R0 diff; null when no diff",
    )
    # Phase 5 / U6 — first-turn analysis; null before the first acquire
    analysis: Optional[AnalysisSummary] = Field(
        default=None,
        description="First-turn analysis from the most recent acquire; null before first",
    )
