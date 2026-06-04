"""Unit tests for handle_step_cm (compare-and-set + clamp), fake writer."""
from __future__ import annotations

import pytest

from pytxt.config.corrector_channels import CorrectorChannel
from pytxt.handlers.threading import (
    CMPreconditionError,
    CMStepInFlightError,
    handle_step_cm,
)
from pytxt.state.app_state import AppState


class FakeWriter:
    """Minimal CorrectorWriter stand-in: 8 HCM + 8 VCM channels, max 35 A."""

    def __init__(self, readbacks: dict[str, list[float]] | None = None):
        self._readbacks = readbacks or {"HCM": [0.0] * 8, "VCM": [0.0] * 8}
        self.written: tuple | None = None

    def channels(self, family: str) -> list[CorrectorChannel]:
        if family not in ("HCM", "VCM"):
            raise ValueError(f"unknown corrector family {family!r}")
        return [CorrectorChannel(f"{family}{i}", 35.0, family, i) for i in range(8)]

    async def read_setpoints(self, family: str, indices: list[int]) -> list[float]:
        return [self._readbacks[family][i] for i in indices]

    async def write_setpoints(self, family, indices, values_a) -> None:
        self.written = (family, list(indices), list(values_a))


@pytest.mark.asyncio
async def test_applies_step_when_cas_matches():
    state = AppState()
    writer = FakeWriter({"HCM": [10.0, -5.0] + [0.0] * 6, "VCM": [0.0] * 8})
    resp = await handle_step_cm(
        state, writer, family="HCM", device_list=[0, 1], deltas=[2.0, 1.0],
        expected_prior_a=[10.0, -5.0], tol_a=0.01,
    )
    assert resp.status == "APPLIED"
    assert [c.new_value_a for c in resp.applied] == [12.0, -4.0]
    assert writer.written == ("HCM", [0, 1], [12.0, -4.0])
    assert state.last_cm_step.status == "APPLIED"
    assert state.last_cm_step.n_applied == 2
    assert state.cm_step_in_flight is False


@pytest.mark.asyncio
async def test_dry_run_writes_nothing():
    state = AppState()
    writer = FakeWriter({"HCM": [10.0] + [0.0] * 7, "VCM": [0.0] * 8})
    resp = await handle_step_cm(
        state, writer, family="HCM", device_list=[0], deltas=[2.0],
        expected_prior_a=[10.0], tol_a=0.01, dry_run=True,
    )
    assert resp.status == "DRY_RUN"
    assert resp.applied[0].new_value_a == 12.0
    assert writer.written is None
    assert state.last_cm_step.status == "DRY_RUN"


@pytest.mark.asyncio
async def test_cas_refusal_writes_nothing_and_records_refused():
    state = AppState()
    writer = FakeWriter({"HCM": [10.5] + [0.0] * 7, "VCM": [0.0] * 8})  # drifted 0.5
    with pytest.raises(CMPreconditionError) as exc:
        await handle_step_cm(
            state, writer, family="HCM", device_list=[0], deltas=[2.0],
            expected_prior_a=[10.0], tol_a=0.1,
        )
    assert exc.value.refused == ["HCM0"]
    assert writer.written is None
    assert state.last_cm_step.status == "REFUSED"
    assert state.cm_step_in_flight is False


@pytest.mark.asyncio
async def test_clamps_to_limit():
    state = AppState()
    writer = FakeWriter({"HCM": [34.0] + [0.0] * 7, "VCM": [0.0] * 8})
    resp = await handle_step_cm(
        state, writer, family="HCM", device_list=[0], deltas=[5.0],
        expected_prior_a=[34.0], tol_a=0.01,
    )
    assert resp.applied[0].new_value_a == 35.0
    assert resp.applied[0].clamped
    assert resp.n_clamped == 1
    assert writer.written == ("HCM", [0], [35.0])


@pytest.mark.asyncio
async def test_in_flight_collision_raises():
    state = AppState(cm_step_in_flight=True)
    with pytest.raises(CMStepInFlightError):
        await handle_step_cm(
            state, FakeWriter(), family="HCM", device_list=[0], deltas=[1.0],
            expected_prior_a=[0.0],
        )


@pytest.mark.asyncio
async def test_rejects_length_mismatch():
    with pytest.raises(ValueError, match="length mismatch"):
        await handle_step_cm(
            AppState(), FakeWriter(), family="HCM", device_list=[0, 1],
            deltas=[1.0], expected_prior_a=[0.0, 0.0],
        )


@pytest.mark.asyncio
async def test_rejects_out_of_range_index():
    with pytest.raises(ValueError, match="out of range"):
        await handle_step_cm(
            AppState(), FakeWriter(), family="HCM", device_list=[99],
            deltas=[1.0], expected_prior_a=[0.0],
        )


@pytest.mark.asyncio
async def test_rejects_unknown_family():
    with pytest.raises(ValueError):
        await handle_step_cm(
            AppState(), FakeWriter(), family="ZZZ", device_list=[0],
            deltas=[1.0], expected_prior_a=[0.0],
        )


@pytest.mark.asyncio
async def test_rejects_empty_device_list():
    with pytest.raises(ValueError, match="empty"):
        await handle_step_cm(
            AppState(), FakeWriter(), family="HCM", device_list=[],
            deltas=[], expected_prior_a=[],
        )


@pytest.mark.asyncio
async def test_in_flight_cleared_after_writer_error():
    class BoomWriter(FakeWriter):
        async def read_setpoints(self, family, indices):
            raise RuntimeError("CA boom")

    state = AppState()
    with pytest.raises(RuntimeError, match="boom"):
        await handle_step_cm(
            state, BoomWriter(), family="HCM", device_list=[0], deltas=[1.0],
            expected_prior_a=[0.0],
        )
    assert state.cm_step_in_flight is False
