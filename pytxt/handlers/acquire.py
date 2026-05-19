"""Canonical handler for the ACQUIRE command.

Same function whether called by the IOC's CMD:ACQUIRE putter or the REST
POST route — agentic parity by construction. Concurrent attempts raise
AcquisitionInFlightError, surfaced as a CA alarm or HTTP 409 by callers.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Protocol

import numpy as np

from pytxt.api.schemas.result import (
    AcquireResponse,
    AcquireStatus,
    LastAcquireResult,
)
from pytxt.domain.first_turn_extract import extract_first_turn
from pytxt.domain.types import RawBPM
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)


class AcquisitionInFlightError(RuntimeError):
    """Raised when ACQUIRE is triggered while one is already in progress."""


class _ReaderProtocol(Protocol):
    async def read_all(self) -> dict[str, RawBPM | None]: ...


def _classify(ok: int, fail: int) -> AcquireStatus:
    if ok == 0:
        return AcquireStatus.FAILED
    if fail > 0:
        return AcquireStatus.PARTIAL
    return AcquireStatus.OK


def _median_injection_turn(injection_turn: np.ndarray) -> int:
    valid = injection_turn[injection_turn >= 0]
    if valid.size == 0:
        return -1
    return int(np.median(valid))


async def handle_acquire(state: AppState, reader: _ReaderProtocol) -> AcquireResponse:
    """Orchestrate one acquisition.

    Sequence: check in-flight → set in-flight → read all BPMs in parallel
    → extract first-turn positions → publish via AppState update → return
    AcquireResponse. The in-flight flag is always cleared (try/finally).
    """
    if state.acquire_in_flight:
        raise AcquisitionInFlightError("ACQUIRE already in progress")

    try:
        await state.update(
            acquire_in_flight=True,
            last_acquire=LastAcquireResult(
                status=AcquireStatus.ACQUIRING,
                ok_count=0,
                fail_count=0,
                failed_bpm_names=[],
                injection_turn_median=-1,
                timestamp=None,
            ),
        )

        raws = await reader.read_all()
        first_turn = extract_first_turn(raws)

        # BpmReader.read_all guarantees one entry per configured prefix
        # (None for unreachable BPMs). first_turn.failed_bpm_names is exactly
        # the subset of raws keys whose value was None.
        ok_count = len(raws) - len(first_turn.failed_bpm_names)
        fail_count = len(first_turn.failed_bpm_names)
        status = _classify(ok_count, fail_count)
        median_turn = _median_injection_turn(first_turn.injection_turn)
        now = datetime.now(timezone.utc)

        last = LastAcquireResult(
            status=status,
            ok_count=ok_count,
            fail_count=fail_count,
            failed_bpm_names=first_turn.failed_bpm_names,
            injection_turn_median=median_turn,
            timestamp=now,
        )

        # Strip None entries from raws so /result/bpm/raw can simply look up by prefix.
        successful_raws = {p: r for p, r in raws.items() if r is not None}

        await state.update(
            last_acquire=last,
            last_acquire_raws=successful_raws,
        )

        return AcquireResponse(
            status=status.value,
            ok_count=ok_count,
            fail_count=fail_count,
            failed_bpm_names=first_turn.failed_bpm_names,
            injection_turn_median=median_turn,
            timestamp=now,
        )

    except Exception as exc:
        logger.exception("handle_acquire: unexpected error")
        await state.update(
            last_acquire=LastAcquireResult(
                status=AcquireStatus.FAILED,
                ok_count=0,
                fail_count=len(state.bpm_prefixes),
                failed_bpm_names=list(state.bpm_prefixes),
                injection_turn_median=-1,
                timestamp=datetime.now(timezone.utc),
                fail_reason=f"{type(exc).__name__}: {exc}",
            ),
        )
        raise
    finally:
        await state.update(acquire_in_flight=False)
