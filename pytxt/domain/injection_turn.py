"""Per-BPM injection-turn detection.

Port of MATLAB SCexp_ALS_readoutBPMs.m:

    [~,injind] = max(diff(sum'));
    if any(injind<100) || any(injind>4500)
        injind(loop) = 1370;     % per-BPM fallback
    end

The comment in the MATLAB source notes that BPMs may be offset from
each other by a few turns — that's why detection is per-BPM, not global.
"""
from __future__ import annotations

import numpy as np


_VALID_MIN = 100
_VALID_MAX = 4500
_FALLBACK_INDEX = 1370


def detect_injection_turn(sum_waveform: np.ndarray) -> int:
    """Return the sample index of the injection turn.

    Algorithm: argmax of the first difference of the sum signal, plus one.
    ``np.diff(wf)[i] = wf[i+1] - wf[i]``, so the peak in the diff array
    sits one sample *before* the first elevated sample.  Adding one converts
    the diff index back to the turn index, matching MATLAB's 1-based
    ``injind`` (shifted to 0-based here).

    If the result falls outside [100, 4500], fall back to the documented
    default of 1370 (matches MATLAB).
    """
    diff_idx = int(np.argmax(np.diff(sum_waveform)))
    turn_idx = diff_idx + 1
    if turn_idx < _VALID_MIN or turn_idx > _VALID_MAX:
        return _FALLBACK_INDEX
    return turn_idx
