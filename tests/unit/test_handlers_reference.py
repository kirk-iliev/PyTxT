"""Unit tests for the PROMOTE_REF / CLEAR_REF handlers.

Drive the canonical handlers against a real AppState carrying a synthetic
last_acquire (mirrors the phase-2 RawBPM synth used in test_handlers_acquire).
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from pytxt.api.schemas.result import AcquireStatus, LastAcquireResult
from pytxt.domain.types import RawBPM, ReferenceSource
from pytxt.handlers.reference import (
    NoLastAcquireError,
    handle_clear_ref,
    handle_promote_ref,
)
from pytxt.state.app_state import AppState


def _fake_raw(prefix: str) -> RawBPM:
    """A BPM whose sum waveform jumps at sample 1370 → finite first-turn.
    x first-turn = 80_000 / 1e6 = 0.08 mm; y = 0.0 mm."""
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


def _acquired_state(prefixes: list[str], failed: list[str] | None = None) -> AppState:
    """Build an AppState that looks like it just completed an acquire.

    `failed` prefixes are absent from last_acquire_raws (matching how
    handle_acquire strips None entries)."""
    failed = failed or []
    raws = {p: _fake_raw(p) for p in prefixes if p not in failed}
    ok = len(prefixes) - len(failed)
    return AppState(
        bpm_prefixes=prefixes,
        last_acquire_raws=raws,
        last_acquire=LastAcquireResult(
            status=AcquireStatus.OK if not failed else AcquireStatus.PARTIAL,
            ok_count=ok,
            fail_count=len(failed),
            failed_bpm_names=failed,
            injection_turn_median=1370,
            timestamp=datetime.now(timezone.utc),
        ),
    )


@pytest.mark.asyncio
async def test_promote_loads_in_memory_reference():
    state = _acquired_state(["A", "B"])

    resp = await handle_promote_ref(state)

    assert state.reference_loaded is True
    assert state.reference_name == "<promoted>"
    assert state.reference_source is ReferenceSource.PROMOTED
    assert state.reference_file_path is None
    assert state.reference_loaded_at is not None
    assert state.reference_bpm_names == ["A", "B"]
    assert state.reference_first_turn is not None
    # self-diff is exactly zero where the live value was finite
    assert state.last_diff is not None
    assert np.allclose(state.last_diff.dx, 0.0)
    assert np.allclose(state.last_diff.dy, 0.0)
    assert state.last_diff.dx.shape == (2,)

    assert resp.loaded is True
    assert resp.source is ReferenceSource.PROMOTED
    assert resp.n_aligned == 2
    assert resp.n_unaligned == 0
    assert resp.summary.n_valid == 2
    assert resp.summary.x_rms_mm == pytest.approx(0.0)
    assert resp.summary.y_rms_mm == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_promote_with_failed_bpm_counts_only_valid():
    state = _acquired_state(["A", "B", "C"], failed=["C"])

    resp = await handle_promote_ref(state)

    assert resp.n_aligned == 2  # A, B finite; C is NaN
    assert resp.n_unaligned == 1
    assert state.last_diff.dx.shape == (3,)
    # the failed index is NaN in the self-diff
    assert np.isnan(state.last_diff.dx[2])
    assert np.isnan(state.last_diff.dy[2])


@pytest.mark.asyncio
async def test_promote_with_no_acquire_raises():
    state = AppState(bpm_prefixes=["A", "B"])  # fresh: ok_count == 0

    with pytest.raises(NoLastAcquireError):
        await handle_promote_ref(state)

    # state untouched
    assert state.reference_loaded is False
    assert state.last_diff is None


@pytest.mark.asyncio
async def test_clear_from_loaded_resets_all_fields():
    state = _acquired_state(["A", "B"])
    await handle_promote_ref(state)
    assert state.reference_loaded is True

    resp = await handle_clear_ref(state)

    assert resp.loaded is False
    assert state.reference_loaded is False
    assert state.reference_name == ""
    assert state.reference_loaded_at is None
    assert state.reference_source is ReferenceSource.NONE
    assert state.reference_first_turn is None
    assert state.reference_file_path is None
    assert state.reference_bpm_names is None
    assert state.last_diff is None


@pytest.mark.asyncio
async def test_clear_when_already_clear_is_idempotent():
    state = AppState(bpm_prefixes=["A"])

    resp = await handle_clear_ref(state)

    assert resp.loaded is False
    assert state.reference_loaded is False
    assert state.last_diff is None


@pytest.mark.asyncio
async def test_promote_fires_listeners_for_changed_fields():
    state = _acquired_state(["A", "B"])
    seen: dict[str, int] = {"reference_loaded": 0, "last_diff": 0}

    async def _loaded_cb(_v):
        seen["reference_loaded"] += 1

    async def _diff_cb(_v):
        seen["last_diff"] += 1

    state.subscribe("reference_loaded", _loaded_cb)
    state.subscribe("last_diff", _diff_cb)

    await handle_promote_ref(state)

    assert seen["reference_loaded"] == 1
    assert seen["last_diff"] == 1
