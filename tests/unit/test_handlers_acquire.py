"""Unit tests for handle_acquire with a mocked reader."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import numpy as np
import pytest

from pytxt.api.schemas.result import AcquireStatus
from pytxt.domain.types import RawBPM
from pytxt.handlers.acquire import AcquisitionInFlightError, handle_acquire
from pytxt.handlers.reference import handle_promote_ref
from pytxt.state.app_state import AppState


def _fake_raw(prefix: str):
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
async def test_happy_path_updates_state_and_returns_response():
    state = AppState(bpm_prefixes=["A", "B"])
    reader = AsyncMock()
    reader.read_all.return_value = {"A": _fake_raw("A"), "B": _fake_raw("B")}

    response = await handle_acquire(state, reader)

    assert response.status == "OK"
    assert response.ok_count == 2
    assert response.fail_count == 0
    assert state.acquire_in_flight is False
    assert state.last_acquire.status == "OK"
    assert state.last_acquire_raws["A"].prefix == "A"


@pytest.mark.asyncio
async def test_in_flight_collision_raises():
    state = AppState(bpm_prefixes=["A"], acquire_in_flight=True)
    reader = AsyncMock()

    with pytest.raises(AcquisitionInFlightError):
        await handle_acquire(state, reader)


@pytest.mark.asyncio
async def test_all_fail_status_failed():
    state = AppState(bpm_prefixes=["A", "B"])
    reader = AsyncMock()
    reader.read_all.return_value = {"A": None, "B": None}

    response = await handle_acquire(state, reader)

    assert response.status == "FAILED"
    assert response.ok_count == 0
    assert response.fail_count == 2
    assert state.last_acquire.status == "FAILED"


@pytest.mark.asyncio
async def test_partial_fail_status_partial():
    state = AppState(bpm_prefixes=["A", "B"])
    reader = AsyncMock()
    reader.read_all.return_value = {"A": _fake_raw("A"), "B": None}

    response = await handle_acquire(state, reader)

    assert response.status == "PARTIAL"
    assert response.ok_count == 1
    assert response.fail_count == 1
    assert response.failed_bpm_names == ["B"]


@pytest.mark.asyncio
async def test_exception_clears_in_flight():
    state = AppState(bpm_prefixes=["A"])
    reader = AsyncMock()
    reader.read_all.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await handle_acquire(state, reader)

    assert state.acquire_in_flight is False
    assert state.last_acquire.status == "FAILED"


@pytest.mark.asyncio
async def test_acquire_no_ref_leaves_last_diff_none():
    state = AppState(bpm_prefixes=["A", "B"])
    reader = AsyncMock()
    reader.read_all.return_value = {"A": _fake_raw("A"), "B": _fake_raw("B")}

    await handle_acquire(state, reader)

    assert state.reference_loaded is False
    assert state.last_diff is None


@pytest.mark.asyncio
async def test_acquire_after_promote_computes_last_diff():
    prefixes = ["A", "B"]
    state = AppState(bpm_prefixes=prefixes)
    reader = AsyncMock()
    reader.read_all.return_value = {"A": _fake_raw("A"), "B": _fake_raw("B")}

    # First acquire gives us a last_acquire to promote from.
    await handle_acquire(state, reader)
    await handle_promote_ref(state)
    assert state.reference_loaded is True

    # Second acquire now computes a diff against the promoted reference.
    await handle_acquire(state, reader)

    assert state.last_diff is not None
    assert state.last_diff.dx.shape == (len(prefixes),)
    assert state.last_diff.dy.shape == (len(prefixes),)
