"""Integration: GET /api/v1/state returns the AppState projection."""
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_state_endpoint_returns_full_snapshot():
    from pytxt.state.app_state import AppState
    from pytxt.api.server import create_app
    import time

    state = AppState(
        version="0.1.0",
        heartbeat=42,
        last_ping_at="2026-05-07T00:00:00+00:00",
        ping_count=3,
        started_at=time.time() - 1.0,
    )
    app = create_app(state=state, ioc=None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/state")
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "0.1.0"
    assert body["heartbeat"] == 42
    assert body["last_ping_at"] == "2026-05-07T00:00:00+00:00"
    assert body["ping_count"] == 3
    assert body["uptime_s"] >= 1.0


@pytest.mark.asyncio
async def test_state_endpoint_handles_no_ping_yet():
    """last_ping_at is null until first ping."""
    from pytxt.state.app_state import AppState
    from pytxt.api.server import create_app

    state = AppState(version="0.1.0")
    app = create_app(state=state, ioc=None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/state")
    assert r.status_code == 200
    assert r.json()["last_ping_at"] is None
