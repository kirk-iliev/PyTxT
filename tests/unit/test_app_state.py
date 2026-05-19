"""Unit tests for pytxt.state.app_state."""
import asyncio
import pytest
import time


@pytest.mark.asyncio
async def test_update_fires_listener_with_new_value():
    from pytxt.state.app_state import AppState
    state = AppState()
    received = []

    async def listener(value):
        received.append(value)

    state.subscribe("ping_count", listener)
    await state.update(ping_count=5)
    assert received == [5]


@pytest.mark.asyncio
async def test_update_suppresses_no_op():
    """If the value didn't change, listeners do not fire."""
    from pytxt.state.app_state import AppState
    state = AppState(ping_count=3)
    received = []

    async def listener(value):
        received.append(value)

    state.subscribe("ping_count", listener)
    await state.update(ping_count=3)  # same value
    assert received == []


@pytest.mark.asyncio
async def test_update_multiple_fields_fires_all_listeners():
    from pytxt.state.app_state import AppState
    state = AppState()
    received_a = []
    received_b = []

    async def listener_a(v):
        received_a.append(v)

    async def listener_b(v):
        received_b.append(v)

    state.subscribe("ping_count", listener_a)
    state.subscribe("last_ping_at", listener_b)
    await state.update(ping_count=1, last_ping_at="2026-05-07T00:00:00Z")
    assert received_a == [1]
    assert received_b == ["2026-05-07T00:00:00Z"]


@pytest.mark.asyncio
async def test_failing_listener_does_not_block_others(caplog):
    """Per-listener exception isolation: one bad listener does not break the chain."""
    from pytxt.state.app_state import AppState
    state = AppState()
    received = []

    async def bad_listener(value):
        raise RuntimeError("boom")

    async def good_listener(value):
        received.append(value)

    state.subscribe("ping_count", bad_listener)
    state.subscribe("ping_count", good_listener)
    await state.update(ping_count=1)
    assert received == [1]
    # The bad listener's exception should be logged
    assert "listener" in caplog.text.lower()


@pytest.mark.asyncio
async def test_multiple_listeners_on_same_field_all_fire():
    from pytxt.state.app_state import AppState
    state = AppState()
    received_a = []
    received_b = []

    async def la(v):
        received_a.append(v)

    async def lb(v):
        received_b.append(v)

    state.subscribe("heartbeat", la)
    state.subscribe("heartbeat", lb)
    await state.update(heartbeat=10)
    assert received_a == [10]
    assert received_b == [10]


def test_uptime_s_property():
    from pytxt.state.app_state import AppState
    state = AppState(started_at=time.time() - 5.0)
    assert 4.5 < state.uptime_s < 5.5


def test_uptime_s_zero_when_started_at_unset():
    from pytxt.state.app_state import AppState
    state = AppState()  # started_at = 0.0
    assert state.uptime_s == 0.0


@pytest.mark.asyncio
async def test_uptime_s_pushed_is_separate_from_property():
    """uptime_s_pushed is a writable field bound to the PV; uptime_s is computed."""
    from pytxt.state.app_state import AppState
    state = AppState(started_at=time.time())
    assert state.uptime_s_pushed == 0.0  # not auto-populated
    await state.update(uptime_s_pushed=1.5)
    assert state.uptime_s_pushed == 1.5
    # The property is independent
    assert state.uptime_s > 0


@pytest.mark.asyncio
async def test_update_rejects_unknown_field():
    """A typo in a field name raises AttributeError at the mutation site."""
    from pytxt.state.app_state import AppState
    state = AppState()
    with pytest.raises(AttributeError, match="ping_coutn"):
        await state.update(ping_coutn=5)  # typo


@pytest.mark.asyncio
async def test_update_rejects_internal_field():
    """Internal `_listeners` field cannot be overwritten via update()."""
    from pytxt.state.app_state import AppState
    state = AppState()
    with pytest.raises(AttributeError, match="_listeners"):
        await state.update(_listeners={})


@pytest.mark.asyncio
async def test_update_rejects_property_name():
    """The computed `uptime_s` property cannot be set via update()."""
    from pytxt.state.app_state import AppState
    state = AppState()
    with pytest.raises(AttributeError, match="uptime_s"):
        await state.update(uptime_s=42.0)


import asyncio
import numpy as np

from pytxt.api.schemas.result import AcquireStatus, LastAcquireResult


def test_app_state_has_phase_2_fields():
    """AppState defaults populate the four new phase-2 fields."""
    from pytxt.state.app_state import AppState
    s = AppState()
    assert s.bpm_prefixes == []
    assert s.acquire_in_flight is False
    assert s.last_acquire is not None
    assert s.last_acquire.status == "NEVER"
    assert s.last_acquire_raws == {}


def test_acquire_in_flight_is_listener_observable():
    """Listeners fire on acquire_in_flight changes."""
    from pytxt.state.app_state import AppState
    s = AppState()
    captured = []

    async def cb(v):
        captured.append(v)

    s.subscribe("acquire_in_flight", cb)

    async def run():
        await s.update(acquire_in_flight=True)
        await s.update(acquire_in_flight=False)

    asyncio.run(run())
    assert captured == [True, False]
