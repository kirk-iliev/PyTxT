"""Integration: BpmReader active-acquisition path (setup / arm / wait).

Exercises the Phase-4 arm/trigger/wait code against the fake IOC's control PVs.
Real-machine arm validation is deferred to the control room (checklist B3).
"""
import pytest

from pytxt.ca_client.bpm_reader import AcquisitionTimeoutError, BpmReader


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [["FAKE:BPM1", "FAKE:BPM2"]], indirect=True)
async def test_setup_writes_trigger_config(fake_bpm_ioc):
    """setup() programs trigger mask, event-48 trigger, and acq count per BPM."""
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=3.0)
    await reader.start()
    try:
        await reader.setup(acq_count=100_000)
        # Read the control PVs back through the reader's resolved PV objects.
        for prefix in fake_bpm_ioc.prefixes:
            ctrl = reader._ctrl_pvs[prefix]
            assert int((await ctrl["trigger_mask"].read()).data[0]) == 0b01000000
            assert int((await ctrl["event48trig"].read()).data[0]) == 0b01000000
            assert int((await ctrl["acq_count"].read()).data[0]) == 100_000
            assert int((await ctrl["arm"].read()).data[0]) == 0  # cleared by setup
    finally:
        await reader.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [["FAKE:BPM1", "FAKE:BPM2"]], indirect=True)
async def test_arm_sets_arm_pv(fake_bpm_ioc):
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=3.0)
    await reader.start()
    try:
        await reader.setup()
        await reader.arm()
        for prefix in fake_bpm_ioc.prefixes:
            assert int((await reader._ctrl_pvs[prefix]["arm"].read()).data[0]) == 1
    finally:
        await reader.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_bpm_ioc", [3], indirect=True)
async def test_full_active_cycle_setup_arm_wait_read(fake_bpm_ioc):
    """setup -> arm -> wait_until_ready -> read_all on ready BPMs (armed=0)."""
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=3.0)
    await reader.start()
    try:
        await reader.setup()
        await reader.arm()
        await reader.wait_until_ready(timeout_s=3.0)  # fake BPMs report armed=0
        result = await reader.read_all()
    finally:
        await reader.stop()

    assert list(result.keys()) == fake_bpm_ioc.prefixes
    for prefix in fake_bpm_ioc.prefixes:
        assert result[prefix] is not None
        assert result[prefix].x_wf.shape == (100000,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fake_bpm_ioc",
    [{"prefixes": ["FAKE:BPM1", "FAKE:BPM2"], "stuck_armed": ["FAKE:BPM2"]}],
    indirect=True,
)
async def test_wait_times_out_when_bpm_stays_armed(fake_bpm_ioc):
    """A BPM stuck at armed=1 makes wait_until_ready raise AcquisitionTimeoutError."""
    reader = BpmReader(prefixes=fake_bpm_ioc.prefixes, per_pv_timeout_s=2.0)
    await reader.start()
    try:
        await reader.setup()
        await reader.arm()
        with pytest.raises(AcquisitionTimeoutError, match="still armed"):
            await reader.wait_until_ready(timeout_s=0.6, poll_interval_s=0.1)
    finally:
        await reader.stop()


@pytest.mark.asyncio
async def test_active_methods_require_start():
    reader = BpmReader(prefixes=["FAKE:BPM1"], per_pv_timeout_s=1.0)
    with pytest.raises(RuntimeError, match="start"):
        await reader.setup()
    with pytest.raises(RuntimeError, match="start"):
        await reader.wait_until_ready(timeout_s=0.1)
