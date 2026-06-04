"""Cached response-matrix artifact I/O (Phase 4, Decision D1).

A `ResponseMatrix` is generated **offline** — modeled via pySC against the LOCO
lattice, or measured on the machine — and persisted to a single ``.npz`` archive.
The runtime loads it with `load_response_matrix` and never imports pySC (D1). The
amps↔kick unit convention is folded into `mplus` at generation time (D2), so the
loaded matrix maps BPM-mm orbit deviation directly to corrector-amps.

Artifact contents (``np.savez``):
    mplus        : (n_cm, 2*n_bpms) float64   — the cached pseudo-inverse
    bpm_s        : (n_bpms,) float64           — BPM s-positions (m)
    cm_s         : (n_cm,) float64             — corrector s-positions (m)
    bpm_names    : (n_bpms,) str
    hcm_names    : (n_hcm,) str
    vcm_names    : (n_vcm,) str
    units        : () str                      — e.g. "mm->amp"
    energy_gev   : () float64
    provenance   : () str                      — tool / lattice / date

This is filesystem-local numpy I/O only — NO caproto/FastAPI/asyncio, NO pySC.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from pytxt.domain.types import ResponseMatrix


class ResponseMatrixError(ValueError):
    """Raised when a response-matrix artifact is missing or internally inconsistent."""


def save_response_matrix(path: Path, rm: ResponseMatrix) -> None:
    """Persist a `ResponseMatrix` to a ``.npz`` artifact at `path`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez(
        path,
        mplus=np.asarray(rm.mplus, dtype=np.float64),
        bpm_s=np.asarray(rm.bpm_s, dtype=np.float64),
        cm_s=np.asarray(rm.cm_s, dtype=np.float64),
        bpm_names=np.asarray(rm.bpm_names, dtype=np.str_),
        hcm_names=np.asarray(rm.hcm_names, dtype=np.str_),
        vcm_names=np.asarray(rm.vcm_names, dtype=np.str_),
        units=np.asarray(rm.units),
        energy_gev=np.asarray(rm.energy_gev, dtype=np.float64),
        provenance=np.asarray(rm.provenance),
    )


def load_response_matrix(path: Path) -> ResponseMatrix:
    """Load and validate a cached `ResponseMatrix` artifact.

    Raises `ResponseMatrixError` if the file is absent or the array shapes are
    mutually inconsistent (so a corrupt/mis-generated matrix fails loudly at
    load, not mid-threading).
    """
    path = Path(path)
    if not path.exists():
        raise ResponseMatrixError(f"Response-matrix artifact not found: {path}")

    try:
        npz = np.load(path, allow_pickle=False)
    except Exception as exc:
        raise ResponseMatrixError(f"Failed to read {path.name}: {exc}") from exc

    required = {
        "mplus", "bpm_s", "cm_s", "bpm_names", "hcm_names", "vcm_names",
        "units", "energy_gev", "provenance",
    }
    missing = required - set(npz.files)
    if missing:
        raise ResponseMatrixError(f"{path.name}: missing arrays {sorted(missing)}")

    mplus = np.asarray(npz["mplus"], dtype=np.float64)
    bpm_s = np.asarray(npz["bpm_s"], dtype=np.float64)
    cm_s = np.asarray(npz["cm_s"], dtype=np.float64)
    bpm_names = [str(n) for n in npz["bpm_names"]]
    hcm_names = [str(n) for n in npz["hcm_names"]]
    vcm_names = [str(n) for n in npz["vcm_names"]]

    n_bpms = len(bpm_names)
    n_cm = len(hcm_names) + len(vcm_names)

    if mplus.ndim != 2:
        raise ResponseMatrixError(f"{path.name}: mplus must be 2-D, got {mplus.shape}")
    if mplus.shape != (n_cm, 2 * n_bpms):
        raise ResponseMatrixError(
            f"{path.name}: mplus shape {mplus.shape} != "
            f"(n_cm={n_cm}, 2*n_bpms={2 * n_bpms})"
        )
    if bpm_s.shape != (n_bpms,):
        raise ResponseMatrixError(
            f"{path.name}: bpm_s shape {bpm_s.shape} != ({n_bpms},)"
        )
    if cm_s.shape != (n_cm,):
        raise ResponseMatrixError(
            f"{path.name}: cm_s shape {cm_s.shape} != ({n_cm},)"
        )

    return ResponseMatrix(
        mplus=mplus,
        bpm_names=bpm_names,
        hcm_names=hcm_names,
        vcm_names=vcm_names,
        bpm_s=bpm_s,
        cm_s=cm_s,
        units=str(npz["units"]),
        energy_gev=float(npz["energy_gev"]),
        provenance=str(npz["provenance"]),
    )
