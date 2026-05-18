"""Integration: POST /api/v1/cmd/ping invokes handle_ping and mutates AppState."""
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_post_ping_increments_count():
    from pytxt.state.app_state import AppState
    from pytxt.api.server import create_app

    state = AppState(version="0.1.0", ping_count=0)
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/ping", json={})

    assert r.status_code == 200
    body = r.json()
    assert "acknowledged_at" in body
    assert "T" in body["acknowledged_at"]  # ISO format
    assert state.ping_count == 1
    assert state.last_ping_at is not None


@pytest.mark.asyncio
async def test_post_ping_accumulates():
    from pytxt.state.app_state import AppState
    from pytxt.api.server import create_app

    state = AppState(version="0.1.0")
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for _ in range(5):
            r = await ac.post("/api/v1/cmd/ping", json={})
            assert r.status_code == 200

    assert state.ping_count == 5
