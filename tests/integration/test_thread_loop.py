"""Integration: the threading loop controller (handle_thread_start/stop).

Uses a SimulatedRing closed-loop double — applying corrector deltas changes the
next BPM reading — so the loop's convergence, divergence guard, dry-run, and stop
behaviour are exercised without a real machine. Real closed-loop commissioning is
a control-room item (checklist B4).
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient

from pytxt.api.server import create_app
from pytxt.config.corrector_channels import CorrectorChannel
from pytxt.domain.threading import tikhonov_pinv
from pytxt.domain.types import FirstTurnResult, RawBPM, ResponseMatrix
from pytxt.handlers.threading import (
    ThreadConfigError,
    ThreadInFlightError,
    ThreadNoReferenceError,
    handle_thread_start,
    handle_thread_stop,
)
from pytxt.state.app_state import AppState

_N_BPMS = 2          # 2*N_BPMS == N_CM == 4 (square, fully correctable)
_N_HCM = 2
_N_VCM = 2
_SAMPLES = 100_000
_INJ = 1370


def _raw(prefix: str, x_mm: float, y_mm: float) -> RawBPM:
    """RawBPM whose detected first turn is (x_mm, y_mm)."""
    sum_wf = np.full(_SAMPLES, 1000, np.int32)
    sum_wf[_INJ:] = 200_000
    return RawBPM(
        prefix=prefix,
        x_wf=np.full(_SAMPLES, round(x_mm * 1e6), np.int32),
        y_wf=np.full(_SAMPLES, round(y_mm * 1e6), np.int32),
        sum_wf=sum_wf,
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )


class SimulatedRing:
    """Reader+writer double sharing orbit state: orbit = initial - plant @ cm."""

    def __init__(self, plant: np.ndarray, initial_orbit: np.ndarray, prefixes: list[str]):
        self.plant = plant
        self.initial = initial_orbit
        self.prefixes = prefixes
        self.cm = {"HCM": np.zeros(_N_HCM), "VCM": np.zeros(_N_VCM)}
        self._chans = {
            "HCM": [CorrectorChannel(f"H{i}", 1e9, "HCM", i) for i in range(_N_HCM)],
            "VCM": [CorrectorChannel(f"V{i}", 1e9, "VCM", i) for i in range(_N_VCM)],
        }

    def _orbit(self) -> np.ndarray:
        cm = np.concatenate([self.cm["HCM"], self.cm["VCM"]])
        return self.initial - self.plant @ cm

    # reader protocol
    async def read_all(self) -> dict[str, RawBPM]:
        orbit = self._orbit()
        n = len(self.prefixes)
        return {p: _raw(p, orbit[i], orbit[n + i]) for i, p in enumerate(self.prefixes)}

    # corrector-writer protocol
    def channels(self, family: str) -> list[CorrectorChannel]:
        return self._chans[family]

    async def read_setpoints(self, family: str, indices: list[int]) -> list[float]:
        return [float(self.cm[family][i]) for i in indices]

    async def write_setpoints(self, family: str, indices: list[int], values_a: list[float]) -> None:
        for i, v in zip(indices, values_a):
            self.cm[family][i] = v


def _matrix(plant: np.ndarray) -> ResponseMatrix:
    return ResponseMatrix(
        mplus=tikhonov_pinv(plant, alpha=0.01, damping=1.0),
        bpm_names=[f"BPM{i}" for i in range(_N_BPMS)],
        hcm_names=[f"H{i}" for i in range(_N_HCM)],
        vcm_names=[f"V{i}" for i in range(_N_VCM)],
        bpm_s=np.arange(_N_BPMS, dtype=float),
        cm_s=np.full(_N_HCM + _N_VCM, -1.0),   # all upstream -> no downstream-zeroing
        units="mm->amp", energy_gev=1.9, provenance="sim",
    )


def _state_with_zero_reference(prefixes: list[str]) -> AppState:
    """AppState with a zeroed reference loaded (R0=0 -> diff == live orbit)."""
    n = len(prefixes)
    state = AppState(version="0.1.0", bpm_prefixes=prefixes)
    state.reference_loaded = True
    state.reference_first_turn = FirstTurnResult(
        x_first_turn=np.zeros(n), y_first_turn=np.zeros(n),
        sum_first_turn=np.full(n, np.nan), injection_turn=np.full(n, -1, np.int32),
        failed_bpm_names=[],
    )
    return state


def _prefixes() -> list[str]:
    return [f"BPM{i}" for i in range(_N_BPMS)]


# --- convergence / dry-run / caps ---------------------------------------

@pytest.mark.asyncio
async def test_converges_with_simulated_ring():
    rng = np.random.default_rng(0)
    plant = rng.standard_normal((4, 4))
    sim = SimulatedRing(plant, initial_orbit=np.array([1.0, -0.8, 0.6, -0.4]), prefixes=_prefixes())
    state = _state_with_zero_reference(_prefixes())

    resp = await handle_thread_start(
        state, reader=sim, response_matrix=_matrix(plant), corrector_writer=sim,
        max_steps=20, gain=0.5, conv_rms_mm=1e-3,
    )
    assert resp.status == "CONVERGED"
    assert resp.final_rms_mm <= 1e-3
    assert resp.iterations < 20
    # RMS monotonically non-increasing
    assert all(b <= a + 1e-9 for a, b in zip(resp.rms_history_mm, resp.rms_history_mm[1:]))
    assert state.thread_running is False


@pytest.mark.asyncio
async def test_dry_run_writes_no_correctors():
    rng = np.random.default_rng(1)
    plant = rng.standard_normal((4, 4))
    sim = SimulatedRing(plant, initial_orbit=np.array([1.0, 1.0, 1.0, 1.0]), prefixes=_prefixes())
    state = _state_with_zero_reference(_prefixes())

    resp = await handle_thread_start(
        state, reader=sim, response_matrix=_matrix(plant), corrector_writer=sim,
        max_steps=3, gain=0.5, dry_run=True,
    )
    assert resp.status == "MAX_STEPS"
    assert resp.dry_run is True
    # No correctors moved -> orbit constant -> RMS history flat
    assert np.allclose(sim.cm["HCM"], 0.0) and np.allclose(sim.cm["VCM"], 0.0)
    assert len(set(round(r, 9) for r in resp.rms_history_mm)) == 1


@pytest.mark.asyncio
async def test_max_steps_cap_when_no_convergence_threshold():
    rng = np.random.default_rng(2)
    plant = rng.standard_normal((4, 4))
    sim = SimulatedRing(plant, initial_orbit=np.array([1.0, 1.0, 1.0, 1.0]), prefixes=_prefixes())
    state = _state_with_zero_reference(_prefixes())
    resp = await handle_thread_start(
        state, reader=sim, response_matrix=_matrix(plant), corrector_writer=sim,
        max_steps=3, gain=0.5,  # no conv_rms_mm
    )
    assert resp.status == "MAX_STEPS"
    assert resp.iterations == 3


@pytest.mark.asyncio
async def test_divergence_guard_trips():
    """A reader whose orbit grows each read trips the divergence guard."""
    class DivergingReader:
        def __init__(self):
            self.scale = 1.0
            self.cm = {"HCM": np.zeros(_N_HCM), "VCM": np.zeros(_N_VCM)}
            self._chans = {"HCM": [CorrectorChannel(f"H{i}", 1e9, "HCM", i) for i in range(_N_HCM)],
                           "VCM": [CorrectorChannel(f"V{i}", 1e9, "VCM", i) for i in range(_N_VCM)]}

        async def read_all(self):
            orbit = np.array([self.scale, self.scale])
            self.scale *= 2.0  # grow every read
            return {f"BPM{i}": _raw(f"BPM{i}", orbit[i], 0.0) for i in range(_N_BPMS)}

        def channels(self, family): return self._chans[family]
        async def read_setpoints(self, family, indices): return [0.0 for _ in indices]
        async def write_setpoints(self, family, indices, values): pass

    rng = np.random.default_rng(3)
    plant = rng.standard_normal((4, 4))
    sim = DivergingReader()
    state = _state_with_zero_reference(_prefixes())
    resp = await handle_thread_start(
        state, reader=sim, response_matrix=_matrix(plant), corrector_writer=sim,
        max_steps=10, gain=0.5,
    )
    assert resp.status == "DIVERGED"
    assert resp.iterations >= 2


@pytest.mark.asyncio
async def test_cooperative_stop():
    """A concurrent STOP (set during a read) halts the loop next iteration."""
    state = _state_with_zero_reference(_prefixes())
    rng = np.random.default_rng(4)
    plant = rng.standard_normal((4, 4))

    class StoppingSim(SimulatedRing):
        def __init__(self, *a):
            super().__init__(*a)
            self.reads = 0

        async def read_all(self):
            self.reads += 1
            if self.reads == 1:
                await handle_thread_stop(state)  # request stop after first read
            return await super().read_all()

    sim = StoppingSim(plant, np.array([1.0, 1.0, 1.0, 1.0]), _prefixes())
    resp = await handle_thread_start(
        state, reader=sim, response_matrix=_matrix(plant), corrector_writer=sim,
        max_steps=20, gain=0.5,
    )
    assert resp.status == "STOPPED"
    assert resp.iterations == 1


# --- guards --------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_reference_raises():
    state = AppState(version="0.1.0", bpm_prefixes=_prefixes())  # no reference loaded
    plant = np.eye(4)
    with pytest.raises(ThreadNoReferenceError):
        await handle_thread_start(state, reader=object(), response_matrix=_matrix(plant))


@pytest.mark.asyncio
async def test_no_matrix_raises():
    state = _state_with_zero_reference(_prefixes())
    with pytest.raises(ThreadConfigError):
        await handle_thread_start(state, reader=object(), response_matrix=None)


@pytest.mark.asyncio
async def test_live_run_without_writer_raises():
    state = _state_with_zero_reference(_prefixes())
    plant = np.eye(4)
    with pytest.raises(ThreadConfigError):
        await handle_thread_start(
            state, reader=object(), response_matrix=_matrix(plant),
            corrector_writer=None, dry_run=False,
        )


@pytest.mark.asyncio
async def test_in_flight_raises():
    state = _state_with_zero_reference(_prefixes())
    state.thread_running = True
    plant = np.eye(4)
    with pytest.raises(ThreadInFlightError):
        await handle_thread_start(state, reader=object(), response_matrix=_matrix(plant))


@pytest.mark.asyncio
async def test_stop_is_idempotent_when_idle():
    state = AppState(version="0.1.0")
    resp = await handle_thread_stop(state)
    assert resp.stop_requested is True
    assert state.thread_stop_requested is True


# --- REST surface --------------------------------------------------------

@pytest.mark.asyncio
async def test_rest_dry_run_thread_start():
    rng = np.random.default_rng(5)
    plant = rng.standard_normal((4, 4))
    sim = SimulatedRing(plant, np.array([1.0, 1.0, 1.0, 1.0]), _prefixes())
    state = _state_with_zero_reference(_prefixes())
    app = create_app(state=state, response_matrix=_matrix(plant))
    app.state.bpm_reader = sim
    app.state.corrector_writer = sim

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/thread_start", json={"max_steps": 3, "dry_run": True})
        assert r.status_code == 200
        assert r.json()["status"] == "MAX_STEPS"
        rs = await ac.post("/api/v1/cmd/thread_stop", json={})
        assert rs.status_code == 200


@pytest.mark.asyncio
async def test_rest_no_matrix_returns_503():
    state = _state_with_zero_reference(_prefixes())
    app = create_app(state=state)  # no response_matrix
    app.state.bpm_reader = object()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/thread_start", json={"dry_run": True})
        assert r.status_code == 503


@pytest.mark.asyncio
async def test_rest_no_reference_returns_422():
    rng = np.random.default_rng(6)
    plant = rng.standard_normal((4, 4))
    state = AppState(version="0.1.0", bpm_prefixes=_prefixes())  # no reference
    app = create_app(state=state, response_matrix=_matrix(plant))
    app.state.bpm_reader = SimulatedRing(plant, np.zeros(4), _prefixes())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/thread_start", json={"dry_run": True})
        assert r.status_code == 422
