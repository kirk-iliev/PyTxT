"""Integration: GET /api/v1/result/bpm/raw?bpm=<prefix>.

Covers 400 (missing/empty param), 404 (unknown prefix OR no data yet), and
200 happy-path with shape/schema verification.
"""
from datetime import datetime, timezone

import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport

from pytxt.domain.types import RawBPM


def _fake_raw(prefix: str) -> RawBPM:
    return RawBPM(
        prefix=prefix,
        x_wf=np.arange(100000, dtype=np.int32),
        y_wf=np.full(100000, -42, dtype=np.int32),
        sum_wf=np.full(100000, 1000, dtype=np.int32),
        armed=0,
        read_timestamp=datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.mark.asyncio
async def test_raw_endpoint_returns_waveform_for_known_prefix():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(
        version="0.1.0",
        bpm_prefixes=["SR01C:BPM1", "SR01C:BPM2"],
        last_acquire_raws={"SR01C:BPM1": _fake_raw("SR01C:BPM1")},
    )
    app = create_app(state=state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw?bpm=SR01C:BPM1")
    assert r.status_code == 200
    body = r.json()
    assert body["bpm_prefix"] == "SR01C:BPM1"
    assert len(body["x_nm"]) == 100000
    assert len(body["y_nm"]) == 100000
    assert len(body["sum_au"]) == 100000
    assert body["x_nm"][0] == 0
    assert body["x_nm"][99999] == 99999
    assert body["y_nm"][0] == -42
    assert body["armed"] == 0
    assert body["read_timestamp"].startswith("2026-05-24T12:00:00")


@pytest.mark.asyncio
async def test_raw_endpoint_400_on_missing_param():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["SR01C:BPM1"])
    app = create_app(state=state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_raw_endpoint_400_on_empty_param():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["SR01C:BPM1"])
    app = create_app(state=state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw?bpm=")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_raw_endpoint_404_on_unknown_prefix():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(
        version="0.1.0",
        bpm_prefixes=["SR01C:BPM1"],
        last_acquire_raws={"SR01C:BPM1": _fake_raw("SR01C:BPM1")},
    )
    app = create_app(state=state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw?bpm=NOT:A:BPM")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_raw_endpoint_404_when_no_data_yet_for_known_prefix():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    # SR01C:BPM2 is a known prefix but has no raw data (e.g. never acquired,
    # or it was in failed_bpm_names of the last acquire).
    state = AppState(
        version="0.1.0",
        bpm_prefixes=["SR01C:BPM1", "SR01C:BPM2"],
        last_acquire_raws={"SR01C:BPM1": _fake_raw("SR01C:BPM1")},
    )
    app = create_app(state=state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.get("/api/v1/result/bpm/raw?bpm=SR01C:BPM2")
    assert r.status_code == 404
