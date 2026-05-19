"""Phase-2 REST schemas for BPM acquisition results.

The status enum has both a string form (REST/JSON-friendly) and an int form
(EPICS-friendly). The two mappings here are the single source of truth.
"""
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class AcquireStatus(StrEnum):
    NEVER = "NEVER"
    ACQUIRING = "ACQUIRING"
    OK = "OK"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


# Canonical int↔string mapping (same in IOC enum PV and REST JSON).
STATUS_INT_TO_STR: dict[int, str] = {
    0: "NEVER",
    1: "ACQUIRING",
    2: "OK",
    3: "PARTIAL",
    4: "FAILED",
}
STATUS_STR_TO_INT: dict[str, int] = {v: k for k, v in STATUS_INT_TO_STR.items()}


class LastAcquireResult(BaseModel):
    """Outcome of the most recent ACQUIRE. Stored in AppState.last_acquire
    and mirrored to STATE:LAST_ACQUIRE_* PVs."""
    status: AcquireStatus = Field(description="Lifecycle status")
    ok_count: int = Field(description="BPMs that returned valid data")
    fail_count: int = Field(description="BPMs that timed out / returned invalid data")
    failed_bpm_names: list[str] = Field(default_factory=list)
    injection_turn_median: int = Field(
        description="Median per-BPM detected injection turn; -1 if all failed"
    )
    timestamp: datetime | None = Field(default=None)
    fail_reason: str = Field(default="", description="Short error when status=FAILED")


class AcquireResponse(BaseModel):
    """Response body for POST /api/v1/cmd/acquire."""
    status: Literal["OK", "PARTIAL", "FAILED"]
    ok_count: int
    fail_count: int
    failed_bpm_names: list[str]
    injection_turn_median: int
    timestamp: datetime


class BpmRawWaveforms(BaseModel):
    """Response body for GET /api/v1/result/bpm/raw?bpm=<prefix>."""
    bpm_prefix: str
    x_nm: list[int]   # 100000 samples, raw nm (no mm conversion)
    y_nm: list[int]
    sum_au: list[int]
    armed: int        # 0 = data was valid at read time
    read_timestamp: datetime
