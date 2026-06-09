"""Deterministic in-memory injection trigger for e2e and demo use.

Mirrors the `InjectionTrigger` interface but holds the TimInjReq waveform and
fine-delay in memory instead of writing EPICS. Selected alongside the synthetic
BPM reader (``PYTXT_USE_SYNTHETIC_READER=1``) so the active injection path
(``CMD:INJECT_ONESHOT``, the Injection panel) is exercisable without a ring.

`bucket:control:cmd` reads 0 (top-off not active) so safe shots fire; the
gun-fire guard (inhibit=0 needs allow_gun_fire) is handler-level and works
regardless. Never used in production.
"""
from __future__ import annotations


class SyntheticInjectionTrigger:
    """No-CA injection trigger with in-memory request state."""

    def __init__(self) -> None:
        # [bucket, gunBunches, mode, inhibit, 0, 0, seqNum]
        self._tim: list[int] = [0, 0, 0, 0, 0, 0, 0]
        self._fine_delay: int = 0
        # 0 = bucket loading / top-off NOT active → shots allowed.
        self.bucket_control: int = 0

    async def start(self) -> None:  # protocol no-op
        return None

    async def stop(self) -> None:  # protocol no-op
        return None

    async def read_bucket_control(self) -> int:
        return self.bucket_control

    async def read_tim_inj_req(self) -> list[int]:
        return list(self._tim)

    async def read_seq_busy(self) -> int:
        return 0

    async def write_tim_inj_req(self, req: list[int]) -> None:
        self._tim = list(req)

    async def write_fine_delay(self, counts: int) -> None:
        self._fine_delay = int(counts)

    async def sync_seq_busy(self, timeout_s: float = 5.0, poll_s: float = 0.01) -> None:
        # A real seqBusy 1->0 cycle completes instantly here.
        return None
