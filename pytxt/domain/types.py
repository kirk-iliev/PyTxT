"""Pure-numpy dataclasses shared by ca_client/, handlers/, and IOC publish.

NO I/O imports here — no channel-access library, no web framework, no asyncio.
Adapters that construct these types live above the domain package.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np


@dataclass(frozen=True)
class RawBPM:
    """Single BPM's TBT capture as read from CA. dtype/shape correspond to
    what the CA client returns from {prefix}:wfr:TBT:{c0,c1,c3,armed}."""
    prefix: str
    x_wf: np.ndarray         # shape (100000,), dtype int32, units nm
    y_wf: np.ndarray
    sum_wf: np.ndarray
    armed: int               # 0 = data was valid at read time
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
