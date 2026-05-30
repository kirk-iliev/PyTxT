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
    app = create_app(state=state)

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
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/state")
    assert r.status_code == 200
    assert r.json()["last_ping_at"] is None


@pytest.mark.asyncio
async def test_state_endpoint_includes_phase_2_fields():
    from pytxt.state.app_state import AppState
    from pytxt.api.server import create_app
    import time

    state = AppState(version="0.1.0", started_at=time.time(), bpm_prefixes=["A", "B"])
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/state")

    assert r.status_code == 200
    body = r.json()
    assert body["bpm_prefixes"] == ["A", "B"]
    assert body["acquire_in_flight"] is False
    assert body["last_acquire"]["status"] == "NEVER"


@pytest.mark.asyncio
async def test_state_endpoint_reference_null_before_promote():
    """Phase-3 reference/last_diff blocks are null until a reference is loaded."""
    from pytxt.state.app_state import AppState
    from pytxt.api.server import create_app

    state = AppState(version="0.1.0", bpm_prefixes=["A"])
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/state")

    assert r.status_code == 200
    body = r.json()
    assert body["reference"] is None
    assert body["last_diff"] is None


@pytest.mark.asyncio
async def test_state_endpoint_exposes_reference_after_promote_and_acquire():
    """After acquire → promote → acquire, /state surfaces a promoted reference
    and a non-null last_diff summary."""
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock

    import numpy as np

    from pytxt.api.server import create_app
    from pytxt.domain.types import RawBPM
    from pytxt.state.app_state import AppState

    def _fake_raw(prefix):
        sum_wf = np.full(100000, 1000, dtype=np.int32)
        sum_wf[1370:] = 200000
        return RawBPM(
            prefix=prefix,
            x_wf=np.full(100000, 80_000, dtype=np.int32),
            y_wf=np.zeros(100000, dtype=np.int32),
            sum_wf=sum_wf,
            armed=0,
            read_timestamp=datetime.now(timezone.utc),
        )

    state = AppState(version="0.1.0", bpm_prefixes=["A"])
    reader = AsyncMock()
    reader.read_all.return_value = {"A": _fake_raw("A")}

    app = create_app(state=state)
    app.state.bpm_reader = reader

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        assert (await ac.post("/api/v1/cmd/acquire", json={})).status_code == 200
        assert (await ac.post("/api/v1/cmd/promote_ref", json={})).status_code == 200
        assert (await ac.post("/api/v1/cmd/acquire", json={})).status_code == 200
        r = await ac.get("/api/v1/state")

    assert r.status_code == 200
    body = r.json()
    assert body["reference"] is not None
    assert body["reference"]["source"] == "promoted"
    assert body["reference"]["name"] == "<promoted>"
    assert body["last_diff"] is not None
    assert body["last_diff"]["n_valid"] >= 1


@pytest.mark.asyncio
async def test_promote_ref_no_acquire_returns_422():
    """Promote with no successful acquisition → 422."""
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["A"])
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/promote_ref", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_clear_ref_idempotent_via_rest():
    """Clear succeeds (200) even when nothing is loaded, and again after."""
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["A"])
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r1 = await ac.post("/api/v1/cmd/clear_ref", json={})
        r2 = await ac.post("/api/v1/cmd/clear_ref", json={})
    assert r1.status_code == 200
    assert r1.json()["loaded"] is False
    assert r2.status_code == 200
