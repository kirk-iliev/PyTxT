"""AppState — single in-process source of truth.

A typed dataclass plus async change-notification. Subsystems (the IOC,
REST routes, the WS bridge, future CA client) read AppState as needed
and mutate it via `update()`. Listeners registered via `subscribe()`
are invoked on change.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from pytxt.api.schemas.result import AcquireStatus, LastAcquireResult
from pytxt.api.schemas.threading import (
    LastCMStepResult,
    LastInjectResult,
    ThreadStateResult,
)
from pytxt.domain.types import DiffResult, FirstTurnResult, ReferenceSource

logger = logging.getLogger(__name__)

ListenerFn = Callable[[Any], Awaitable[None]]


def _initial_last_acquire() -> LastAcquireResult:
    return LastAcquireResult(
        status=AcquireStatus.NEVER,
        ok_count=0,
        fail_count=0,
        failed_bpm_names=[],
        injection_turn_median=-1,
        timestamp=None,
    )


@dataclass
class AppState:
    # === Phase 1 published fields ===
    heartbeat: int = 0
    last_ping_at: Optional[str] = None
    ping_count: int = 0
    version: str = ""
    started_at: float = 0.0
    uptime_s_pushed: float = 0.0

    # === Phase 2 published fields ===
    bpm_prefixes: list[str] = field(default_factory=list)
    acquire_in_flight: bool = False
    last_acquire: LastAcquireResult = field(default_factory=_initial_last_acquire)
    # In-memory only: raw waveforms from the most recent acquisition,
    # served by GET /api/v1/result/bpm/raw. Not mirrored to PVs.
    last_acquire_raws: dict = field(default_factory=dict)

    # === Phase 3 reference state (all-or-nothing) ===
    # When reference_loaded is False, every other reference_* field is at its
    # empty default. Flips on PROMOTE_REF / CLEAR_REF.
    reference_loaded: bool = False
    reference_name: str = ""
    reference_loaded_at: Optional[datetime] = None
    reference_source: ReferenceSource = ReferenceSource.NONE
    reference_first_turn: Optional[FirstTurnResult] = None
    reference_file_path: Optional[Path] = None  # always None in M2 (file backing is M3)
    reference_bpm_names: Optional[list[str]] = None
    last_diff: Optional[DiffResult] = None  # None → diff PVs NaN-filled

    # === Phase 4 threading state ===
    cm_step_in_flight: bool = False
    last_cm_step: LastCMStepResult = field(default_factory=LastCMStepResult)
    inject_in_flight: bool = False
    last_inject: LastInjectResult = field(default_factory=LastInjectResult)
    # Threading loop controller
    thread_running: bool = False
    thread_stop_requested: bool = False
    thread_state: ThreadStateResult = field(default_factory=ThreadStateResult)

    # Internal: per-field listener lists (excluded from repr/init)
    _listeners: dict[str, list[ListenerFn]] = field(
        default_factory=dict, init=False, repr=False
    )

    @property
    def uptime_s(self) -> float:
        """Seconds since process start. Zero if started_at not set."""
        return time.time() - self.started_at if self.started_at else 0.0

    def subscribe(self, field_name: str, callback: ListenerFn) -> None:
        """Register an async callback to fire when `field_name` changes."""
        self._listeners.setdefault(field_name, []).append(callback)

    async def update(self, **changes: Any) -> None:
        """Atomically apply changes and notify listeners.

        Two-pass: apply *all* field changes first, then fire listeners. This
        guarantees a listener reading other fields of `self` always sees the
        post-update state, not a half-applied snapshot from mid-iteration.
        Important for multi-field updates like:

            state.update(last_acquire=..., last_acquire_raws=...)

        where a listener on `last_acquire` needs to read `last_acquire_raws`.

        - Equality check suppresses spurious notifications.
        - Per-listener try/except: a failing listener logs and is skipped;
          other listeners on the same field still fire.
        - Raises AttributeError on unknown or internal field names (catches
          caller typos at the source of the mutation).
        """
        # Pass 1: validate + apply
        actually_changed: list[tuple[str, Any]] = []
        for k, v in changes.items():
            if k.startswith("_") or not hasattr(self, k) or callable(getattr(type(self), k, None)):
                raise AttributeError(f"AppState has no settable field {k!r}")
            old = getattr(self, k)
            # Some fields hold numpy-bearing structures (e.g. dict[str, RawBPM]
            # for last_acquire_raws). Numpy's element-wise __eq__ + Python's
            # bool() on the result raises ValueError. Treat any uncomparable
            # value as "changed" — that's the safe semantic when we can't tell.
            try:
                unchanged = bool(old == v)
            except (ValueError, TypeError):
                unchanged = False
            if unchanged:
                continue
            setattr(self, k, v)
            actually_changed.append((k, v))

        # Pass 2: notify (state is now fully consistent)
        for k, v in actually_changed:
            for cb in self._listeners.get(k, []):
                try:
                    await cb(v)
                except Exception:
                    logger.exception(
                        "AppState listener for field %r failed; "
                        "other listeners still fired",
                        k,
                    )
