"""REST schema: full AppState projection."""
from typing import Optional
from pydantic import BaseModel, Field

from pytxt.api.schemas.result import LastAcquireResult


class StateSnapshot(BaseModel):
    """Projection of AppState fields for `GET /api/v1/state`. Pure
    one-to-one mapping to the published HEALTH:*, STATE:*, and RESULT:* PVs."""
    # Phase 1
    version: str = Field(description="Semantic version of the running app")
    heartbeat: int = Field(description="Liveness counter; increments every 1s")
    uptime_s: float = Field(description="Seconds since process start")
    last_ping_at: Optional[str] = Field(default=None)
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
        description="Outcome of the most recent ACQUIRE; status=NEVER before first"
    )
