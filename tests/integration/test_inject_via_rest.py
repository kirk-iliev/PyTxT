"""Integration: POST /api/v1/cmd/inject_oneshot route + error mapping (fake trigger)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from pytxt.api.server import create_app
from pytxt.state.app_state import AppState
from tests.unit.test_handlers_inject import FakeTrigger


def _app(state: AppState, trigger=...) -> object:
    app = create_app(state=state)
    app.state.injection_trigger = FakeTrigger() if trigger is ... else trigger
    return app


async def _post(app, body: dict):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post("/api/v1/cmd/inject_oneshot", json=body)


@pytest.mark.asyncio
async def test_default_shot_returns_200_fired():
    state = AppState(version="0.1.0")
    r = await _post(_app(state), {})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "FIRED"
    assert body["bucket"] == 308 and body["inhibit"] == 1
    assert state.last_inject.status == "FIRED"


@pytest.mark.asyncio
async def test_gun_fire_without_flag_returns_403():
    r = await _post(_app(AppState(version="0.1.0")), {"inhibit": 0})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_gun_fire_with_flag_returns_200():
    r = await _post(_app(AppState(version="0.1.0")),
                    {"inhibit": 0, "allow_gun_fire": True})
    assert r.status_code == 200
    assert r.json()["inhibit"] == 0


@pytest.mark.asyncio
async def test_top_off_precondition_returns_409():
    app = _app(AppState(version="0.1.0"), FakeTrigger(bucket_control=1))
    r = await _post(app, {})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_force_bypasses_precondition_200():
    app = _app(AppState(version="0.1.0"), FakeTrigger(bucket_control=1))
    r = await _post(app, {"force": True})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_in_flight_returns_409():
    r = await _post(_app(AppState(version="0.1.0", inject_in_flight=True)), {})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_unknown_mode_returns_422():
    r = await _post(_app(AppState(version="0.1.0")), {"mode": 99})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_out_of_range_bucket_returns_422():
    r = await _post(_app(AppState(version="0.1.0")), {"bucket": 999})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_no_trigger_configured_returns_503():
    r = await _post(_app(AppState(version="0.1.0"), trigger=None), {})
    assert r.status_code == 503
