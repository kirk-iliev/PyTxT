"""Deterministic BPM reader for e2e and demo use.

Returns synthetic `RawBPM` waveforms that match the shape and dtype of
real CA reads, with a sum-waveform rising edge at sample 1370 so the
domain's first-turn extraction finds a real injection turn.

Selected at composition time by setting ``PYTXT_USE_SYNTHETIC_READER=1``.
Never used in production — production wires the real ``BpmReader``.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from pytxt.domain.types import RawBPM

_N_SAMPLES = 100_000
_INJECTION_INDEX = 1370


class SyntheticBpmReader:
    """No-CA reader returning deterministic per-prefix waveforms.

    The injection-step pattern matches the production sum-waveform shape
    closely enough that `pytxt.domain.first_turn_extract.extract_first_turn`
    detects a sensible per-BPM injection turn.
    """

    def __init__(self, prefixes: list[str]) -> None:
        self.prefixes = list(prefixes)
        # Per-call counter: consecutive read_all() calls return slightly
        # different amplitudes so a reference promoted on one acquire shows a
        # non-zero B − R0 diff on the next. Bounded (modulo) and deterministic,
        # so it stays reproducible; per-prefix variation is preserved.
        self._call = 0

    async def start(self) -> None:  # noqa: D401 - protocol no-op
        """Match the BpmReader protocol; nothing to connect to."""
        return None

    async def read_all(self) -> dict[str, RawBPM | None]:
        now = datetime.now(timezone.utc)
        out: dict[str, RawBPM | None] = {}
        sum_wf = np.full(_N_SAMPLES, 1000, dtype=np.int32)
        sum_wf[_INJECTION_INDEX:] = 200_000
        # Adjacent integers mod 7 / mod 5 always differ, so the diff between
        # consecutive acquires is always a clearly-visible >= ~0.02 mm step.
        x_jitter = 30_000 * (self._call % 7)
        y_jitter = 20_000 * (self._call % 5)
        self._call += 1
        for i, prefix in enumerate(self.prefixes):
            # Vary x/y per BPM so the rendered polyline shows a non-flat
            # pattern. Amplitude in nm; rendered as mm after /1e6.
            x_amp = 80_000 + 5_000 * i + x_jitter
            y_amp = 40_000 - 3_000 * i + y_jitter
            x_wf = np.full(_N_SAMPLES, x_amp, dtype=np.int32)
            y_wf = np.full(_N_SAMPLES, y_amp, dtype=np.int32)
            out[prefix] = RawBPM(
                prefix=prefix,
                x_wf=x_wf,
                y_wf=y_wf,
                sum_wf=sum_wf,
                armed=0,
                read_timestamp=now,
            )
        return out
