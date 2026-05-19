"""Extract per-BPM first-turn position arrays from a dict of raw waveforms.

Failed BPMs (raws[prefix] is None) produce NaN/-1 sentinels and are added
to failed_bpm_names. Dict-insertion order defines BPM index; preserve it.

nm → mm conversion: divide by 1e6, matching MATLAB SCexp_ALS_readoutBPMs.m.
"""
from __future__ import annotations

import numpy as np

from pytxt.domain.injection_turn import detect_injection_turn
from pytxt.domain.types import FirstTurnResult, RawBPM


def extract_first_turn(raws: dict[str, RawBPM | None]) -> FirstTurnResult:
    n = len(raws)
    x = np.full(n, np.nan, dtype=np.float64)
    y = np.full(n, np.nan, dtype=np.float64)
    sum_val = np.full(n, np.nan, dtype=np.float64)
    injection_turn = np.full(n, -1, dtype=np.int32)
    failed: list[str] = []

    for i, (prefix, raw) in enumerate(raws.items()):
        if raw is None:
            failed.append(prefix)
            continue
        idx = detect_injection_turn(raw.sum_wf)
        injection_turn[i] = idx
        x[i] = float(raw.x_wf[idx]) / 1e6
        y[i] = float(raw.y_wf[idx]) / 1e6
        sum_val[i] = float(raw.sum_wf[idx])

    return FirstTurnResult(
        x_first_turn=x,
        y_first_turn=y,
        sum_first_turn=sum_val,
        injection_turn=injection_turn,
        failed_bpm_names=failed,
    )
