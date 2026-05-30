"""Unit: CMD:LOAD_REF / CMD:SAVE_REF putters dispatch to the canonical
LOAD/SAVE handlers and surface typed exceptions to CA clients.

Symmetric to REST's /api/v1/cmd/{load_ref,save_ref}. Mirrors the structure of
tests/unit/test_cmd_reference_putters.py: each putter coroutine is called
directly with a mock self carrying a real AppState + a tmp_path reference_dir
(no running IOC/Context), exercising the adapter wiring without caproto loopback.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock

import numpy as np
import pytest

from pytxt.api.schemas.result import AcquireStatus, LastAcquireResult
from pytxt.domain.types import RawBPM, ReferenceSource
from pytxt.handlers.reference import (
    InvalidReferenceNameError,
    ReferenceNotFoundError,
)
from pytxt.ioc.pvs import PyTxTPVGroup
from pytxt.state.app_state import AppState


def _fake_raw(prefix: str) -> RawBPM:
    """A BPM whose sum waveform jumps at sample 1370 → finite first-turn."""
    sum_wf = np.full(100000, 1000, dtype=np.int32)
    sum_wf[1370:] = 200000
    return RawBPM(
        prefix=prefix,
        x_wf=np.full(100000, 80_000, dtype=np.int32),
        y_wf=np.zeros(100000, dtype=np.int32),
        sum_wf=sum_wf,
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )


def _acquired_state(prefixes: list[str]) -> AppState:
    """An AppState that looks like it just completed a successful acquire."""
    raws = {p: _fake_raw(p) for p in prefixes}
    return AppState(
        bpm_prefixes=prefixes,
        last_acquire_raws=raws,
        last_acquire=LastAcquireResult(
            status=AcquireStatus.OK,
            ok_count=len(prefixes),
            fail_count=0,
            failed_bpm_names=[],
            injection_turn_median=1370,
            timestamp=datetime.now(timezone.utc),
        ),
    )


@pytest.mark.asyncio
async def test_cmd_save_ref_putter_writes_file(tmp_path):
    """A caput to CMD:SAVE_REF after an acquire writes a .mat into the library
    and leaves AppState untouched (SAVE is not LOAD)."""
    state = _acquired_state(["FAKE:BPM1", "FAKE:BPM2"])

    putter_fn = PyTxTPVGroup.cmd_save_ref.pvspec.put
    mock_self = MagicMock()
    mock_self._state = state
    mock_self._reference_dir = tmp_path
    instance = MagicMock()

    result = await putter_fn(mock_self, instance, "foo.mat")

    assert result == "foo.mat"
    assert (tmp_path / "foo.mat").exists()
    # SAVE must not mutate state.
    assert state.reference_loaded is False


@pytest.mark.asyncio
async def test_cmd_save_ref_putter_empty_string_uses_timestamp_default(tmp_path):
    """An empty CA string maps to None → handler's timestamp default name."""
    state = _acquired_state(["FAKE:BPM1", "FAKE:BPM2"])

    putter_fn = PyTxTPVGroup.cmd_save_ref.pvspec.put
    mock_self = MagicMock()
    mock_self._state = state
    mock_self._reference_dir = tmp_path
    instance = MagicMock()

    result = await putter_fn(mock_self, instance, "")

    assert result == ""
    mats = list(tmp_path.glob("*_reference_trajectory.mat"))
    assert len(mats) == 1


@pytest.mark.asyncio
async def test_cmd_load_ref_putter_loads_reference(tmp_path):
    """SAVE then a caput to CMD:LOAD_REF populates the reference state (FILE)."""
    prefixes = ["FAKE:BPM1", "FAKE:BPM2"]

    # Seed the library via the SAVE putter.
    save_state = _acquired_state(prefixes)
    save_fn = PyTxTPVGroup.cmd_save_ref.pvspec.put
    save_self = MagicMock()
    save_self._state = save_state
    save_self._reference_dir = tmp_path
    await save_fn(save_self, MagicMock(), "foo.mat")
    assert (tmp_path / "foo.mat").exists()

    # Load into a fresh acquired state.
    state = _acquired_state(prefixes)
    load_fn = PyTxTPVGroup.cmd_load_ref.pvspec.put
    mock_self = MagicMock()
    mock_self._state = state
    mock_self._reference_dir = tmp_path
    instance = MagicMock()

    result = await load_fn(mock_self, instance, "foo.mat")

    assert result == "foo.mat"
    assert state.reference_loaded is True
    assert state.reference_source is ReferenceSource.FILE
    assert state.reference_name == "foo.mat"
    assert state.reference_file_path == tmp_path / "foo.mat"


@pytest.mark.asyncio
async def test_cmd_load_ref_putter_reraises_bad_name(tmp_path):
    """A bad name must propagate InvalidReferenceNameError so caproto encodes
    it as a CA write error."""
    state = _acquired_state(["FAKE:BPM1", "FAKE:BPM2"])

    putter_fn = PyTxTPVGroup.cmd_load_ref.pvspec.put
    mock_self = MagicMock()
    mock_self._state = state
    mock_self._reference_dir = tmp_path
    instance = MagicMock()

    with pytest.raises(InvalidReferenceNameError):
        await putter_fn(mock_self, instance, "../escape.mat")

    assert state.reference_loaded is False


@pytest.mark.asyncio
async def test_cmd_load_ref_putter_reraises_not_found(tmp_path):
    """A missing file must propagate ReferenceNotFoundError to CA."""
    state = _acquired_state(["FAKE:BPM1", "FAKE:BPM2"])

    putter_fn = PyTxTPVGroup.cmd_load_ref.pvspec.put
    mock_self = MagicMock()
    mock_self._state = state
    mock_self._reference_dir = tmp_path
    instance = MagicMock()

    with pytest.raises(ReferenceNotFoundError):
        await putter_fn(mock_self, instance, "nope.mat")

    assert state.reference_loaded is False
