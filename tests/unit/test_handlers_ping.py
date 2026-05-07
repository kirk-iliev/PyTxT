"""Unit tests for pytxt.handlers.ping."""
import pytest
from datetime import datetime, timezone


@pytest.mark.asyncio
async def test_handle_ping_increments_count():
    from pytxt.state.app_state import AppState
    from pytxt.handlers.ping import handle_ping
    state = AppState(ping_count=2)
    await handle_ping(state)
    assert state.ping_count == 3


@pytest.mark.asyncio
async def test_handle_ping_sets_iso_timestamp():
    from pytxt.state.app_state import AppState
    from pytxt.handlers.ping import handle_ping
    state = AppState()
    before = datetime.now(timezone.utc)
    await handle_ping(state)
    after = datetime.now(timezone.utc)
    assert state.last_ping_at is not None
    parsed = datetime.fromisoformat(state.last_ping_at)
    assert before <= parsed <= after


@pytest.mark.asyncio
async def test_multiple_pings_accumulate():
    from pytxt.state.app_state import AppState
    from pytxt.handlers.ping import handle_ping
    state = AppState()
    for _ in range(5):
        await handle_ping(state)
    assert state.ping_count == 5
