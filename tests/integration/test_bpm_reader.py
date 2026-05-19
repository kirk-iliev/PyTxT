"""Integration: BpmReader reads upstream BPM TBT PVs in parallel.

Uses the fake_bpm_ioc fixture, so the test is fully self-contained.
"""
import numpy as np
import pytest

from pytxt.ca_client.bpm_reader import BpmReader
from pytxt.domain.types import RawBPM


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [["FAKE:BPM1"]], indirect=True)
async def test_read_one_bpm_returns_raw_bpm(fake_bpm_ioc):
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=3.0)
    await reader.start()
    try:
        result = await reader.read_all()
    finally:
        await reader.stop()

    assert set(result.keys()) == {"FAKE:BPM1"}
    raw = result["FAKE:BPM1"]
    assert raw is not None
    assert isinstance(raw, RawBPM)
    assert raw.prefix == "FAKE:BPM1"
    assert raw.x_wf.shape == (100000,)
    assert raw.y_wf.shape == (100000,)
    assert raw.sum_wf.shape == (100000,)
    assert raw.armed == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [5], indirect=True)
async def test_read_multiple_bpms_returns_aligned_dict(fake_bpm_ioc):
    """All five BPMs return RawBPM; dict ordering matches input prefixes order."""
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=3.0)
    await reader.start()
    try:
        result = await reader.read_all()
    finally:
        await reader.stop()

    assert list(result.keys()) == fake_bpm_ioc.prefixes
    for prefix in fake_bpm_ioc.prefixes:
        assert result[prefix] is not None, f"{prefix} returned None"
        assert result[prefix].prefix == prefix


@pytest.mark.asyncio
async def test_read_unreachable_bpm_returns_none(test_pv_prefix):
    """A nonexistent BPM prefix returns None in the result dict (not an exception)."""
    reader = BpmReader(prefixes=["NONEXISTENT:BPM"], per_pv_timeout_s=1.0)
    await reader.start()
    try:
        result = await reader.read_all()
    finally:
        await reader.stop()
    assert result == {"NONEXISTENT:BPM": None}


@pytest.mark.asyncio
async def test_read_all_raises_if_not_started():
    """Calling read_all() before start() succeeds raises a clear error."""
    reader = BpmReader(prefixes=["FAKE:BPM1"], per_pv_timeout_s=1.0)
    with pytest.raises(RuntimeError, match="before start"):
        await reader.read_all()
