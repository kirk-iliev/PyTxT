"""Reference-trajectory I/O and math.

Pure-numpy + scipy.io module: NO caproto, NO FastAPI, NO asyncio. Only
filesystem-local I/O via scipy.io.{loadmat,savemat}. Per CLAUDE.md
principle #5 — adapters above this layer translate file paths to and
from settings / CMD strings.

MATLAB schema (interop-safe per spec §1, §6.1):

    Required:   R0      : (2, n_bpms) float64, mm — row 0 X, row 1 Y
                BPMs    : struct, .Names cell of 'SR01C:BPM1:SA:X'-style

    Optional:   X_wf, Y_wf, sum_wf      : (n_bpms, n_samples) int32
                injection_turn          : (n_bpms,) int32
                bpm_prefixes_canonical  : (n_bpms,) cell str
                saved_by                : str, "pytxt v<version>"
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from pytxt.domain.types import (
    DiffSummary,
    FirstTurnResult,
    RawBPM,
    Reference,
)


class ReferenceLoadError(ValueError):
    """Raised when a .mat file does not parse as a valid reference."""


_MATLAB_BPM_SUFFIX_RE = re.compile(r":SA:[XY]$")


def canonicalize_bpm_name(name: str) -> str:
    """Strip MATLAB's trailing ':SA:X' or ':SA:Y' channel suffix.

    Idempotent: names without the suffix pass through unchanged.
    """
    return _MATLAB_BPM_SUFFIX_RE.sub("", name)


# load_reference_mat       — Task 2
# save_reference_mat       — Task 3
# align_to_current         — Task 4
# compute_diff             — Task 5
# summarize_diff           — Task 5
