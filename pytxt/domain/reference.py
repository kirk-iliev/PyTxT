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
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np
import scipy.io

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


def load_reference_mat(path: Path) -> Reference:
    """Read a reference .mat file. See module docstring for schema."""
    if not path.exists():
        raise FileNotFoundError(f"Reference file not found: {path}")

    try:
        mat = scipy.io.loadmat(path, squeeze_me=True, struct_as_record=False)
    except Exception as exc:
        raise ReferenceLoadError(f"Failed to parse {path.name}: {exc}") from exc

    if "R0" not in mat:
        raise ReferenceLoadError(f"{path.name}: missing required variable 'R0'")
    if "BPMs" not in mat:
        raise ReferenceLoadError(f"{path.name}: missing required variable 'BPMs'")

    R0 = np.asarray(mat["R0"], dtype=np.float64)
    if R0.ndim != 2 or R0.shape[0] != 2:
        raise ReferenceLoadError(
            f"{path.name}: R0 has shape {R0.shape}, expected (2, n_bpms)"
        )

    bpms_struct = mat["BPMs"]
    if not hasattr(bpms_struct, "Names"):
        raise ReferenceLoadError(f"{path.name}: BPMs struct has no 'Names' field")

    names_raw = np.atleast_1d(bpms_struct.Names)
    raw_names = [str(np.atleast_1d(n)[0]) for n in names_raw]
    bpm_names = [canonicalize_bpm_name(n) for n in raw_names]

    if len(bpm_names) != R0.shape[1]:
        raise ReferenceLoadError(
            f"{path.name}: BPMs.Names length {len(bpm_names)} != R0.shape[1] {R0.shape[1]}"
        )

    n_bpms = R0.shape[1]
    x = R0[0].astype(np.float64)
    y = R0[1].astype(np.float64)
    sum_val = np.full(n_bpms, np.nan, dtype=np.float64)
    injection_turn = np.full(n_bpms, -1, dtype=np.int32)

    raws: dict[str, RawBPM] | None = None
    if all(k in mat for k in ("X_wf", "Y_wf", "sum_wf", "injection_turn")):
        try:
            X_wf = np.asarray(mat["X_wf"], dtype=np.int32)
            Y_wf = np.asarray(mat["Y_wf"], dtype=np.int32)
            sum_wf = np.asarray(mat["sum_wf"], dtype=np.int32)
            inj = np.asarray(mat["injection_turn"], dtype=np.int32)
            assert X_wf.shape == Y_wf.shape == sum_wf.shape
            assert X_wf.shape[0] == n_bpms
            assert inj.shape == (n_bpms,)
            now = datetime.now(timezone.utc)
            raws = {
                bpm_names[i]: RawBPM(
                    prefix=bpm_names[i],
                    x_wf=X_wf[i],
                    y_wf=Y_wf[i],
                    sum_wf=sum_wf[i],
                    armed=0,
                    read_timestamp=now,
                )
                for i in range(n_bpms)
            }
            injection_turn = inj
        except (AssertionError, ValueError):
            raws = None    # malformed extras → silently fall back to MATLAB-only

    first_turn = FirstTurnResult(
        x_first_turn=x,
        y_first_turn=y,
        sum_first_turn=sum_val,
        injection_turn=injection_turn,
        failed_bpm_names=[],
    )

    saved_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    return Reference(
        first_turn=first_turn,
        bpm_names=bpm_names,
        raws=raws,
        file_path=path,
        saved_at=saved_at,
    )


_N_SAMPLES = 100_000


def _pytxt_version() -> str:
    try:
        return version("pytxt")
    except PackageNotFoundError:
        return "0.0.0+dev"


def save_reference_mat(
    path: Path,
    first_turn: FirstTurnResult,
    last_acquire_raws: dict[str, RawBPM],
    bpm_prefixes: list[str],
) -> None:
    """Write a MATLAB-compatible reference .mat with PyTxT extras.

    See module docstring for the schema. Failed BPMs (absent from
    last_acquire_raws) are written with NaN in R0 and zero-filled
    waveform rows.
    """
    n_bpms = len(bpm_prefixes)
    assert first_turn.x_first_turn.shape == (n_bpms,), \
        f"first_turn length {first_turn.x_first_turn.shape[0]} != prefixes {n_bpms}"

    R0 = np.stack([
        first_turn.x_first_turn.astype(np.float64),
        first_turn.y_first_turn.astype(np.float64),
    ])  # (2, n_bpms)

    X_wf = np.zeros((n_bpms, _N_SAMPLES), dtype=np.int32)
    Y_wf = np.zeros((n_bpms, _N_SAMPLES), dtype=np.int32)
    sum_wf = np.zeros((n_bpms, _N_SAMPLES), dtype=np.int32)
    inj = np.full(n_bpms, -1, dtype=np.int32)
    for i, prefix in enumerate(bpm_prefixes):
        raw = last_acquire_raws.get(prefix)
        if raw is None:
            continue
        X_wf[i] = raw.x_wf
        Y_wf[i] = raw.y_wf
        sum_wf[i] = raw.sum_wf
        inj[i] = int(first_turn.injection_turn[i])

    bpms_struct = {
        "Names": np.array([[p] for p in bpm_prefixes], dtype=object),
        "ORDs": np.arange(1, n_bpms + 1, dtype=np.uint16),  # stub; we lack lattice ordinals
        "nBuffer": np.int32(_N_SAMPLES),
        # GUI-visible fields stubbed empty for completeness
        "XGolden": np.array([], dtype=np.float64),
        "YGolden": np.array([], dtype=np.float64),
        "current_mode": "",
        "attenuation": np.uint8(0),
    }

    scipy.io.savemat(path, {
        "R0": R0,
        "BPMs": bpms_struct,
        "X_wf": X_wf,
        "Y_wf": Y_wf,
        "sum_wf": sum_wf,
        "injection_turn": inj,
        "bpm_prefixes_canonical": np.array([[p] for p in bpm_prefixes], dtype=object),
        "saved_by": f"pytxt v{_pytxt_version()}",
    })


# align_to_current         — Task 4
# compute_diff             — Task 5
# summarize_diff           — Task 5
