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


_SLOW_DELAY_S_DEFAULT = 3.0  # > production per_pv_timeout_s=2.0


def _make_slow_bpm_group(prefix: str, bpm_index: int, delay_s: float) -> PVGroup:
    """Like _make_bpm_group, but each pvproperty has an async getter that
    sleeps `delay_s` seconds before returning the static value. Used to
    exercise BpmReader._read_one's per-PV wait_for timeout path."""
    x_nm, y_nm, sum_au = _synthesize_waveforms(bpm_index)

    async def slow_c0_read(group, instance):
        await asyncio.sleep(delay_s)
        return instance.value

    async def slow_c1_read(group, instance):
        await asyncio.sleep(delay_s)
        return instance.value

    async def slow_c3_read(group, instance):
        await asyncio.sleep(delay_s)
        return instance.value

    async def slow_armed_read(group, instance):
        await asyncio.sleep(delay_s)
        return instance.value

    class SlowFakeBPM(PVGroup):
        c0 = pvproperty(
            slow_c0_read,
            value=x_nm.tolist(), dtype=int, read_only=True,
            name="wfr:TBT:c0", max_length=_SAMPLES,
        )
        c1 = pvproperty(
            slow_c1_read,
            value=y_nm.tolist(), dtype=int, read_only=True,
            name="wfr:TBT:c1", max_length=_SAMPLES,
        )
        c3 = pvproperty(
            slow_c3_read,
            value=sum_au.tolist(), dtype=int, read_only=True,
            name="wfr:TBT:c3", max_length=_SAMPLES,
        )
        armed = pvproperty(
            slow_armed_read,
            value=0, dtype=int, read_only=True,
            name="wfr:TBT:armed",
        )

    return SlowFakeBPM(prefix=prefix + ":" if not prefix.endswith(":") else prefix)


@dataclass
class FakeBpmIoc:
    """Handle returned from the fixture. Holds the running context and the
    list of BPM prefixes it's serving. Use for fault injection in M3 tasks."""
    prefixes: list[str]
    _context: Context
    _task: asyncio.Task


@pytest_asyncio.fixture
async def fake_bpm_ioc(request) -> FakeBpmIoc:
    """Parametrize via @pytest.mark.parametrize('fake_bpm_ioc', [N_or_list_or_dict], indirect=True).

    Three accepted forms for `request.param`:
    - int N → prefixes are ["FAKE:BPM1", ..., "FAKE:BPMN"], all healthy.
    - list[str] → those exact prefixes, all healthy.
    - dict with optional keys:
        - "n" (int) OR "prefixes" (list[str]) — defines the prefix set (mutually exclusive).
        - "offline" (list[str], optional) — these prefixes are reported in
          fixture.prefixes but their PVs are not built into the IOC, so
          BpmReader sees them as unreachable.
        - "slow" (list[str], optional) — these prefixes serve PVs whose
          async getters sleep _SLOW_DELAY_S_DEFAULT seconds before returning.
          PVs resolve on connect; the delay surfaces only on read. Used to
          exercise BpmReader._read_one's per-PV wait_for timeout path.
    """
    param = request.param if hasattr(request, "param") else 1

    offline_set: set[str] = set()
    slow_set: set[str] = set()
    if isinstance(param, int):
        prefixes = [f"FAKE:BPM{i+1}" for i in range(param)]
    elif isinstance(param, list):
        prefixes = list(param)
    elif isinstance(param, dict):
        if "n" in param and "prefixes" in param:
            raise ValueError("fake_bpm_ioc: pass either 'n' or 'prefixes', not both")
        if "n" in param:
            prefixes = [f"FAKE:BPM{i+1}" for i in range(int(param["n"]))]
        elif "prefixes" in param:
            prefixes = list(param["prefixes"])
        else:
            raise ValueError("fake_bpm_ioc dict param needs 'n' or 'prefixes'")
        offline_set = set(param.get("offline", []))
        slow_set = set(param.get("slow", []))
    else:
        raise TypeError(
            f"fake_bpm_ioc: unsupported param type {type(param).__name__}"
        )

    # Build PVGroups: offline prefixes get no PVs; slow prefixes get delayed reads.
    groups = []
    for i, p in enumerate(prefixes):
        if p in offline_set:
            continue
        if p in slow_set:
            groups.append(_make_slow_bpm_group(p, i, _SLOW_DELAY_S_DEFAULT))
        else:
            groups.append(_make_bpm_group(p, i))
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
        # Force-close caproto sockets first so any blocked UDP recv unblocks
        # and the task can actually respond to cancel(). See decisions log
        # entry "IOC server shutdown blocks on appsdev2" (2026-05-20).
        for sock in list(getattr(ctx, "tcp_sockets", {}).values()):
            with contextlib.suppress(Exception):
                sock.close()
        for sock in list(getattr(ctx, "udp_socks", {}).values()):
            with contextlib.suppress(Exception):
                sock.close()
        for entry in list(getattr(ctx, "beacon_socks", {}).values()):
            sock = entry[1] if isinstance(entry, tuple) and len(entry) > 1 else entry
            with contextlib.suppress(Exception):
                sock.close()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=2.0)
