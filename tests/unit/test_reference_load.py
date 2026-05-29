"""Unit tests for load_reference_mat."""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import scipy.io

from pytxt.domain.reference import (
    ReferenceLoadError,
    canonicalize_bpm_name,
    load_reference_mat,
)


# Real MATLAB GUI sample file. Gitignored, transferred from appsdev2.
LEGACY_REF = Path("legacy/TxT_GUI/2025-03-23_12:43:16_reference_trajectory.mat")


def _skip_if_no_legacy():
    if not LEGACY_REF.exists():
        pytest.skip(f"Missing legacy fixture {LEGACY_REF}; rsync legacy/ from appsdev2 to run this test.")


def _write_minimal_matlab_ref(tmp_path: Path) -> Path:
    """Synthesize a MATLAB-GUI-shaped .mat (R0 + BPMs only, no extras)."""
    p = tmp_path / "minimal.mat"
    n = 3
    R0 = np.array([[0.1, -0.2, 0.3], [0.4, -0.5, 0.6]], dtype=np.float64)
    bpms = {"Names": np.array([["SR01C:BPM1:SA:X"], ["SR02C:BPM1:SA:X"], ["SR03C:BPM1:SA:X"]], dtype=object)}
    scipy.io.savemat(p, {"R0": R0, "BPMs": bpms})
    return p


def _write_extended_ref(tmp_path: Path) -> Path:
    """Synthesize a PyTxT-extended .mat (R0 + BPMs + waveform extras)."""
    p = tmp_path / "extended.mat"
    n = 2
    n_samples = 100
    R0 = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float64)
    bpms = {"Names": np.array([["SR01C:BPM1:SA:X"], ["SR02C:BPM1:SA:X"]], dtype=object)}
    X_wf = np.tile(np.arange(n_samples, dtype=np.int32), (n, 1))
    Y_wf = np.full((n, n_samples), -1, dtype=np.int32)
    sum_wf = np.full((n, n_samples), 1000, dtype=np.int32)
    injection_turn = np.array([5, 7], dtype=np.int32)
    scipy.io.savemat(p, {
        "R0": R0, "BPMs": bpms,
        "X_wf": X_wf, "Y_wf": Y_wf, "sum_wf": sum_wf,
        "injection_turn": injection_turn,
        "saved_by": "pytxt vtest",
    })
    return p


# --- happy paths ---

def test_load_real_matlab_file_parses_correctly() -> None:
    _skip_if_no_legacy()
    ref = load_reference_mat(LEGACY_REF)
    assert len(ref.bpm_names) == 104
    assert ref.bpm_names[0] == "SR01C:BPM1"
    assert ref.bpm_names[-1] == "SR12C:BPM8"
    assert ref.first_turn.x_first_turn.shape == (104,)
    assert ref.first_turn.y_first_turn.shape == (104,)
    assert ref.raws is None                              # MATLAB-only schema
    assert ref.file_path == LEGACY_REF
    assert ref.saved_at is not None


def test_load_minimal_synthesized_ref(tmp_path: Path) -> None:
    p = _write_minimal_matlab_ref(tmp_path)
    ref = load_reference_mat(p)
    assert ref.bpm_names == ["SR01C:BPM1", "SR02C:BPM1", "SR03C:BPM1"]
    np.testing.assert_allclose(ref.first_turn.x_first_turn, [0.1, -0.2, 0.3])
    np.testing.assert_allclose(ref.first_turn.y_first_turn, [0.4, -0.5, 0.6])
    assert ref.raws is None


def test_load_extended_ref_populates_raws(tmp_path: Path) -> None:
    p = _write_extended_ref(tmp_path)
    ref = load_reference_mat(p)
    assert ref.raws is not None
    assert set(ref.raws) == {"SR01C:BPM1", "SR02C:BPM1"}
    assert ref.raws["SR01C:BPM1"].x_wf.shape == (100,)
    assert ref.raws["SR01C:BPM1"].x_wf.dtype == np.int32
    assert ref.first_turn.injection_turn.tolist() == [5, 7]


# --- error paths ---

def test_load_missing_R0_raises(tmp_path: Path) -> None:
    p = tmp_path / "no_R0.mat"
    scipy.io.savemat(p, {"BPMs": {"Names": np.array([["x"]], dtype=object)}})
    with pytest.raises(ReferenceLoadError, match="R0"):
        load_reference_mat(p)


def test_load_missing_BPMs_raises(tmp_path: Path) -> None:
    p = tmp_path / "no_BPMs.mat"
    scipy.io.savemat(p, {"R0": np.zeros((2, 3))})
    with pytest.raises(ReferenceLoadError, match="BPMs"):
        load_reference_mat(p)


def test_load_wrong_R0_shape_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad_R0.mat"
    scipy.io.savemat(p, {
        "R0": np.zeros((3, 3)),                          # should be (2, n)
        "BPMs": {"Names": np.array([["a"], ["b"], ["c"]], dtype=object)},
    })
    with pytest.raises(ReferenceLoadError, match=r"shape|R0"):
        load_reference_mat(p)


def test_load_R0_BPMs_length_mismatch_raises(tmp_path: Path) -> None:
    p = tmp_path / "mismatched.mat"
    scipy.io.savemat(p, {
        "R0": np.zeros((2, 5)),
        "BPMs": {"Names": np.array([["a"], ["b"]], dtype=object)},
    })
    with pytest.raises(ReferenceLoadError, match=r"mismatch|length|BPMs"):
        load_reference_mat(p)


def test_load_corrupt_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "garbage.mat"
    p.write_bytes(b"not a mat file at all")
    with pytest.raises(ReferenceLoadError):
        load_reference_mat(p)


def test_load_missing_file_raises(tmp_path: Path) -> None:
    p = tmp_path / "does_not_exist.mat"
    with pytest.raises((FileNotFoundError, ReferenceLoadError)):
        load_reference_mat(p)


# --- canonicalization ---

def test_loaded_names_are_canonicalized(tmp_path: Path) -> None:
    p = _write_minimal_matlab_ref(tmp_path)
    ref = load_reference_mat(p)
    for n in ref.bpm_names:
        assert ":SA:" not in n
