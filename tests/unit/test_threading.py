"""Unit tests for the Phase-4 threading domain (pure numpy, ms-fast)."""
from __future__ import annotations

import numpy as np
import pytest

from pytxt.domain.threading import calc_cm_step, tikhonov_pinv
from pytxt.domain.types import ResponseMatrix


def _rm(mplus: np.ndarray, n_hcm: int, n_vcm: int,
        bpm_s: list[float], cm_s: list[float]) -> ResponseMatrix:
    """Build a ResponseMatrix from an explicit mplus for testing."""
    n_bpms = len(bpm_s)
    return ResponseMatrix(
        mplus=np.asarray(mplus, dtype=np.float64),
        bpm_names=[f"BPM{i}" for i in range(n_bpms)],
        hcm_names=[f"HCM{i}" for i in range(n_hcm)],
        vcm_names=[f"VCM{i}" for i in range(n_vcm)],
        bpm_s=np.asarray(bpm_s, dtype=np.float64),
        cm_s=np.asarray(cm_s, dtype=np.float64),
        units="mm->amp",
        energy_gev=1.9,
        provenance="synthetic-test",
    )


# --- tikhonov_pinv ---------------------------------------------------------

def test_pinv_alpha_zero_equals_moore_penrose():
    rng = np.random.default_rng(0)
    rm = rng.standard_normal((6, 3))  # (2*n_bpms, n_cm), well-conditioned
    got = tikhonov_pinv(rm, alpha=0.0, n_sv_cut=0, damping=1.0)
    np.testing.assert_allclose(got, np.linalg.pinv(rm), atol=1e-10)


def test_pinv_shape_is_transposed():
    rm = np.ones((6, 3))
    assert tikhonov_pinv(rm).shape == (3, 6)


def test_pinv_damping_scales_linearly():
    rng = np.random.default_rng(1)
    rm = rng.standard_normal((6, 3))
    base = tikhonov_pinv(rm, alpha=1.0, damping=1.0)
    half = tikhonov_pinv(rm, alpha=1.0, damping=0.5)
    np.testing.assert_allclose(half, 0.5 * base, atol=1e-12)


def test_pinv_alpha_regularizes_small_singular_values():
    # A near-singular matrix: plain pinv blows up, Tikhonov stays bounded.
    rm = np.array([[1.0, 0.0], [0.0, 1e-8], [0.0, 0.0], [0.0, 0.0]])
    reg = tikhonov_pinv(rm, alpha=1.0)
    assert np.all(np.abs(reg) <= 1.0 + 1e-9)


def test_pinv_sv_cut_rejects_out_of_range():
    rm = np.ones((6, 3))
    with pytest.raises(ValueError):
        tikhonov_pinv(rm, n_sv_cut=3)  # only 3 singular values -> index 3 invalid


def test_pinv_rejects_non_2d():
    with pytest.raises(ValueError):
        tikhonov_pinv(np.ones(5))


# --- calc_cm_step ----------------------------------------------------------

def test_step_is_matmul_when_all_beam_seen():
    # mplus (n_cm=3, 2*n_bpms=6); cm_s all upstream of last BPM so nothing zeroed
    mplus = np.arange(18, dtype=float).reshape(3, 6)
    rm = _rm(mplus, n_hcm=2, n_vcm=1, bpm_s=[1, 2, 3], cm_s=[0.1, 0.2, 0.3])
    dx = np.array([1.0, 0.0, 0.0])
    dy = np.array([0.0, 0.0, 0.0])
    step = calc_cm_step(dx, dy, rm)
    expected = mplus @ np.array([1, 0, 0, 0, 0, 0], dtype=float)
    np.testing.assert_allclose(np.concatenate([step.dphi_hcm, step.dphi_vcm]), expected)
    assert step.n_zeroed == 0
    assert step.last_seen_bpm_index == 2


def test_step_hcm_vcm_split():
    mplus = np.ones((3, 6))
    rm = _rm(mplus, n_hcm=2, n_vcm=1, bpm_s=[1, 2, 3], cm_s=[0.1, 0.2, 0.3])
    step = calc_cm_step(np.ones(3), np.ones(3), rm)
    assert step.dphi_hcm.shape == (2,)
    assert step.dphi_vcm.shape == (1,)
    assert step.hcm_names == ["HCM0", "HCM1"]
    assert step.vcm_names == ["VCM0"]


def test_step_nan_deviations_are_zeroed_before_matmul():
    mplus = np.ones((3, 6))
    rm = _rm(mplus, n_hcm=2, n_vcm=1, bpm_s=[1, 2, 3], cm_s=[0.1, 0.2, 0.3])
    dx = np.array([1.0, np.nan, 2.0])
    dy = np.array([np.nan, 1.0, 1.0])
    step = calc_cm_step(dx, dy, rm, beam_seen_mask=np.array([True, True, True]))
    # NaN -> 0, so dR = [1,0,2, 0,1,1], each row of ones -> sum = 5
    np.testing.assert_allclose(step.dphi_hcm, [5.0, 5.0])
    np.testing.assert_allclose(step.dphi_vcm, [5.0])


def test_downstream_zeroing_zeros_correctors_past_last_seen_bpm():
    mplus = np.ones((3, 6))
    # cm0 upstream of bpm2(s=2), cm1/cm2 downstream
    rm = _rm(mplus, n_hcm=2, n_vcm=1, bpm_s=[1, 2, 3], cm_s=[1.5, 2.5, 3.5])
    # beam seen only through bpm index 1 (s=2); bpm2 lost it
    mask = np.array([True, True, False])
    step = calc_cm_step(np.ones(3), np.ones(3), rm, beam_seen_mask=mask)
    assert step.last_seen_bpm_index == 1
    assert step.n_zeroed == 2
    assert step.dphi_hcm[0] != 0.0      # cm0 (s=1.5) kept
    assert step.dphi_hcm[1] == 0.0      # cm1 (s=2.5) zeroed
    assert step.dphi_vcm[0] == 0.0      # cm2 (s=3.5) zeroed


def test_no_beam_seen_zeros_everything():
    mplus = np.ones((3, 6))
    rm = _rm(mplus, n_hcm=2, n_vcm=1, bpm_s=[1, 2, 3], cm_s=[1.5, 2.5, 3.5])
    mask = np.array([False, False, False])
    step = calc_cm_step(np.ones(3), np.ones(3), rm, beam_seen_mask=mask)
    assert step.last_seen_bpm_index == -1
    assert step.n_zeroed == 3
    assert np.all(step.dphi_hcm == 0.0)
    assert np.all(step.dphi_vcm == 0.0)


def test_gain_scales_step():
    mplus = np.ones((3, 6))
    rm = _rm(mplus, n_hcm=2, n_vcm=1, bpm_s=[1, 2, 3], cm_s=[0.1, 0.2, 0.3])
    full = calc_cm_step(np.ones(3), np.ones(3), rm, gain=1.0)
    half = calc_cm_step(np.ones(3), np.ones(3), rm, gain=0.5)
    np.testing.assert_allclose(half.dphi_hcm, 0.5 * full.dphi_hcm)


def test_step_rejects_wrong_length_deviation():
    rm = _rm(np.ones((3, 6)), n_hcm=2, n_vcm=1, bpm_s=[1, 2, 3], cm_s=[1, 2, 3])
    with pytest.raises(ValueError):
        calc_cm_step(np.ones(2), np.ones(3), rm)


def test_step_rejects_wrong_mask_length():
    rm = _rm(np.ones((3, 6)), n_hcm=2, n_vcm=1, bpm_s=[1, 2, 3], cm_s=[1, 2, 3])
    with pytest.raises(ValueError):
        calc_cm_step(np.ones(3), np.ones(3), rm, beam_seen_mask=np.array([True, False]))


def test_inferred_mask_uses_nan_in_dx():
    mplus = np.ones((3, 6))
    rm = _rm(mplus, n_hcm=2, n_vcm=1, bpm_s=[1, 2, 3], cm_s=[1.5, 2.5, 3.5])
    # dx NaN at bpm2 -> inferred last-seen = index 1 -> cm1,cm2 zeroed
    dx = np.array([1.0, 1.0, np.nan])
    dy = np.array([1.0, 1.0, 1.0])
    step = calc_cm_step(dx, dy, rm)
    assert step.last_seen_bpm_index == 1
    assert step.n_zeroed == 2


def test_convergence_over_iterations_reduces_rms():
    """A damped pinv loop should monotonically reduce orbit RMS on a linear
    plant — the property the real threading loop relies on (Decision D4)."""
    rng = np.random.default_rng(42)
    n_bpms = 2                                           # 2*n_bpms == n_cm == 4
    plant = rng.standard_normal((4, 4))                  # full-rank, fully correctable
    mplus = tikhonov_pinv(plant, alpha=0.01, damping=0.5)  # damped inverse
    rm = _rm(
        mplus, n_hcm=2, n_vcm=2,
        bpm_s=list(range(n_bpms)),
        cm_s=[-1.0, -1.0, -1.0, -1.0],  # all upstream -> no zeroing
    )
    orbit = rng.standard_normal(2 * n_bpms)              # initial deviation
    rms = [float(np.sqrt(np.mean(orbit**2)))]
    for _ in range(8):
        dx, dy = orbit[:n_bpms], orbit[n_bpms:]
        step = calc_cm_step(dx, dy, rm, beam_seen_mask=np.ones(n_bpms, bool))
        dphi = np.concatenate([step.dphi_hcm, step.dphi_vcm])
        orbit = orbit - plant @ dphi                     # apply correction
        rms.append(float(np.sqrt(np.mean(orbit**2))))
    assert rms[-1] < rms[0] * 0.5                        # converged substantially
    assert all(b <= a + 1e-9 for a, b in zip(rms, rms[1:]))  # monotone non-increasing
