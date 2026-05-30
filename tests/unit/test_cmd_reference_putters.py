"""Unit: CMD:PROMOTE_REF / CMD:CLEAR_REF putters dispatch to the canonical
reference handlers and surface NoLastAcquireError to CA clients.

Symmetric to REST's 422 (promote with no acquire) and idempotent clear
returned by /api/v1/cmd/{promote_ref,clear_ref}. Mirrors the structure of
tests/unit/test_cmd_acquire_putter.py: the putter coroutine is called
directly with a mock self (no running IOC/Context), so we exercise the
adapter wiring without caproto loopback.
"""
from unittest.mock import MagicMock

import pytest

from pytxt.ca_client.synthetic_reader import SyntheticBpmReader
from pytxt.domain.types import ReferenceSource
from pytxt.handlers.acquire import handle_acquire
from pytxt.handlers.reference import NoLastAcquireError, handle_promote_ref
from pytxt.ioc.pvs import PyTxTPVGroup
from pytxt.state.app_state import AppState


@pytest.mark.asyncio
async def test_cmd_promote_ref_putter_loads_reference():
    """A caput to CMD:PROMOTE_REF after a successful acquire promotes the
    live first-turn to an in-memory reference (acts on _state, no reader)."""
    # Drive a real acquire first so last_acquire/last_acquire_raws are populated.
    prefixes = ["FAKE:BPM1", "FAKE:BPM2"]
    state = AppState(bpm_prefixes=prefixes)
    reader = SyntheticBpmReader(prefixes)
    await handle_acquire(state, reader)
    assert state.last_acquire.ok_count > 0

    putter_fn = PyTxTPVGroup.cmd_promote_ref.pvspec.put
    mock_self = MagicMock()
    mock_self._state = state
    mock_self._reader = None  # promote must NOT gate on the reader
    instance = MagicMock()

    result = await putter_fn(mock_self, instance, 1)

    assert result == 1
    assert state.reference_loaded is True
    assert state.reference_source is ReferenceSource.PROMOTED
    assert state.reference_name == "<promoted>"
    assert state.reference_file_path is None
    assert state.last_diff is not None


@pytest.mark.asyncio
async def test_cmd_promote_ref_putter_reraises_when_no_acquire():
    """Promote on a fresh state (no successful acquire) must propagate
    NoLastAcquireError so caproto encodes it as a CA write error."""
    state = AppState(bpm_prefixes=["FAKE:BPM1"])
    assert state.last_acquire.ok_count == 0

    putter_fn = PyTxTPVGroup.cmd_promote_ref.pvspec.put
    mock_self = MagicMock()
    mock_self._state = state
    mock_self._reader = None
    instance = MagicMock()

    with pytest.raises(NoLastAcquireError):
        await putter_fn(mock_self, instance, 1)


@pytest.mark.asyncio
async def test_cmd_clear_ref_putter_clears_reference():
    """A caput to CMD:CLEAR_REF unloads a loaded reference (acts on _state)."""
    prefixes = ["FAKE:BPM1", "FAKE:BPM2"]
    state = AppState(bpm_prefixes=prefixes)
    reader = SyntheticBpmReader(prefixes)
    await handle_acquire(state, reader)
    await handle_promote_ref(state)
    assert state.reference_loaded is True

    putter_fn = PyTxTPVGroup.cmd_clear_ref.pvspec.put
    mock_self = MagicMock()
    mock_self._state = state
    mock_self._reader = None
    instance = MagicMock()

    result = await putter_fn(mock_self, instance, 1)

    assert result == 1
    assert state.reference_loaded is False
    assert state.reference_source is ReferenceSource.NONE
    assert state.last_diff is None


@pytest.mark.asyncio
async def test_cmd_clear_ref_putter_idempotent_when_clear():
    """Clear on an already-clear state succeeds (no alarm)."""
    state = AppState(bpm_prefixes=["FAKE:BPM1"])
    assert state.reference_loaded is False

    putter_fn = PyTxTPVGroup.cmd_clear_ref.pvspec.put
    mock_self = MagicMock()
    mock_self._state = state
    mock_self._reader = None
    instance = MagicMock()

    result = await putter_fn(mock_self, instance, 1)

    assert result == 1
    assert state.reference_loaded is False
