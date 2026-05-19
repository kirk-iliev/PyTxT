"""Integration: POST /api/v1/cmd/acquire calls handle_acquire and returns AcquireResponse."""
from unittest.mock import AsyncMock
from datetime import datetime, timezone

import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport

from pytxt.domain.types import RawBPM


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


@pytest.mark.asyncio
async def test_post_acquire_returns_response():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["A"])
    reader = AsyncMock()
    reader.read_all.return_value = {"A": _fake_raw("A")}

    app = create_app(state=state)
    app.state.bpm_reader = reader

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/acquire", json={})

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "OK"
    assert body["ok_count"] == 1
    assert body["fail_count"] == 0


@pytest.mark.asyncio
async def test_post_acquire_concurrent_returns_409():
    from pytxt.api.server import create_app
    from pytxt.state.app_state import AppState

    state = AppState(version="0.1.0", bpm_prefixes=["A"], acquire_in_flight=True)
    reader = AsyncMock()
    app = create_app(state=state)
    app.state.bpm_reader = reader

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/acquire", json={})
    assert r.status_code == 409
