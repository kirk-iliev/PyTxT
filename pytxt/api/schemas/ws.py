"""WebSocket message schemas for the WS-to-CA bridge."""
from typing import Any, Literal
from pydantic import BaseModel, Field


class WSSubscribe(BaseModel):
    """Client → server: subscribe or unsubscribe to PVs by name."""
    action: Literal["subscribe", "unsubscribe"]
    pvs: list[str] = Field(description="PV names to (un)subscribe to")


class WSValueUpdate(BaseModel):
    """Server → client: a PV value change."""
    pv: str
    value: Any
    ts: str = Field(description="ISO-8601 UTC timestamp of the update")


class WSError(BaseModel):
    """Server → client: subscribe failed for a PV."""
    pv: str
    error: str
