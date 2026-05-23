"""Sanity check: the fake BPM IOC fixture serves the expected PV shape."""
import asyncio
import pytest
import numpy as np
from caproto import CaprotoTimeoutError
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fake_bpm_ioc",
    [{"n": 3, "offline": ["FAKE:BPM2"]}],
    indirect=True,
)
async def test_offline_prefixes_omits_pvs_from_pvdb(fake_bpm_ioc):
    """A prefix in `offline` is reported in fixture.prefixes but its PVs do not exist."""
    assert fake_bpm_ioc.prefixes == ["FAKE:BPM1", "FAKE:BPM2", "FAKE:BPM3"]

    # PVs for the online BPMs resolve.
    async with ClientContext() as ctx:
        online_pv, = await asyncio.wait_for(
            ctx.get_pvs("FAKE:BPM1:wfr:TBT:c0"), timeout=2.0
        )
        result = await online_pv.read()
        assert len(result.data) == 100000

    # PVs for the offline BPM do NOT resolve within a short window.
    # get_pvs() returns immediately with an unconnected PV object; the
    # CaprotoTimeoutError surfaces on the first read() attempt.
    async with ClientContext() as ctx:
        offline_pvs = await ctx.get_pvs("FAKE:BPM2:wfr:TBT:c0")
        offline_pv = offline_pvs[0]
        with pytest.raises(CaprotoTimeoutError):
            await asyncio.wait_for(offline_pv.read(timeout=0.5), timeout=1.0)
