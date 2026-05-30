"""Pure-numpy dataclasses shared by ca_client/, handlers/, and IOC publish.

NO I/O imports here — no channel-access library, no web framework, no asyncio.
Adapters that construct these types live above the domain package.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class RawBPM:
    """Single BPM's TBT capture as read from CA. dtype/shape correspond to
    what the CA client returns from {prefix}:wfr:TBT:{c0,c1,c3,armed}."""
    prefix: str
    x_wf: np.ndarray         # shape (100000,), dtype int32, units nm
    y_wf: np.ndarray
    sum_wf: np.ndarray
    armed: int               # 0 = acquisition complete, data is valid; nonzero = BPM
                             # is still armed/waiting (per MATLAB convention — phase 2
                             # is read-only so we capture whatever the BPM IOC reports)
    read_timestamp: datetime


@dataclass(frozen=True)
class FirstTurnResult:
    """Extracted per-BPM first-turn positions, aligned with the BPM list order.
    NaN/-1 sentinels mark BPMs that failed during the acquisition."""
    x_first_turn: np.ndarray         # (n_bpms,) float64, mm, NaN for failed
    y_first_turn: np.ndarray
    sum_first_turn: np.ndarray
    injection_turn: np.ndarray       # (n_bpms,) int32, -1 for failed
    failed_bpm_names: list[str]


@dataclass(frozen=True)
class Reference:
    """In-memory representation of a loaded reference trajectory.

    `first_turn` is always populated (it's the diff math input).
    `raws` is populated only when the .mat included the PyTxT-extended
    waveform variables. MATLAB-GUI-saved references omit these; for
    those refs `raws` is None and the lazy /result/ref/raw endpoint
    (M4) returns 404.

    `bpm_names` is the *canonicalized* (suffix-stripped) list from the
    .mat — preserved separately from `first_turn` for the soft-merge
    audit (M2) and diagnostics.
    """
    first_turn: FirstTurnResult
    bpm_names: list[str]
    raws: dict[str, RawBPM] | None
    file_path: Path | None
    saved_at: datetime | None


@dataclass(frozen=True)
class DiffSummary:
    """Cheap summary of a B − R0 diff. NaN-aware."""
    x_rms_mm: float
    y_rms_mm: float
    x_max_abs_mm: float
    y_max_abs_mm: float
    n_valid: int


class ReferenceSource(str, enum.Enum):
    """Provenance of the currently-loaded reference trajectory."""
    NONE = ""
    FILE = "file"          # reachable in M3 (LOAD_REF)
    PROMOTED = "promoted"  # reachable in M2 (PROMOTE_REF)


@dataclass(frozen=True)
class DiffResult:
    """Latest per-BPM B − R0 diff plus its cheap summary.

    `dx`/`dy` are (n_bpms,) float64, NaN where either side is NaN. When
    AppState.last_diff is None, the IOC NaN-fills the diff PVs.
    """
    dx: np.ndarray
    dy: np.ndarray
    summary: DiffSummary
