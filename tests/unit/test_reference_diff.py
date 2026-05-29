"""Unit tests for compute_diff and summarize_diff."""
import math

import numpy as np
import pytest

from pytxt.domain.reference import compute_diff, summarize_diff
from pytxt.domain.types import FirstTurnResult


def _ft(xs: list[float], ys: list[float]) -> FirstTurnResult:
    n = len(xs)
    return FirstTurnResult(
        x_first_turn=np.array(xs, dtype=np.float64),
        y_first_turn=np.array(ys, dtype=np.float64),
        sum_first_turn=np.full(n, np.nan, dtype=np.float64),
        injection_turn=np.full(n, -1, dtype=np.int32),
        failed_bpm_names=[],
    )


# --- compute_diff ---

def test_compute_diff_straight_subtraction() -> None:
    dx, dy = compute_diff(_ft([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]),
                          _ft([0.5, 1.5, 2.5], [3.5, 4.5, 5.5]))
    np.testing.assert_allclose(dx, [0.5, 0.5, 0.5])
    np.testing.assert_allclose(dy, [0.5, 0.5, 0.5])


def test_compute_diff_nan_in_live_propagates() -> None:
    dx, dy = compute_diff(_ft([1.0, np.nan, 3.0], [4.0, np.nan, 6.0]),
                          _ft([0.5, 1.5, 2.5],     [3.5, 4.5, 5.5]))
    assert np.isnan(dx[1])
    assert np.isnan(dy[1])


def test_compute_diff_nan_in_ref_propagates() -> None:
    dx, dy = compute_diff(_ft([1.0, 2.0, 3.0],     [4.0, 5.0, 6.0]),
                          _ft([0.5, np.nan, 2.5], [3.5, np.nan, 5.5]))
    assert np.isnan(dx[1])
    assert np.isnan(dy[1])


def test_compute_diff_preserves_shape() -> None:
    dx, dy = compute_diff(_ft([1.0, 2.0], [3.0, 4.0]),
                          _ft([0.0, 0.0], [0.0, 0.0]))
    assert dx.shape == (2,)
    assert dy.shape == (2,)


# --- summarize_diff ---

def test_summarize_basic() -> None:
    dx = np.array([1.0, -1.0, 2.0, -2.0])
    dy = np.array([0.0, 0.0, 0.0, 0.0])
    s = summarize_diff(dx, dy)
    assert math.isclose(s.x_rms_mm, math.sqrt((1+1+4+4)/4))
    assert s.y_rms_mm == 0.0
    assert s.x_max_abs_mm == 2.0
    assert s.y_max_abs_mm == 0.0
    assert s.n_valid == 4


def test_summarize_ignores_nan_for_rms() -> None:
    dx = np.array([1.0, np.nan, 1.0])
    dy = np.array([1.0, 1.0,    1.0])
    s = summarize_diff(dx, dy)
    # x_rms over the 2 valid entries
    assert math.isclose(s.x_rms_mm, 1.0)
    # n_valid counts where BOTH are non-NaN
    assert s.n_valid == 2


def test_summarize_n_valid_requires_both() -> None:
    dx = np.array([1.0, np.nan, 1.0, np.nan])
    dy = np.array([1.0, 1.0,    np.nan, np.nan])
    s = summarize_diff(dx, dy)
    assert s.n_valid == 1   # only index 0 has both non-NaN


def test_summarize_all_nan() -> None:
    dx = np.array([np.nan, np.nan])
    dy = np.array([np.nan, np.nan])
    s = summarize_diff(dx, dy)
    assert math.isnan(s.x_rms_mm)
    assert math.isnan(s.y_rms_mm)
    assert math.isnan(s.x_max_abs_mm)
    assert math.isnan(s.y_max_abs_mm)
    assert s.n_valid == 0


def test_summarize_max_abs_picks_largest_magnitude() -> None:
    s = summarize_diff(np.array([-5.0, 3.0, -1.0]), np.array([0.0, 0.0, 0.0]))
    assert s.x_max_abs_mm == 5.0
