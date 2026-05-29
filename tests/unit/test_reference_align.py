"""Unit tests for align_to_current (soft-merge by canonical BPM name)."""
from pathlib import Path

import numpy as np
import pytest

from pytxt.domain.reference import align_to_current
from pytxt.domain.types import FirstTurnResult, Reference


def _make_ref(names: list[str], xs: list[float], ys: list[float]) -> Reference:
    n = len(names)
    return Reference(
        first_turn=FirstTurnResult(
            x_first_turn=np.array(xs, dtype=np.float64),
            y_first_turn=np.array(ys, dtype=np.float64),
            sum_first_turn=np.full(n, np.nan, dtype=np.float64),
            injection_turn=np.full(n, -1, dtype=np.int32),
            failed_bpm_names=[],
        ),
        bpm_names=names,
        raws=None,
        file_path=None,
        saved_at=None,
    )


def test_full_overlap_same_order() -> None:
    ref = _make_ref(["SR01C:BPM1", "SR02C:BPM1"], [0.1, 0.2], [0.3, 0.4])
    aligned, n_ok, n_miss = align_to_current(ref, ["SR01C:BPM1", "SR02C:BPM1"])
    assert n_ok == 2 and n_miss == 0
    np.testing.assert_allclose(aligned.x_first_turn, [0.1, 0.2])
    np.testing.assert_allclose(aligned.y_first_turn, [0.3, 0.4])


def test_full_overlap_different_order() -> None:
    """current_prefixes order drives output, not the ref's order."""
    ref = _make_ref(["A", "B"], [1.0, 2.0], [3.0, 4.0])
    aligned, n_ok, n_miss = align_to_current(ref, ["B", "A"])
    assert n_ok == 2 and n_miss == 0
    np.testing.assert_allclose(aligned.x_first_turn, [2.0, 1.0])
    np.testing.assert_allclose(aligned.y_first_turn, [4.0, 3.0])


def test_partial_overlap_leaves_nan() -> None:
    ref = _make_ref(["A", "B"], [1.0, 2.0], [3.0, 4.0])
    aligned, n_ok, n_miss = align_to_current(ref, ["A", "B", "C"])
    assert n_ok == 2 and n_miss == 1
    assert aligned.x_first_turn[0] == 1.0
    assert aligned.x_first_turn[1] == 2.0
    assert np.isnan(aligned.x_first_turn[2])
    assert np.isnan(aligned.y_first_turn[2])
    assert aligned.injection_turn[2] == -1


def test_zero_overlap_all_nan() -> None:
    ref = _make_ref(["A", "B"], [1.0, 2.0], [3.0, 4.0])
    aligned, n_ok, n_miss = align_to_current(ref, ["X", "Y"])
    assert n_ok == 0 and n_miss == 2
    assert np.all(np.isnan(aligned.x_first_turn))
    assert np.all(np.isnan(aligned.y_first_turn))


def test_ref_larger_than_current_drops_extras() -> None:
    ref = _make_ref(["A", "B", "C"], [1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
    aligned, n_ok, n_miss = align_to_current(ref, ["B"])
    assert n_ok == 1 and n_miss == 0
    np.testing.assert_allclose(aligned.x_first_turn, [2.0])
    np.testing.assert_allclose(aligned.y_first_turn, [5.0])


def test_aligned_length_matches_current() -> None:
    ref = _make_ref(["A"], [1.0], [2.0])
    aligned, _, _ = align_to_current(ref, ["A", "B", "C", "D"])
    assert aligned.x_first_turn.shape == (4,)
    assert aligned.y_first_turn.shape == (4,)


def test_current_prefixes_are_canonicalized_defensively() -> None:
    """If somehow current_prefixes has the MATLAB :SA:X suffix, still match."""
    ref = _make_ref(["SR01C:BPM1"], [0.5], [0.7])
    aligned, n_ok, n_miss = align_to_current(ref, ["SR01C:BPM1:SA:X"])
    assert n_ok == 1 and n_miss == 0
    assert aligned.x_first_turn[0] == 0.5
