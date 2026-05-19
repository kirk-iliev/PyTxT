"""Sanity check: the fake BPM IOC fixture serves the expected PV shape."""
import asyncio
import pytest
import numpy as np
from caproto.asyncio.client import Context as ClientContext


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [["SR01C:BPM1"]], indirect=True)
async def test_fake_bpm_serves_tbt_channels(fake_bpm_ioc):
    """The fixture publishes c0/c1/c3 as length-100000 int32 waveforms and armed as a scalar."""
    async with ClientContext() as client:
        c0, c1, c3, armed = await client.get_pvs(
            "SR01C:BPM1:wfr:TBT:c0",
            "SR01C:BPM1:wfr:TBT:c1",
            "SR01C:BPM1:wfr:TBT:c3",
            "SR01C:BPM1:wfr:TBT:armed",
        )
        r_c0 = await c0.read()
        r_c1 = await c1.read()
        r_c3 = await c3.read()
        r_armed = await armed.read()

    assert len(r_c0.data) == 100000
    assert len(r_c1.data) == 100000
    assert len(r_c3.data) == 100000
    assert r_armed.data[0] == 0  # data ready by default

    # Sum signal should have an injection-turn peak around sample 1370
    sum_wf = np.asarray(r_c3.data)
    peak_idx = int(np.argmax(np.diff(sum_wf)))
    assert 1300 < peak_idx < 1500, f"expected peak ~1370, got {peak_idx}"
