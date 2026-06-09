"""Unit tests for first-turn analysis metrics (Phase 5 / U6)."""
import numpy as np

from pytxt.domain.analysis import analyze_first_turn
from pytxt.domain.types import FirstTurnResult


def _ft(x, y):
    x = np.asarray(x, dtype=float)
    return FirstTurnResult(
        x_first_turn=x,
        y_first_turn=np.asarray(y, dtype=float),
        sum_first_turn=np.ones_like(x),
        injection_turn=np.zeros(x.size, dtype=np.int32),
        failed_bpm_names=[],
    )


NAMES = ["SR01C:BPM1", "SR02C:BPM1", "SR03C:BPM1", "SR04C:BPM1"]


def test_basic_rms_and_maxabs():
    ft = _ft([3.0, -4.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0])
    r = analyze_first_turn(ft, NAMES)
    # rms of [3,-4,0,0] = sqrt((9+16)/4) = 2.5
    assert r.x_rms_mm == 2.5
    assert r.x_max_abs_mm == 4.0
    assert r.y_rms_mm == 0.0
    assert r.n_live_bpms == 4
    assert r.n_bpms == 4


def test_nan_aware_and_reach():
    # Beam dies after BPM 2 (indices 2,3 are NaN).
    ft = _ft([1.0, -1.0, np.nan, np.nan], [0.5, np.nan, np.nan, np.nan])
    r = analyze_first_turn(ft, NAMES)
    assert r.n_live_bpms == 2
    assert r.reach_index == 1
    assert r.reach_name == "SR02C:BPM1"
    # rms over finite x only: sqrt((1+1)/2) = 1
    assert r.x_rms_mm == 1.0


def test_all_failed():
    ft = _ft([np.nan, np.nan], [np.nan, np.nan])
    r = analyze_first_turn(ft, NAMES[:2])
    assert r.n_live_bpms == 0
    assert r.reach_index == -1
    assert r.reach_name == ""
    assert np.isnan(r.x_rms_mm)
    assert np.isnan(r.x_max_abs_mm)
