"""REST schema: full AppState projection."""
from typing import Optional
from pydantic import BaseModel, Field


class StateSnapshot(BaseModel):
    """Projection of AppState fields for `GET /api/v1/state`. Pure
    one-to-one mapping to the published HEALTH:* and STATE:* PVs."""
    version: str = Field(description="Semantic version of the running app")
    heartbeat: int = Field(description="Liveness counter; increments every 1s")
    uptime_s: float = Field(description="Seconds since process start")
    last_ping_at: Optional[str] = Field(
        default=None, description="ISO-8601 timestamp of most recent ping; null until first ping"
    )
    ping_count: int = Field(description="Pings received since startup")
