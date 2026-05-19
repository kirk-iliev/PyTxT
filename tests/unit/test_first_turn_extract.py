"""extract_first_turn: convert raw BPM dict → FirstTurnResult with NaN sentinels."""
from datetime import datetime, timezone
import numpy as np

from pytxt.domain.first_turn_extract import extract_first_turn
from pytxt.domain.types import RawBPM


def _raw_with_offset(prefix: str, x_offset_nm: int, y_offset_nm: int, peak_at: int = 1370):
    sum_wf = np.full(100000, 1000, dtype=np.int32)
    sum_wf[peak_at:] = 200000
    return RawBPM(
        prefix=prefix,
        x_wf=np.full(100000, x_offset_nm, dtype=np.int32),
        y_wf=np.full(100000, y_offset_nm, dtype=np.int32),
        sum_wf=sum_wf,
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )


def test_all_valid_bpms_extracted():
    raws = {
        "A": _raw_with_offset("A", 80_000, 0),   # 0.08 mm X
        "B": _raw_with_offset("B", 0, -50_000),  # -0.05 mm Y
    }
    r = extract_first_turn(raws)
    np.testing.assert_allclose(r.x_first_turn, [0.08, 0.0])
    np.testing.assert_allclose(r.y_first_turn, [0.0, -0.05])
    assert list(r.injection_turn) == [1370, 1370]
    assert r.failed_bpm_names == []


def test_none_entries_become_nan_with_failed_names():
    raws = {
        "A": _raw_with_offset("A", 80_000, 0),
        "B": None,
        "C": _raw_with_offset("C", 0, 0),
    }
    r = extract_first_turn(raws)
    assert np.isnan(r.x_first_turn[1])
    assert np.isnan(r.y_first_turn[1])
    assert r.injection_turn[1] == -1
    assert r.failed_bpm_names == ["B"]
    assert not np.isnan(r.x_first_turn[0])
    assert not np.isnan(r.x_first_turn[2])


def test_all_none_all_nan_all_failed():
    raws = {"X": None, "Y": None, "Z": None}
    r = extract_first_turn(raws)
    assert np.all(np.isnan(r.x_first_turn))
    assert np.all(r.injection_turn == -1)
    assert r.failed_bpm_names == ["X", "Y", "Z"]


def test_bpm_index_alignment_preserved():
    """Dict-insertion order defines BPM index. Don't reorder."""
    raws = {"Z": _raw_with_offset("Z", 1_000_000, 0), "A": _raw_with_offset("A", 0, 0)}
    r = extract_first_turn(raws)
    # Index 0 is "Z" (first inserted)
    np.testing.assert_allclose(r.x_first_turn[0], 1.0)
    np.testing.assert_allclose(r.x_first_turn[1], 0.0)
