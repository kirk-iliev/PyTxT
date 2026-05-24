"""Unit: SyntheticBpmReader produces deterministic RawBPMs matching the protocol."""
import numpy as np
import pytest

from pytxt.ca_client.synthetic_reader import SyntheticBpmReader
from pytxt.domain.types import RawBPM


@pytest.mark.asyncio
async def test_synthetic_reader_read_all_returns_one_raw_per_prefix():
    prefixes = ["SR01C:BPM1", "SR02C:BPM1", "SR03C:BPM1"]
    reader = SyntheticBpmReader(prefixes=prefixes)
    await reader.start()
    raws = await reader.read_all()
    assert set(raws.keys()) == set(prefixes)
    for p in prefixes:
        r = raws[p]
        assert isinstance(r, RawBPM)
        assert r.prefix == p
        assert r.x_wf.shape == (100000,)
        assert r.x_wf.dtype == np.int32
        assert r.y_wf.shape == (100000,)
        assert r.sum_wf.shape == (100000,)
        assert r.armed == 0


@pytest.mark.asyncio
async def test_synthetic_reader_sum_wf_has_injection_step():
    """The synthetic sum_wf must rise so domain code can detect the injection turn."""
    reader = SyntheticBpmReader(prefixes=["SR01C:BPM1"])
    await reader.start()
    raws = await reader.read_all()
    sum_wf = raws["SR01C:BPM1"].sum_wf
    # Pre-injection samples are low; post-injection samples are high.
    assert sum_wf[:1000].max() < 10_000
    assert sum_wf[5000:].min() > 50_000


@pytest.mark.asyncio
async def test_synthetic_reader_x_varies_across_prefixes():
    """Each synthetic BPM should produce a different x_wf so the rendered
    polyline isn't a horizontal line."""
    reader = SyntheticBpmReader(prefixes=["SR01C:BPM1", "SR02C:BPM1"])
    await reader.start()
    raws = await reader.read_all()
    x0 = raws["SR01C:BPM1"].x_wf
    x1 = raws["SR02C:BPM1"].x_wf
    assert not np.array_equal(x0, x1)
