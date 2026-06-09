"""Deterministic in-memory corrector writer for e2e and demo use.

Mirrors the `CorrectorWriter` interface (channels / read_setpoints /
write_setpoints / start / stop) but holds setpoints in a dict instead of
talking to EPICS. Selected at composition time alongside the synthetic BPM
reader (``PYTXT_USE_SYNTHETIC_READER=1``) so the active corrector path
(``CMD:STEP_CM``, the Correctors panel) is fully exercisable without a ring.

Never used in production — production wires the real ``CorrectorWriter``.
"""
from __future__ import annotations

from pytxt.config.corrector_channels import CorrectorChannel


class SyntheticCorrectorWriter:
    """No-CA corrector writer with in-memory setpoints.

    Setpoints seed to a small deterministic per-index pattern (within each
    channel's limit) so a dry-run "preview" shows non-zero current values.
    """

    def __init__(
        self,
        hcm_channels: list[CorrectorChannel],
        vcm_channels: list[CorrectorChannel],
    ) -> None:
        self._channels: dict[str, list[CorrectorChannel]] = {
            "HCM": list(hcm_channels),
            "VCM": list(vcm_channels),
        }
        # family -> list[float] setpoints, index-aligned with _channels[family].
        self._setpoints: dict[str, list[float]] = {}
        for family, chans in self._channels.items():
            self._setpoints[family] = [
                round(0.05 * ((i % 5) - 2), 4) for i in range(len(chans))
            ]

    def channels(self, family: str) -> list[CorrectorChannel]:
        self._require_family(family)
        return self._channels[family]

    def _require_family(self, family: str) -> None:
        if family not in self._channels:
            raise ValueError(f"unknown corrector family {family!r} (expected HCM or VCM)")

    async def start(self) -> None:  # protocol no-op
        return None

    async def stop(self) -> None:  # protocol no-op
        return None

    def _check_indices(self, family: str, indices: list[int]) -> None:
        self._require_family(family)
        n = len(self._channels[family])
        for i in indices:
            if i < 0 or i >= n:
                raise IndexError(f"{family} index {i} out of range (0..{n - 1})")

    async def read_setpoints(self, family: str, indices: list[int]) -> list[float]:
        self._check_indices(family, indices)
        sp = self._setpoints[family]
        return [sp[i] for i in indices]

    async def write_setpoints(
        self, family: str, indices: list[int], values_a: list[float]
    ) -> None:
        if len(indices) != len(values_a):
            raise ValueError(
                f"indices/values length mismatch ({len(indices)}/{len(values_a)})"
            )
        self._check_indices(family, indices)
        sp = self._setpoints[family]
        for i, v in zip(indices, values_a):
            sp[i] = float(v)
