"""First-turn threading correction math (Phase 4).

Pure-numpy/scipy module: NO caproto, NO FastAPI, NO asyncio, **NO pySC**
(Decision D1 — pySC is confined to the offline matrix generator; the runtime
correction is a numpy matmul against a cached pseudo-inverse). Ported from the
legacy `SCgetPinv` + `SCexp_ALS_calcCMstep.m`.

The threading loop is:

    Mplus = tikhonov_pinv(RM, alpha, n_sv_cut, damping)   # offline, once
    ...
    dx, dy = compute_diff(live, reference)                # Phase-3 diff == dR
    step   = calc_cm_step(dx, dy, rm, beam_seen_mask)     # this module
    apply step.dphi_hcm / step.dphi_vcm incrementally     # caget+delta->clamp->caput

`dphi = Mplus @ [dx; dy]` is the whole correction; the only first-turn-specific
nuance is **downstream-zeroing** — you cannot steer beam past the last BPM that
still saw it, so correctors downstream of that point are forced to zero.
"""
from __future__ import annotations

import numpy as np

from pytxt.domain.types import CMStep, ResponseMatrix


def tikhonov_pinv(
    rm: np.ndarray,
    alpha: float = 1.0,
    n_sv_cut: int = 0,
    damping: float = 1.0,
) -> np.ndarray:
    """Regularized pseudo-inverse of a response matrix (legacy `SCgetPinv`).

    `rm` maps corrector kicks -> orbit response, shape (2*n_bpms, n_cm). The
    returned `mplus` maps orbit deviation -> corrector step, shape
    (n_cm, 2*n_bpms).

    - `alpha`  : Tikhonov regularization. Singular values are filtered by
      s -> s / (s**2 + alpha**2), which rolls off small singular values smoothly
      instead of a hard cut (legacy default alpha=1).
    - `n_sv_cut` : additionally zero the `n_sv_cut` *smallest* singular values
      (legacy `N`; default 0 = keep all).
    - `damping` : scalar loop-gain folded into the inverse (legacy default 0.5).
      Kept at 1.0 here so the cached artifact is a pure inverse and the loop
      controller owns the gain knob (Decision D4); pass 0.5 to match legacy
      exactly.

    Tikhonov with alpha=0, n_sv_cut=0, damping=1 reduces to the plain
    Moore-Penrose pseudo-inverse.
    """
    if rm.ndim != 2:
        raise ValueError(f"rm must be 2-D, got shape {rm.shape}")
    u, s, vt = np.linalg.svd(rm, full_matrices=False)
    if n_sv_cut < 0 or n_sv_cut >= s.size:
        raise ValueError(f"n_sv_cut={n_sv_cut} out of range for {s.size} singular values")
    filt = s / (s**2 + alpha**2)
    if n_sv_cut > 0:
        filt[s.size - n_sv_cut:] = 0.0
    mplus = (vt.T * filt) @ u.T
    return mplus * damping


def calc_cm_step(
    dx: np.ndarray,
    dy: np.ndarray,
    rm: ResponseMatrix,
    beam_seen_mask: np.ndarray | None = None,
    gain: float = 1.0,
) -> CMStep:
    """Compute one corrector step from an orbit deviation (legacy `calcCMstep`).

    `dx`/`dy` are the per-BPM orbit deviation (B - R0) in mm, each length
    n_bpms and aligned with `rm.bpm_names` — this is exactly the Phase-3
    `compute_diff` output. NaN entries (failed/unseen BPMs) are zeroed before
    the matmul, matching `dR(isnan)=0` in the legacy.

    `beam_seen_mask` marks BPMs that actually saw beam this shot (length
    n_bpms, bool). Correctors with s-position downstream of the last True
    entry are forced to zero (first-turn downstream-zeroing). If None, the
    mask is inferred from `dx` being non-NaN (best effort).

    `gain` is an extra runtime loop-gain multiplier applied on top of any
    damping already folded into `rm.mplus` (Decision D4).

    Returns a `CMStep` with HCM/VCM deltas in hardware amps.
    """
    n_bpms = rm.n_bpms
    if dx.shape != (n_bpms,) or dy.shape != (n_bpms,):
        raise ValueError(
            f"dx/dy must be ({n_bpms},) to match matrix BPM count, "
            f"got {dx.shape}/{dy.shape}"
        )

    if beam_seen_mask is None:
        beam_seen_mask = ~np.isnan(dx)
    elif beam_seen_mask.shape != (n_bpms,):
        raise ValueError(
            f"beam_seen_mask must be ({n_bpms},), got {beam_seen_mask.shape}"
        )

    # dR = [dx; dy], NaN -> 0 (legacy dR(isnan)=0)
    dr = np.concatenate([dx, dy]).astype(np.float64)
    dr[np.isnan(dr)] = 0.0

    dphi = gain * (rm.mplus @ dr)        # (n_cm,) amps

    # --- first-turn downstream-zeroing ---
    seen_idx = np.flatnonzero(beam_seen_mask)
    if seen_idx.size == 0:
        # No BPM saw beam: nothing to steer on, zero the whole step.
        last_seen_bpm_index = -1
        n_zeroed = int(dphi.size)
        dphi = np.zeros_like(dphi)
    else:
        last_seen_bpm_index = int(seen_idx[-1])
        last_seen_s = float(rm.bpm_s[last_seen_bpm_index])
        downstream = rm.cm_s > last_seen_s
        n_zeroed = int(np.count_nonzero(downstream))
        dphi = dphi.copy()
        dphi[downstream] = 0.0

    dphi_hcm = dphi[: rm.n_hcm]
    dphi_vcm = dphi[rm.n_hcm:]

    return CMStep(
        dphi_hcm=dphi_hcm,
        dphi_vcm=dphi_vcm,
        hcm_names=list(rm.hcm_names),
        vcm_names=list(rm.vcm_names),
        last_seen_bpm_index=last_seen_bpm_index,
        n_zeroed=n_zeroed,
    )
