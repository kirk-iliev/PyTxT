"""Integration: InjectionTrigger CA adapter against the fake timing IOC.

Validates the real adapter reads/writes the right PV names and that the
seqBusy 1->0 sync completes. Real-machine validation is deferred (checklist B1).
"""
import pytest

from pytxt.ca_client.injection_trigger import InjectionTrigger


@pytest.mark.asyncio
async def test_read_tim_inj_req_returns_7_longs(fake_injection_ioc):
    trig = InjectionTrigger(per_pv_timeout_s=3.0)
    await trig.start()
    try:
        req = await trig.read_tim_inj_req()
        assert req == [57, 4, 40, 0, 0, 0, 19133]
    finally:
        await trig.stop()


@pytest.mark.asyncio
async def test_write_tim_inj_req_round_trips(fake_injection_ioc):
    trig = InjectionTrigger(per_pv_timeout_s=3.0)
    await trig.start()
    try:
        await trig.write_tim_inj_req([308, 4, 40, 1, 0, 0, 19134])
        assert await trig.read_tim_inj_req() == [308, 4, 40, 1, 0, 0, 19134]
    finally:
        await trig.stop()


@pytest.mark.asyncio
async def test_write_fine_delay(fake_injection_ioc):
    trig = InjectionTrigger(per_pv_timeout_s=3.0)
    await trig.start()
    try:
        await trig.write_fine_delay(640)
    finally:
        await trig.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_injection_ioc", [{"bucket_control": 0}], indirect=True)
async def test_read_bucket_control_zero(fake_injection_ioc):
    trig = InjectionTrigger(per_pv_timeout_s=3.0)
    await trig.start()
    try:
        assert await trig.read_bucket_control() == 0
    finally:
        await trig.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("fake_injection_ioc", [{"bucket_control": 1}], indirect=True)
async def test_read_bucket_control_active(fake_injection_ioc):
    trig = InjectionTrigger(per_pv_timeout_s=3.0)
    await trig.start()
    try:
        assert await trig.read_bucket_control() == 1
    finally:
        await trig.stop()


@pytest.mark.asyncio
async def test_seq_busy_sync_completes(fake_injection_ioc):
    """The fake seqBusy returns 1 then 0, so the 1->0 sync completes."""
    trig = InjectionTrigger(per_pv_timeout_s=3.0)
    await trig.start()
    try:
        await trig.sync_seq_busy(timeout_s=2.0, poll_s=0.01)
    finally:
        await trig.stop()


@pytest.mark.asyncio
async def test_methods_require_start():
    trig = InjectionTrigger(per_pv_timeout_s=1.0)
    with pytest.raises(RuntimeError, match="start"):
        await trig.read_tim_inj_req()
