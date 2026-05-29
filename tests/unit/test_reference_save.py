"""Unit tests for save_reference_mat (round-trip + MATLAB-loader simulation)."""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import scipy.io

from pytxt.domain.reference import (
    canonicalize_bpm_name,
    load_reference_mat,
    save_reference_mat,
)
from pytxt.domain.types import FirstTurnResult, RawBPM


def _synth_first_turn(n: int) -> FirstTurnResult:
    return FirstTurnResult(
        x_first_turn=np.array([0.01 * i for i in range(n)], dtype=np.float64),
        y_first_turn=np.array([-0.02 * i for i in range(n)], dtype=np.float64),
        sum_first_turn=np.full(n, 1234.0, dtype=np.float64),
        injection_turn=np.full(n, 1370, dtype=np.int32),
        failed_bpm_names=[],
    )


def _synth_raws(prefixes: list[str]) -> dict[str, RawBPM]:
    now = datetime.now(timezone.utc)
    n_samples = 100000
    return {
        p: RawBPM(
            prefix=p,
            x_wf=np.full(n_samples, i + 1, dtype=np.int32),
            y_wf=np.full(n_samples, -(i + 1), dtype=np.int32),
            sum_wf=np.full(n_samples, 1000 * (i + 1), dtype=np.int32),
            armed=0,
            read_timestamp=now,
        )
        for i, p in enumerate(prefixes)
    }


def test_save_then_load_round_trips_basic(tmp_path: Path) -> None:
    p = tmp_path / "round_trip.mat"
    prefixes = ["SR01C:BPM1", "SR02C:BPM1", "SR03C:BPM1"]
    first_turn = _synth_first_turn(3)
    raws = _synth_raws(prefixes)

    save_reference_mat(p, first_turn, raws, prefixes)
    assert p.exists()
    ref = load_reference_mat(p)

    assert ref.bpm_names == prefixes
    np.testing.assert_allclose(ref.first_turn.x_first_turn, first_turn.x_first_turn)
    np.testing.assert_allclose(ref.first_turn.y_first_turn, first_turn.y_first_turn)
    assert ref.raws is not None
    np.testing.assert_array_equal(ref.raws["SR01C:BPM1"].x_wf, raws["SR01C:BPM1"].x_wf)


def test_save_handles_failed_bpms_as_nan(tmp_path: Path) -> None:
    """A BPM in prefixes but absent from last_acquire_raws → NaN row in R0."""
    p = tmp_path / "with_failure.mat"
    prefixes = ["SR01C:BPM1", "SR02C:BPM1"]
    first_turn = FirstTurnResult(
        x_first_turn=np.array([0.1, np.nan]),
        y_first_turn=np.array([0.2, np.nan]),
        sum_first_turn=np.array([100.0, np.nan]),
        injection_turn=np.array([1370, -1], dtype=np.int32),
        failed_bpm_names=["SR02C:BPM1"],
    )
    raws = _synth_raws(["SR01C:BPM1"])    # SR02C:BPM1 absent

    save_reference_mat(p, first_turn, raws, prefixes)
    ref = load_reference_mat(p)
    assert np.isnan(ref.first_turn.x_first_turn[1])
    assert np.isnan(ref.first_turn.y_first_turn[1])
    # Failed BPM still has a row in the waveform arrays (zero-filled)
    assert ref.raws is not None
    assert np.all(ref.raws["SR02C:BPM1"].x_wf == 0)
    assert ref.first_turn.injection_turn[1] == -1


def test_save_writes_matlab_compatible_R0_BPMs(tmp_path: Path) -> None:
    """Simulate MATLAB's load(file, 'R0', 'BPMs') — extras must be ignored."""
    p = tmp_path / "matlab_compat.mat"
    prefixes = ["SR01C:BPM1", "SR02C:BPM1"]
    save_reference_mat(p, _synth_first_turn(2), _synth_raws(prefixes), prefixes)

    # MATLAB's load(file, 'R0', 'BPMs') equivalent:
    only_required = scipy.io.loadmat(p, variable_names=["R0", "BPMs"], squeeze_me=True, struct_as_record=False)
    user_keys = [k for k in only_required if not k.startswith("__")]
    assert set(user_keys) == {"R0", "BPMs"}
    R0 = np.asarray(only_required["R0"])
    assert R0.shape == (2, 2)
    assert hasattr(only_required["BPMs"], "Names")


def test_save_includes_extended_variables(tmp_path: Path) -> None:
    p = tmp_path / "extended.mat"
    prefixes = ["SR01C:BPM1"]
    save_reference_mat(p, _synth_first_turn(1), _synth_raws(prefixes), prefixes)
    full = scipy.io.loadmat(p, squeeze_me=True, struct_as_record=False)
    user_keys = {k for k in full if not k.startswith("__")}
    # Required + extras
    assert {"R0", "BPMs", "X_wf", "Y_wf", "sum_wf", "injection_turn"}.issubset(user_keys)
    assert "saved_by" in user_keys


def test_save_preserves_prefix_order(tmp_path: Path) -> None:
    p = tmp_path / "ordered.mat"
    prefixes = ["SR03C:BPM1", "SR01C:BPM1", "SR02C:BPM1"]   # NOT sorted
    save_reference_mat(p, _synth_first_turn(3), _synth_raws(prefixes), prefixes)
    ref = load_reference_mat(p)
    assert ref.bpm_names == prefixes
