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

logger = logging.getLogger(__name__)

ListenerFn = Callable[[Any], Awaitable[None]]


@dataclass
class AppState:
    # Published fields (mirrored as PVs by the IOC; surfaced via REST/WS)
    heartbeat: int = 0
    last_ping_at: Optional[str] = None  # ISO-8601 string
    ping_count: int = 0
    version: str = ""
    started_at: float = 0.0
    # Bound to HEALTH:UPTIME_S PV. Set every heartbeat tick by the
    # composition's heartbeat_loop. The `uptime_s` property below is
    # the canonical computed value used by /health and /state — these
    # two coexist because IOC binding requires a writable field.
    uptime_s_pushed: float = 0.0

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
        """
        for k, v in changes.items():
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
