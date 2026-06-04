"""Unit tests for response-matrix artifact save/load + validation."""
from __future__ import annotations

import numpy as np
import pytest

from pytxt.domain.response_matrix import (
    ResponseMatrixError,
    load_response_matrix,
    save_response_matrix,
)
from pytxt.domain.types import ResponseMatrix


def _rm(n_bpms=3, n_hcm=2, n_vcm=1) -> ResponseMatrix:
    n_cm = n_hcm + n_vcm
    return ResponseMatrix(
        mplus=np.arange(n_cm * 2 * n_bpms, dtype=np.float64).reshape(n_cm, 2 * n_bpms),
        bpm_names=[f"BPM{i}" for i in range(n_bpms)],
        hcm_names=[f"HCM{i}" for i in range(n_hcm)],
        vcm_names=[f"VCM{i}" for i in range(n_vcm)],
        bpm_s=np.linspace(0, 10, n_bpms),
        cm_s=np.linspace(0, 10, n_cm),
        units="mm->amp",
        energy_gev=1.9,
        provenance="test",
    )


def test_round_trip_preserves_all_fields(tmp_path):
    rm = _rm()
    path = tmp_path / "rm.npz"
    save_response_matrix(path, rm)
    got = load_response_matrix(path)

    np.testing.assert_array_equal(got.mplus, rm.mplus)
    np.testing.assert_allclose(got.bpm_s, rm.bpm_s)
    np.testing.assert_allclose(got.cm_s, rm.cm_s)
    assert got.bpm_names == rm.bpm_names
    assert got.hcm_names == rm.hcm_names
    assert got.vcm_names == rm.vcm_names
    assert got.units == "mm->amp"
    assert got.energy_gev == pytest.approx(1.9)
    assert got.provenance == "test"
    assert got.n_bpms == 3 and got.n_hcm == 2 and got.n_vcm == 1


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "rm.npz"
    save_response_matrix(path, _rm())
    assert path.exists()


def test_load_missing_file_raises():
    with pytest.raises(ResponseMatrixError, match="not found"):
        load_response_matrix("/nonexistent/rm.npz")


def test_load_rejects_inconsistent_mplus_shape(tmp_path):
    path = tmp_path / "bad.npz"
    # mplus claims wrong BPM count: (3, 8) but 2*n_bpms = 6
    np.savez(
        path,
        mplus=np.zeros((3, 8)),
        bpm_s=np.zeros(3), cm_s=np.zeros(3),
        bpm_names=np.asarray(["a", "b", "c"], dtype=np.str_),
        hcm_names=np.asarray(["h0", "h1"], dtype=np.str_),
        vcm_names=np.asarray(["v0"], dtype=np.str_),
        units=np.asarray("mm->amp"), energy_gev=np.asarray(1.9),
        provenance=np.asarray("x"),
    )
    with pytest.raises(ResponseMatrixError, match="mplus shape"):
        load_response_matrix(path)


def test_load_rejects_wrong_bpm_s_length(tmp_path):
    path = tmp_path / "bad.npz"
    np.savez(
        path,
        mplus=np.zeros((3, 6)),
        bpm_s=np.zeros(5),         # wrong: should be 3
        cm_s=np.zeros(3),
        bpm_names=np.asarray(["a", "b", "c"], dtype=np.str_),
        hcm_names=np.asarray(["h0", "h1"], dtype=np.str_),
        vcm_names=np.asarray(["v0"], dtype=np.str_),
        units=np.asarray("mm->amp"), energy_gev=np.asarray(1.9),
        provenance=np.asarray("x"),
    )
    with pytest.raises(ResponseMatrixError, match="bpm_s shape"):
        load_response_matrix(path)


def test_load_rejects_missing_array(tmp_path):
    path = tmp_path / "bad.npz"
    np.savez(path, mplus=np.zeros((3, 6)))  # everything else missing
    with pytest.raises(ResponseMatrixError, match="missing arrays"):
        load_response_matrix(path)


def test_synthetic_generator_builds_loadable_artifact(tmp_path):
    # The synthetic generator must produce a valid, loadable artifact with the
    # real ALS corrector counts (96 HCM + 72 VCM), proving the runtime contract
    # works without pySC.
    from tools.gen_synthetic_response_matrix import build_synthetic

    rm = build_synthetic(n_bpms=120, n_hcm=96, n_vcm=72, seed=1)
    assert rm.mplus.shape == (96 + 72, 2 * 120)
    assert rm.n_hcm == 96 and rm.n_vcm == 72
    assert "SYNTHETIC" in rm.provenance

    path = tmp_path / "synthetic.npz"
    save_response_matrix(path, rm)
    got = load_response_matrix(path)
    assert got.mplus.shape == rm.mplus.shape
    assert got.units == "mm->amp"
