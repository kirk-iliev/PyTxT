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
from typing import Any, Awaitable, Callable, Optional

from pytxt.api.schemas.result import AcquireStatus, LastAcquireResult

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

        - Equality check suppresses spurious notifications.
        - Per-listener try/except: a failing listener logs and is skipped;
          other listeners on the same field still fire.
        - Raises AttributeError on unknown or internal field names (catches
          caller typos at the source of the mutation).
        """
        for k, v in changes.items():
            if k.startswith("_") or not hasattr(self, k) or callable(getattr(type(self), k, None)):
                raise AttributeError(f"AppState has no settable field {k!r}")
            old = getattr(self, k)
            if old == v:
                continue
            setattr(self, k, v)
            for cb in self._listeners.get(k, []):
                try:
                    await cb(v)
                except Exception:
                    logger.exception(
                        "AppState listener for field %r failed; "
                        "other listeners still fired",
                        k,
                    )
