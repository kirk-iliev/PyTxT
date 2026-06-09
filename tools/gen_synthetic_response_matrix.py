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

from pytxt.domain.response_matrix import build_synthetic_response_matrix, save_response_matrix

# Re-export under the historical name for any callers/tests.
build_synthetic = build_synthetic_response_matrix


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
