"""REST schemas for command endpoints."""
from pydantic import BaseModel, Field


class PingResponse(BaseModel):
    """Response from `POST /api/v1/cmd/ping`."""
    acknowledged_at: str = Field(description="ISO-8601 UTC timestamp of acknowledgement")
