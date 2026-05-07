"""Integration: GET /health returns 200 with the expected shape."""
import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_health_returns_ok():
    from pytxt.state.app_state import AppState
    from pytxt.api.server import create_app
    import time

    state = AppState(version="0.1.0", started_at=time.time() - 0.5)
    app = create_app(state=state, ioc=None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "uptime_s" in body
    assert body["uptime_s"] >= 0.5


@pytest.mark.asyncio
async def test_health_works_immediately_after_startup():
    """Right after startup uptime is ~0; the endpoint still returns 200."""
    from pytxt.state.app_state import AppState
    from pytxt.api.server import create_app
    import time

    state = AppState(version="0.1.0", started_at=time.time())
    app = create_app(state=state, ioc=None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
