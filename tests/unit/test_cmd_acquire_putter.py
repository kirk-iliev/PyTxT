"""Unit: cmd_acquire putter must surface AcquisitionInFlightError to CA clients.

Spec: docs/superpowers/specs/2026-05-18-phase-2-read-path-design.md §11 M3.
Symmetric to REST's 409 returned by /api/v1/cmd/acquire when a concurrent
acquire is in flight (see tests/integration/test_acquire_via_rest.py).
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from pytxt.handlers.acquire import AcquisitionInFlightError
from pytxt.ioc.pvs import PyTxTPVGroup
from pytxt.state.app_state import AppState


@pytest.mark.asyncio
async def test_cmd_acquire_putter_reraises_when_in_flight():
    """A caput while in-flight must propagate AcquisitionInFlightError so
    caproto encodes it as a CA write error to the client."""
    state = AppState(bpm_prefixes=["FAKE:BPM1"], acquire_in_flight=True)
    reader = AsyncMock()  # never gets called because the in-flight guard fires first

    # The putter coroutine is stored as an unbound function at pvspec.put.
    # Call it directly with a mock self (we only need _state and _reader attributes).
    putter_fn = PyTxTPVGroup.cmd_acquire.pvspec.put
    mock_self = MagicMock()
    mock_self._state = state
    mock_self._reader = reader
    instance = MagicMock()  # caproto passes a ChannelData; the putter doesn't use it

    with pytest.raises(AcquisitionInFlightError):
        await putter_fn(mock_self, instance, 1)
