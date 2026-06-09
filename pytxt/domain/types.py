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


@dataclass(frozen=True)
class AnalysisResult:
    """First-turn trajectory analysis (Phase 5 / U6). Single-shot, NaN-aware
    metrics computed on each ACQUIRE: orbit excursion (RMS / max-abs per plane)
    and beam transmission (how many BPMs saw beam, how far the first turn
    reached). Mirrored to RESULT:ANALYSIS:* PVs."""
    x_rms_mm: float
    y_rms_mm: float
    x_max_abs_mm: float
    y_max_abs_mm: float
    n_live_bpms: int
    n_bpms: int
    reach_index: int   # 0-based index of the last BPM that saw beam; -1 if none
    reach_name: str


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


@dataclass(frozen=True)
class ResponseMatrix:
    """A cached pseudo-inverse response matrix (Phase 4, Decision D1/D2).

    `mplus` maps a stacked orbit-deviation vector dR = [dx; dy] (length
    2*n_bpms, **mm**) to a corrector-step vector dphi (length n_hcm+n_vcm,
    **hardware amps**) — the amps↔kick unit convention is folded in at
    generation time (D2), so the runtime never converts. Corrector order is
    **all HCM first, then all VCM** (matching the legacy `calcCMstep` split).

    Generated offline (modeled via pySC, or measured) and loaded from a
    cached artifact; pySC is never imported at runtime (D1). `bpm_s`/`cm_s`
    carry monotone s-positions (m) used only for first-turn downstream-zeroing
    — the one threading-specific nuance (you cannot steer beam past where it
    was lost).
    """
    mplus: np.ndarray                # (n_hcm+n_vcm, 2*n_bpms) float64, mm -> amp
    bpm_names: list[str]             # length n_bpms, defines dR ordering
    hcm_names: list[str]             # length n_hcm
    vcm_names: list[str]             # length n_vcm
    bpm_s: np.ndarray                # (n_bpms,) float64, s-position (m)
    cm_s: np.ndarray                 # (n_hcm+n_vcm,) float64, s-position (m)
    units: str                       # e.g. "mm->amp"
    energy_gev: float                # operating energy the matrix was built for
    provenance: str                  # how/when generated (lattice file, tool, date)

    @property
    def n_bpms(self) -> int:
        return len(self.bpm_names)

    @property
    def n_hcm(self) -> int:
        return len(self.hcm_names)

    @property
    def n_vcm(self) -> int:
        return len(self.vcm_names)


@dataclass(frozen=True)
class CMStep:
    """Result of one threading correction step (Phase 4).

    `dphi_hcm`/`dphi_vcm` are incremental corrector deltas in **hardware amps**
    (already gain-scaled and downstream-zeroed), aligned with the matrix's
    `hcm_names`/`vcm_names`. They are the deltas to *add* to the present
    setpoints (the apply layer does caget+delta->clamp->caput).
    """
    dphi_hcm: np.ndarray             # (n_hcm,) float64, amps
    dphi_vcm: np.ndarray             # (n_vcm,) float64, amps
    hcm_names: list[str]
    vcm_names: list[str]
    last_seen_bpm_index: int         # last BPM index that saw beam; -1 if none
    n_zeroed: int                    # correctors zeroed by downstream-zeroing
