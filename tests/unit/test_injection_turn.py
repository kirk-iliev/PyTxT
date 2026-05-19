"""Port of MATLAB SCexp_ALS_readoutBPMs.m injection-turn detection.

argmax(diff(sum)) with fallback to 1370 when result is outside [100, 4500].
"""
import numpy as np
import pytest

from pytxt.domain.injection_turn import detect_injection_turn


def _waveform_with_step(at: int, n: int = 100000) -> np.ndarray:
    """Build a sum-signal waveform with a step up at sample `at`."""
    wf = np.full(n, 1000, dtype=np.int32)
    wf[at:] = 200000
    return wf


def test_detects_clear_peak_in_valid_range():
    wf = _waveform_with_step(at=1370)
    assert detect_injection_turn(wf) == 1370


def test_detects_clear_peak_at_lower_edge():
    wf = _waveform_with_step(at=100)
    assert detect_injection_turn(wf) == 100


def test_detects_clear_peak_at_upper_edge():
    wf = _waveform_with_step(at=4500)
    assert detect_injection_turn(wf) == 4500


def test_falls_back_to_1370_when_peak_below_100():
    wf = _waveform_with_step(at=50)
    assert detect_injection_turn(wf) == 1370


def test_falls_back_to_1370_when_peak_above_4500():
    wf = _waveform_with_step(at=5000)
    assert detect_injection_turn(wf) == 1370


def test_flat_waveform_falls_back_to_1370():
    """No clear peak — argmax(diff) lands at sample 0, outside [100,4500]."""
    wf = np.full(100000, 1000, dtype=np.int32)
    assert detect_injection_turn(wf) == 1370
