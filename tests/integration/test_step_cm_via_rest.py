"""Integration: POST /api/v1/cmd/step_cm route + error mapping (fake writer)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from pytxt.api.server import create_app
from pytxt.state.app_state import AppState
from tests.unit.test_handlers_step_cm import FakeWriter


def _app(state: AppState, writer=...) -> object:
    app = create_app(state=state)
    app.state.corrector_writer = FakeWriter() if writer is ... else writer
    return app


async def _post(app, body: dict):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        return await ac.post("/api/v1/cmd/step_cm", json=body)


@pytest.mark.asyncio
async def test_applied_returns_200():
    state = AppState(version="0.1.0")
    app = _app(state, FakeWriter({"HCM": [10.0] + [0.0] * 7, "VCM": [0.0] * 8}))
    r = await _post(app, {
        "family": "HCM", "device_list": [0], "deltas": [2.0],
        "expected_prior_a": [10.0], "tol_a": 0.01,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "APPLIED"
    assert body["applied"][0]["new_value_a"] == 12.0
    assert state.last_cm_step.status == "APPLIED"


@pytest.mark.asyncio
async def test_dry_run_returns_200_dry_run():
    app = _app(AppState(version="0.1.0"))
    r = await _post(app, {
        "family": "HCM", "device_list": [0], "deltas": [1.0],
        "expected_prior_a": [0.0], "dry_run": True,
    })
    assert r.status_code == 200
    assert r.json()["status"] == "DRY_RUN"


@pytest.mark.asyncio
async def test_cas_refusal_returns_409():
    app = _app(AppState(version="0.1.0"),
               FakeWriter({"HCM": [5.0] + [0.0] * 7, "VCM": [0.0] * 8}))
    r = await _post(app, {
        "family": "HCM", "device_list": [0], "deltas": [1.0],
        "expected_prior_a": [0.0], "tol_a": 0.1,   # readback 5.0 != 0.0
    })
    assert r.status_code == 409
    assert "refused" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_in_flight_returns_409():
    app = _app(AppState(version="0.1.0", cm_step_in_flight=True))
    r = await _post(app, {
        "family": "HCM", "device_list": [0], "deltas": [1.0], "expected_prior_a": [0.0],
    })
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_bad_index_returns_422():
    app = _app(AppState(version="0.1.0"))
    r = await _post(app, {
        "family": "HCM", "device_list": [99], "deltas": [1.0], "expected_prior_a": [0.0],
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_length_mismatch_returns_422():
    app = _app(AppState(version="0.1.0"))
    r = await _post(app, {
        "family": "HCM", "device_list": [0, 1], "deltas": [1.0], "expected_prior_a": [0.0, 0.0],
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_no_writer_configured_returns_503():
    app = _app(AppState(version="0.1.0"), writer=None)
    r = await _post(app, {
        "family": "HCM", "device_list": [0], "deltas": [1.0], "expected_prior_a": [0.0],
    })
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_invalid_family_rejected_by_schema_422():
    app = _app(AppState(version="0.1.0"))
    r = await _post(app, {
        "family": "ZZZ", "device_list": [0], "deltas": [1.0], "expected_prior_a": [0.0],
    })
    assert r.status_code == 422  # pydantic Literal rejection
