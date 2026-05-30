"""Unit tests for the M3 LOAD_REF / SAVE_REF handlers.

Drive the canonical handlers against a real AppState carrying a synthetic
last_acquire (mirrors the M2 RawBPM synth in test_handlers_reference). Fixtures
are written via the M1 domain saver into a tmp_path library; the garbage-.mat
case writes raw junk bytes to exercise ReferenceLoadError.
"""
from datetime import datetime, timezone

import numpy as np
import pytest

from pytxt.api.schemas.result import AcquireStatus, LastAcquireResult
from pytxt.domain.reference import ReferenceLoadError, save_reference_mat
from pytxt.domain.types import RawBPM, ReferenceSource
from pytxt.handlers.reference import (
    InvalidReferenceNameError,
    NoLastAcquireError,
    ReferenceExistsError,
    ReferenceNotFoundError,
    _current_first_turn,
    handle_save_ref,
    handle_load_ref,
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
    """Build an AppState that looks like it just completed an acquire."""
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


def _seed_reference(reference_dir, prefixes: list[str], name: str) -> None:
    """Write a reference .mat into the library from a synthetic acquire."""
    src = _acquired_state(prefixes)
    save_reference_mat(
        reference_dir / name,
        _current_first_turn(src),
        src.last_acquire_raws,
        prefixes,
    )


# --------------------------------------------------------------------------- #
# SAVE                                                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_save_writes_file_and_leaves_state_untouched(tmp_path):
    state = _acquired_state(["A", "B"])

    resp = await handle_save_ref(state, tmp_path, "foo.mat")

    written = tmp_path / "foo.mat"
    assert written.exists()
    assert resp.name == "foo.mat"
    assert resp.size_bytes == written.stat().st_size
    assert resp.size_bytes > 0
    assert resp.saved_at.tzinfo is not None
    # SAVE must NOT mutate AppState (decision §3).
    assert state.reference_loaded is False
    assert state.reference_source is ReferenceSource.NONE
    assert state.last_diff is None


@pytest.mark.asyncio
async def test_save_with_no_acquire_raises(tmp_path):
    state = AppState(bpm_prefixes=["A", "B"])  # fresh: ok_count == 0

    with pytest.raises(NoLastAcquireError):
        await handle_save_ref(state, tmp_path, "foo.mat")

    assert not (tmp_path / "foo.mat").exists()


@pytest.mark.asyncio
async def test_save_over_existing_raises(tmp_path):
    state = _acquired_state(["A", "B"])
    await handle_save_ref(state, tmp_path, "foo.mat")

    with pytest.raises(ReferenceExistsError):
        await handle_save_ref(state, tmp_path, "foo.mat")


@pytest.mark.asyncio
async def test_save_default_name_uses_timestamp_pattern(tmp_path):
    state = _acquired_state(["A", "B"])

    resp = await handle_save_ref(state, tmp_path, None)

    assert resp.name.endswith("_reference_trajectory.mat")
    assert (tmp_path / resp.name).exists()
    mats = list(tmp_path.glob("*_reference_trajectory.mat"))
    assert len(mats) == 1


@pytest.mark.asyncio
async def test_save_bad_name_raises(tmp_path):
    state = _acquired_state(["A", "B"])

    with pytest.raises(InvalidReferenceNameError):
        await handle_save_ref(state, tmp_path, "a/b.mat")


# --------------------------------------------------------------------------- #
# LOAD                                                                          #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_save_then_load_round_trip(tmp_path):
    prefixes = ["A", "B"]
    src = _acquired_state(prefixes)
    await handle_save_ref(src, tmp_path, "foo.mat")

    # Load into a fresh acquired state with the same prefixes.
    state = _acquired_state(prefixes)
    resp = await handle_load_ref(state, tmp_path, "foo.mat")

    assert resp.loaded is True
    assert resp.source is ReferenceSource.FILE
    assert resp.name == "foo.mat"
    assert resp.n_aligned == len(prefixes)
    assert resp.n_unaligned == 0

    assert state.reference_loaded is True
    assert state.reference_source is ReferenceSource.FILE
    assert state.reference_name == "foo.mat"
    assert state.reference_file_path == tmp_path / "foo.mat"
    assert state.reference_loaded_at is not None
    assert state.reference_bpm_names == prefixes
    assert state.reference_first_turn is not None

    # The diff (live vs identical saved ref) is finite and ~zero.
    assert state.last_diff is not None
    assert np.all(np.isfinite(state.last_diff.dx))
    assert np.allclose(state.last_diff.dx, 0.0)
    assert np.allclose(state.last_diff.dy, 0.0)


@pytest.mark.asyncio
async def test_load_without_acquire_leaves_diff_none(tmp_path):
    _seed_reference(tmp_path, ["A", "B"], "foo.mat")
    state = AppState(bpm_prefixes=["A", "B"])  # no acquire yet

    resp = await handle_load_ref(state, tmp_path, "foo.mat")

    assert resp.loaded is True
    assert resp.n_aligned == 2
    assert state.reference_loaded is True
    # No acquire → no live first-turn → diff stays unset.
    assert state.last_diff is None


@pytest.mark.asyncio
async def test_load_missing_file_raises(tmp_path):
    state = _acquired_state(["A", "B"])

    with pytest.raises(ReferenceNotFoundError):
        await handle_load_ref(state, tmp_path, "nope.mat")

    assert state.reference_loaded is False


@pytest.mark.asyncio
async def test_load_garbage_mat_raises_load_error(tmp_path):
    junk = tmp_path / "junk.mat"
    junk.write_bytes(b"this is not a MAT-file \x00\x01\x02 at all")
    state = _acquired_state(["A", "B"])

    with pytest.raises(ReferenceLoadError):
        await handle_load_ref(state, tmp_path, "junk.mat")

    assert state.reference_loaded is False


@pytest.mark.asyncio
async def test_load_bad_name_raises(tmp_path):
    state = _acquired_state(["A", "B"])

    with pytest.raises(InvalidReferenceNameError):
        await handle_load_ref(state, tmp_path, "../escape.mat")

    assert state.reference_loaded is False


@pytest.mark.asyncio
async def test_load_zero_overlap_loads_with_nan_diff(tmp_path):
    # Reference saved under prefixes that don't match the loading state's.
    _seed_reference(tmp_path, ["X1", "X2"], "other.mat")
    state = _acquired_state(["A", "B"])

    resp = await handle_load_ref(state, tmp_path, "other.mat")

    assert resp.loaded is True
    assert resp.n_aligned == 0
    assert resp.n_unaligned == 2
    assert state.reference_loaded is True
    assert state.reference_source is ReferenceSource.FILE
    # Aligned ref is all-NaN → diff all-NaN despite a live acquire.
    assert state.last_diff is not None
    assert np.all(np.isnan(state.last_diff.dx))
    assert np.all(np.isnan(state.last_diff.dy))
    assert state.last_diff.summary.n_valid == 0
