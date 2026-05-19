"""Caproto-based fake BPM IOC fixture for integration tests.

Spins up N PVGroups in-process (one per BPM prefix) on the conftest-pinned
ephemeral CA port. Each fake BPM publishes:

- {prefix}:wfr:TBT:c0  — X waveform (100000 int32, nm)
- {prefix}:wfr:TBT:c1  — Y waveform (100000 int32, nm)
- {prefix}:wfr:TBT:c3  — sum signal (100000 int32, AU)
- {prefix}:wfr:TBT:armed — scalar uint16 (0 = data ready)

Synthesized data has a sum-signal step at sample 1370 so injection-turn
detection produces deterministic results. X/Y are zero-mean noise with
a small offset (~80 µm) that varies per BPM index. armed is 0 by default;
fault injection via fixture.bpm_offline / fixture.bpm_timeout flips behavior.
"""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Iterator

import numpy as np
import pytest
import pytest_asyncio
from caproto import ChannelType
from caproto.asyncio.server import Context
from caproto.server import PVGroup, pvproperty


_SAMPLES = 100000
_INJECTION_SAMPLE = 1370


def _synthesize_waveforms(bpm_index: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (x_nm, y_nm, sum_au) for one BPM.

    sum_au has a clear step at sample _INJECTION_SAMPLE so detect_injection_turn
    returns that index deterministically. x_nm and y_nm have a small per-BPM
    DC offset plus low-amplitude noise — realistic order of magnitude.
    """
    rng = np.random.default_rng(seed=42 + bpm_index)
    # Sum signal: low background, step up at injection, decay over ~5000 turns
    sum_au = np.full(_SAMPLES, 1000, dtype=np.int32)
    sum_au[_INJECTION_SAMPLE:] = 200_000
    decay = np.linspace(1.0, 0.5, _SAMPLES - _INJECTION_SAMPLE)
    sum_au[_INJECTION_SAMPLE:] = (sum_au[_INJECTION_SAMPLE:] * decay).astype(np.int32)
    sum_au += rng.integers(-500, 500, size=_SAMPLES, dtype=np.int32)

    # X/Y position waveforms: per-BPM DC offset + noise (in nm)
    x_offset_nm = int(80_000 * np.sin(bpm_index * 0.05))   # ±80 µm across BPMs
    y_offset_nm = int(80_000 * np.cos(bpm_index * 0.05))
    x_nm = np.full(_SAMPLES, x_offset_nm, dtype=np.int32) + \
           rng.integers(-5000, 5000, size=_SAMPLES, dtype=np.int32)
    y_nm = np.full(_SAMPLES, y_offset_nm, dtype=np.int32) + \
           rng.integers(-5000, 5000, size=_SAMPLES, dtype=np.int32)

    return x_nm, y_nm, sum_au


def _make_bpm_group(prefix: str, bpm_index: int) -> PVGroup:
    """Build a PVGroup serving the four TBT PVs for one BPM."""
    x_nm, y_nm, sum_au = _synthesize_waveforms(bpm_index)

    class FakeBPM(PVGroup):
        c0 = pvproperty(
            value=x_nm.tolist(), dtype=int, read_only=True,
            name="wfr:TBT:c0", max_length=_SAMPLES,
        )
        c1 = pvproperty(
            value=y_nm.tolist(), dtype=int, read_only=True,
            name="wfr:TBT:c1", max_length=_SAMPLES,
        )
        c3 = pvproperty(
            value=sum_au.tolist(), dtype=int, read_only=True,
            name="wfr:TBT:c3", max_length=_SAMPLES,
        )
        armed = pvproperty(
            value=0, dtype=int, read_only=True,
            name="wfr:TBT:armed",
        )

    # The prefix in caproto's PVGroup gets prepended to each pvproperty name.
    # We want SR01C:BPM1:wfr:TBT:c0, so prefix = "SR01C:BPM1:"
    return FakeBPM(prefix=prefix + ":" if not prefix.endswith(":") else prefix)


@dataclass
class FakeBpmIoc:
    """Handle returned from the fixture. Holds the running context and the
    list of BPM prefixes it's serving. Use for fault injection in M3 tasks."""
    prefixes: list[str]
    _context: Context
    _task: asyncio.Task


@pytest_asyncio.fixture
async def fake_bpm_ioc(request) -> FakeBpmIoc:
    """Parametrize via @pytest.mark.parametrize('fake_bpm_ioc', [N_or_list], indirect=True).

    If param is an int N, generates prefixes ["FAKE:BPM1", "FAKE:BPM2", ...].
    If param is a list[str], uses those exact prefixes.
    """
    param = request.param if hasattr(request, "param") else 1
    if isinstance(param, int):
        prefixes = [f"FAKE:BPM{i+1}" for i in range(param)]
    else:
        prefixes = list(param)

    # Build all PVGroups and merge their pvdbs
    groups = [_make_bpm_group(p, i) for i, p in enumerate(prefixes)]
    pvdb: dict = {}
    for g in groups:
        pvdb.update(g.pvdb)

    ctx = Context(pvdb)
    task = asyncio.create_task(ctx.run(log_pv_names=False))
    # Give caproto a moment to bind sockets
    await asyncio.sleep(0.2)

    handle = FakeBpmIoc(prefixes=prefixes, _context=ctx, _task=task)
    try:
        yield handle
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
