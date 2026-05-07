"""Unit tests for pytxt.api.schemas.*."""
import pytest
from pydantic import ValidationError


def test_state_snapshot_required_fields():
    from pytxt.api.schemas.state import StateSnapshot
    snap = StateSnapshot(
        version="0.1.0",
        heartbeat=5,
        uptime_s=12.3,
        last_ping_at=None,
        ping_count=0,
    )
    assert snap.version == "0.1.0"
    assert snap.heartbeat == 5
    # Round-trip
    payload = snap.model_dump()
    restored = StateSnapshot.model_validate(payload)
    assert restored == snap


def test_state_snapshot_last_ping_at_optional():
    from pytxt.api.schemas.state import StateSnapshot
    snap = StateSnapshot(version="0.1.0", heartbeat=0, uptime_s=0.0, ping_count=0)
    assert snap.last_ping_at is None


def test_ping_response_round_trip():
    from pytxt.api.schemas.cmd import PingResponse
    pr = PingResponse(acknowledged_at="2026-05-07T00:00:00Z")
    assert pr.model_dump() == {"acknowledged_at": "2026-05-07T00:00:00Z"}


def test_ws_subscribe_action_enum():
    from pytxt.api.schemas.ws import WSSubscribe
    s = WSSubscribe(action="subscribe", pvs=["TxT:STATE:HEARTBEAT"])
    assert s.action == "subscribe"
    with pytest.raises(ValidationError):
        WSSubscribe(action="garbage", pvs=[])


def test_ws_value_update_accepts_any_value():
    from pytxt.api.schemas.ws import WSValueUpdate
    for value in (42, 3.14, "hello", True):
        m = WSValueUpdate(pv="X", value=value, ts="2026-05-07T00:00:00Z")
        assert m.value == value


def test_ws_error_shape():
    from pytxt.api.schemas.ws import WSError
    e = WSError(pv="X", error="not found")
    assert e.model_dump() == {"pv": "X", "error": "not found"}
