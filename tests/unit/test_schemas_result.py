"""Phase-2 result schemas: round-trip, required fields, enum mapping."""
from datetime import datetime, timezone
import pytest
from pydantic import ValidationError

from pytxt.api.schemas.result import (
    AcquireStatus,
    LastAcquireResult,
    AcquireResponse,
    BpmRawWaveforms,
    STATUS_INT_TO_STR,
    STATUS_STR_TO_INT,
)


def test_acquire_status_int_string_mapping_is_bijective():
    assert STATUS_INT_TO_STR == {0: "NEVER", 1: "ACQUIRING", 2: "OK", 3: "PARTIAL", 4: "FAILED"}
    for i, s in STATUS_INT_TO_STR.items():
        assert STATUS_STR_TO_INT[s] == i


def test_last_acquire_result_round_trip():
    r = LastAcquireResult(
        status=AcquireStatus.OK,
        ok_count=120,
        fail_count=0,
        failed_bpm_names=[],
        injection_turn_median=1370,
        timestamp=datetime.now(timezone.utc),
    )
    js = r.model_dump_json()
    r2 = LastAcquireResult.model_validate_json(js)
    assert r2.status == "OK"
    assert r2.ok_count == 120


def test_acquire_response_required_fields():
    with pytest.raises(ValidationError):
        AcquireResponse()  # missing required


def test_bpm_raw_waveforms_shape():
    raw = BpmRawWaveforms(
        bpm_prefix="SR01C:BPM1",
        x_nm=[0, 1, 2],
        y_nm=[0, 1, 2],
        sum_au=[100, 200, 300],
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )
    assert raw.bpm_prefix == "SR01C:BPM1"
    assert len(raw.x_nm) == 3
