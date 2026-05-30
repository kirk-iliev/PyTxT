"""Unit tests for pytxt.state.app_state."""
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


from pytxt.api.schemas.result import LastAcquireResult


def test_app_state_has_phase_2_fields():
    """AppState defaults populate the four new phase-2 fields."""
    from pytxt.state.app_state import AppState
    s = AppState()
    assert s.bpm_prefixes == []
    assert s.acquire_in_flight is False
    assert s.last_acquire is not None
    assert s.last_acquire.status == "NEVER"
    assert s.last_acquire_raws == {}


@pytest.mark.asyncio
async def test_acquire_in_flight_is_listener_observable():
    """Listeners fire on acquire_in_flight changes."""
    from pytxt.state.app_state import AppState
    s = AppState()
    captured = []

    async def cb(v):
        captured.append(v)

    s.subscribe("acquire_in_flight", cb)

    await s.update(acquire_in_flight=True)
    await s.update(acquire_in_flight=False)

    assert captured == [True, False]


def test_app_state_has_phase_3_reference_defaults():
    """A fresh AppState carries empty reference/diff state."""
    from pytxt.state.app_state import AppState
    from pytxt.domain.types import ReferenceSource
    s = AppState()
    assert s.reference_loaded is False
    assert s.reference_name == ""
    assert s.reference_loaded_at is None
    assert s.reference_source is ReferenceSource.NONE
    assert s.reference_first_turn is None
    assert s.reference_file_path is None
    assert s.reference_bpm_names is None
    assert s.last_diff is None


@pytest.mark.asyncio
async def test_promote_shaped_update_is_atomic_and_fires_listeners():
    """A multi-field promote-shaped update (including a DiffResult holding numpy
    arrays) applies atomically and fires listeners for exactly the changed
    fields. Exercises the numpy-tolerant equality guard on last_diff."""
    import numpy as np
    from pytxt.domain.types import DiffResult, DiffSummary, ReferenceSource
    from pytxt.state.app_state import AppState

    state = AppState()
    loaded_calls = []
    diff_calls = []

    async def on_loaded(v):
        loaded_calls.append(v)

    async def on_diff(v):
        diff_calls.append(v)

    state.subscribe("reference_loaded", on_loaded)
    state.subscribe("last_diff", on_diff)

    diff = DiffResult(
        dx=np.array([0.0]),
        dy=np.array([0.0]),
        summary=DiffSummary(0, 0, 0, 0, 1),
    )
    await state.update(
        reference_loaded=True,
        reference_name="<promoted>",
        reference_source=ReferenceSource.PROMOTED,
        last_diff=diff,
    )

    # State applied atomically.
    assert state.reference_loaded is True
    assert state.reference_name == "<promoted>"
    assert state.reference_source is ReferenceSource.PROMOTED
    assert state.last_diff is diff

    # Listeners fired exactly once for their changed field.
    assert loaded_calls == [True]
    assert len(diff_calls) == 1
    assert diff_calls[0] is diff


@pytest.mark.asyncio
async def test_update_handles_numpy_bearing_field_replacement():
    """Replacing last_acquire_raws (dict[str, RawBPM] containing numpy arrays)
    on a non-empty prior value must not crash on the equality check.

    Regression test for the M1 control-room bug where the second acquire on a
    real ring raised ``ValueError: truth value of an array ... ambiguous``
    because dict-eq dove into RawBPM's auto-generated numpy __eq__.
    """
    from datetime import datetime, timezone
    import numpy as np
    from pytxt.domain.types import RawBPM
    from pytxt.state.app_state import AppState

    def make_raw(seed: int) -> RawBPM:
        rng = np.random.default_rng(seed)
        return RawBPM(
            prefix="SR01C:BPM1",
            x_wf=rng.integers(-1000, 1000, 100000, dtype=np.int32),
            y_wf=rng.integers(-1000, 1000, 100000, dtype=np.int32),
            sum_wf=rng.integers(0, 100000, 100000, dtype=np.int32),
            armed=0,
            read_timestamp=datetime.now(timezone.utc),
        )

    state = AppState()
    # First acquire: old is {} → eq short-circuits to False, applies fine.
    await state.update(last_acquire_raws={"SR01C:BPM1": make_raw(1)})
    # Second acquire on same key with *different* numpy arrays — this is the
    # case that historically crashed.
    received = []

    async def cb(v):
        received.append(v)

    state.subscribe("last_acquire_raws", cb)
    await state.update(last_acquire_raws={"SR01C:BPM1": make_raw(2)})
    assert len(received) == 1
    assert "SR01C:BPM1" in received[0]
