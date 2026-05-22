# tests/integration/test_bpm_reader_scale.py
"""Integration: BpmReader.read_all scales to production N (107 BPMs) under 3 s.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §12 DoD line 2.
"""
import time

import pytest

from pytxt.ca_client.bpm_reader import BpmReader
from pytxt.domain.types import RawBPM


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [10, 50, 107], indirect=True)
async def test_read_all_scales_under_3s(fake_bpm_ioc):
    """Parametric: N=10, 50, 107 — every BPM returns RawBPM; read_all() under 3 s."""
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=5.0)
    await reader.start()
    try:
        t0 = time.monotonic()
        result = await reader.read_all()
        elapsed = time.monotonic() - t0
    finally:
        await reader.stop()

    n = len(fake_bpm_ioc.prefixes)
    assert len(result) == n, f"expected {n} entries, got {len(result)}"
    none_prefixes = [p for p, r in result.items() if r is None]
    assert not none_prefixes, f"BPMs returned None: {none_prefixes[:5]}"
    for prefix, raw in result.items():
        assert isinstance(raw, RawBPM), f"{prefix} returned {type(raw).__name__}"
        assert raw.x_wf.shape == (100000,)
        assert raw.y_wf.shape == (100000,)
        assert raw.sum_wf.shape == (100000,)
    assert elapsed < 3.0, f"read_all of {n} BPMs took {elapsed:.2f}s, expected <3s"
