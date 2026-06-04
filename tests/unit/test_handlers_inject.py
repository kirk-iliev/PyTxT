"""Unit tests for handle_inject_oneshot (de-boxed srinjectoneshot), fake trigger."""
from __future__ import annotations

import pytest

from pytxt.ca_client.injection_trigger import SeqBusyTimeoutError
from pytxt.handlers.threading import (
    GunFireNotAllowedError,
    InjectInFlightError,
    InjectionPreconditionError,
    handle_inject_oneshot,
)
from pytxt.state.app_state import AppState


class FakeTrigger:
    """In-process InjectionTrigger stand-in recording the fire sequence."""

    def __init__(self, bucket_control: int = 0, seq_busy_raises: bool = False):
        self._bucket_control = bucket_control
        self._seq_busy_raises = seq_busy_raises
        self.req = [57, 4, 40, 0, 0, 0, 19133]
        self.written_req = None
        self.written_delay = None
        self.synced = False

    async def read_bucket_control(self):
        return self._bucket_control

    async def read_tim_inj_req(self):
        return list(self.req)

    async def sync_seq_busy(self, timeout_s=5.0, poll_s=0.01):
        if self._seq_busy_raises:
            raise SeqBusyTimeoutError("no cycle")
        self.synced = True

    async def write_tim_inj_req(self, req):
        self.written_req = list(req)

    async def write_fine_delay(self, counts):
        self.written_delay = int(counts)


@pytest.mark.asyncio
async def test_default_shot_fires_inhibit_1_bucket_308():
    state = AppState()
    trig = FakeTrigger()
    resp = await handle_inject_oneshot(state, trig)
    assert resp.status == "FIRED"
    assert resp.bucket == 308 and resp.inhibit == 1 and resp.mode == 40
    # TimInjReq written with bucket/bunches/mode/inhibit + bumped seq
    assert trig.written_req[:4] == [308, 4, 40, 1]
    assert trig.written_req[6] == 19134
    assert trig.written_delay is not None
    assert state.last_inject.status == "FIRED"
    assert state.last_inject.seq_num == 19134
    assert state.inject_in_flight is False


@pytest.mark.asyncio
async def test_gun_fire_requires_allow_flag():
    with pytest.raises(GunFireNotAllowedError):
        await handle_inject_oneshot(AppState(), FakeTrigger(), inhibit=0)


@pytest.mark.asyncio
async def test_gun_fire_allowed_with_flag():
    state = AppState()
    trig = FakeTrigger()
    resp = await handle_inject_oneshot(state, trig, inhibit=0, allow_gun_fire=True)
    assert resp.inhibit == 0
    assert trig.written_req[3] == 0


@pytest.mark.asyncio
async def test_precondition_refuses_during_top_off():
    state = AppState()
    trig = FakeTrigger(bucket_control=1)  # top-off active
    with pytest.raises(InjectionPreconditionError):
        await handle_inject_oneshot(state, trig)
    assert trig.written_req is None  # nothing fired
    assert state.inject_in_flight is False


@pytest.mark.asyncio
async def test_force_bypasses_precondition():
    state = AppState()
    trig = FakeTrigger(bucket_control=1)
    resp = await handle_inject_oneshot(state, trig, force=True)
    assert resp.status == "FIRED"
    assert trig.written_req is not None


@pytest.mark.asyncio
async def test_in_flight_collision_raises():
    state = AppState(inject_in_flight=True)
    with pytest.raises(InjectInFlightError):
        await handle_inject_oneshot(state, FakeTrigger())


@pytest.mark.asyncio
async def test_seq_busy_timeout_is_non_fatal():
    # The sync is a robustness nicety; a timeout must not block the shot.
    state = AppState()
    trig = FakeTrigger(seq_busy_raises=True)
    resp = await handle_inject_oneshot(state, trig)
    assert resp.status == "FIRED"
    assert trig.written_req is not None
    assert trig.synced is False


@pytest.mark.asyncio
async def test_in_flight_cleared_after_error():
    class BoomTrigger(FakeTrigger):
        async def read_tim_inj_req(self):
            raise RuntimeError("CA boom")

    state = AppState()
    with pytest.raises(RuntimeError, match="boom"):
        await handle_inject_oneshot(state, BoomTrigger(), force=True)
    assert state.inject_in_flight is False
