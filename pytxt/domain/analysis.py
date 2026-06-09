"""First-turn trajectory analysis (Phase 5 / U6).

Pure, I/O-free metrics over an extracted first turn — orbit excursion and beam
transmission — computed on each ACQUIRE and published as RESULT:ANALYSIS:* PVs.

Scope note (Decision D4): these are the well-defined, single-shot-computable
metrics. Gaussian profile fits, dispersion, and kick-angle from the plan's
"analysis polish" are NOT implemented here — the legacy TxT GUI never computed
them on first-turn data (its Tune-Scan / BBA tabs are stubs), and dispersion
needs multi-acquisition (RF-frequency steps). They await a physicist spec and a
multi-shot acquisition mode; see the decisions log.
"""
from __future__ import annotations

import numpy as np

from pytxt.domain.types import AnalysisResult, FirstTurnResult


def _rms(a: np.ndarray) -> float:
    valid = a[~np.isnan(a)]
    return float(np.sqrt(np.mean(valid**2))) if valid.size else float("nan")


def _max_abs(a: np.ndarray) -> float:
    valid = a[~np.isnan(a)]
    return float(np.max(np.abs(valid))) if valid.size else float("nan")


def analyze_first_turn(first_turn: FirstTurnResult, names: list[str]) -> AnalysisResult:
    """Compute single-shot first-turn metrics, NaN-aware.

    A BPM is "live" if its X reading is finite (saw beam). `reach_index` is the
    last live BPM — how far down the ring the first turn made it, useful for
    injection commissioning ("beam reached BPM N of M").
    """
    x = np.asarray(first_turn.x_first_turn, dtype=float)
    y = np.asarray(first_turn.y_first_turn, dtype=float)
    n_bpms = int(x.size)

    live = ~np.isnan(x)
    n_live = int(np.sum(live))
    live_idx = np.nonzero(live)[0]
    reach_index = int(live_idx[-1]) if live_idx.size else -1
    reach_name = names[reach_index] if 0 <= reach_index < len(names) else ""

    return AnalysisResult(
        x_rms_mm=_rms(x),
        y_rms_mm=_rms(y),
        x_max_abs_mm=_max_abs(x),
        y_max_abs_mm=_max_abs(y),
        n_live_bpms=n_live,
        n_bpms=n_bpms,
        reach_index=reach_index,
        reach_name=reach_name,
    )
