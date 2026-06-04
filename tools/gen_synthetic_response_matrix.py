#!/usr/bin/env python3
"""Generate a *synthetic* cached response-matrix artifact for PyTxT Phase-4 dev.

This is a stand-in for the real offline generator (modeled via pySC against the
LOCO lattice, or measured on the machine — deferred per Decision D1's "lattice
modeling later"). It builds a plausible, well-conditioned `mplus` from a random
plant so the runtime threading path and the loop controller can be exercised
end-to-end **without pySC installed**.

The artifact it writes is byte-identical in *format* to what the real generator
will produce — only the numbers are synthetic. Provenance is marked clearly so a
synthetic matrix can never be mistaken for a modeled/measured one.

Usage:
    python tools/gen_synthetic_response_matrix.py [out.npz] [--n-bpms N] \
        [--n-hcm N] [--n-vcm N] [--seed S]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from pytxt.domain.response_matrix import save_response_matrix
from pytxt.domain.threading import tikhonov_pinv
from pytxt.domain.types import ResponseMatrix


def build_synthetic(
    n_bpms: int = 120,
    n_hcm: int = 96,
    n_vcm: int = 72,
    seed: int = 0,
    energy_gev: float = 1.9,
) -> ResponseMatrix:
    """Build a synthetic ResponseMatrix with realistic ALS-scale dimensions."""
    rng = np.random.default_rng(seed)
    n_cm = n_hcm + n_vcm

    # Synthetic plant: corrector kicks (amps) -> orbit (mm). Give it a smooth
    # s-dependent structure so downstream-zeroing has something monotone to act
    # on, plus noise for conditioning.
    bpm_s = np.sort(rng.uniform(0, 200, size=n_bpms))
    cm_s = np.sort(rng.uniform(0, 200, size=n_cm))
    plant = rng.standard_normal((2 * n_bpms, n_cm)) * 0.1   # mm per amp, plausible

    mplus = tikhonov_pinv(plant, alpha=1.0, n_sv_cut=0, damping=1.0)

    return ResponseMatrix(
        mplus=mplus,
        bpm_names=[f"SR{i // 8 + 1:02d}C:BPM{i % 8 + 1}" for i in range(n_bpms)],
        hcm_names=[f"HCM{i + 1}" for i in range(n_hcm)],
        vcm_names=[f"VCM{i + 1}" for i in range(n_vcm)],
        bpm_s=bpm_s,
        cm_s=cm_s,
        units="mm->amp",
        energy_gev=energy_gev,
        provenance=(
            "SYNTHETIC (tools/gen_synthetic_response_matrix.py) — random plant, "
            "NOT a modeled or measured matrix; for dev/test only"
        ),
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("out", nargs="?", default="data/response_matrix/synthetic.npz",
                   help="output .npz path")
    p.add_argument("--n-bpms", type=int, default=120)
    p.add_argument("--n-hcm", type=int, default=96)
    p.add_argument("--n-vcm", type=int, default=72)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    rm = build_synthetic(args.n_bpms, args.n_hcm, args.n_vcm, args.seed)
    out = Path(args.out)
    save_response_matrix(out, rm)
    print(f"wrote synthetic response matrix: {out}")
    print(f"  mplus {rm.mplus.shape}  ({rm.n_hcm} HCM + {rm.n_vcm} VCM, {rm.n_bpms} BPMs)")
    print(f"  provenance: {rm.provenance}")


if __name__ == "__main__":
    main()
