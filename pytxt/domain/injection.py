"""Injection one-shot request math (Phase 4) — de-boxed from srinjectoneshot.m.

Pure functions: NO caproto/asyncio. The CA sequence (seqBusy sync, the
caputs, the top-off precondition) lives in the adapter/handler above. Here we
reproduce the two deterministic pieces of `srinjectoneshot`:

1. Building the 7-element `TimInjReq` request waveform (bump the sequence number,
   set bucket/bunches/mode/inhibit).
2. The extraction fine-delay, a pure function of the bucket number.

Element order of `TimInjReq` (DBF_LONG x7), confirmed live 2026-06-01:
    [bucket, gunBunches, mode, inhibit, IFGD(unused=0), EFGD(unused=0), seqNum]
"""
from __future__ import annotations

# Legacy: Req(7)=Req(7)+1; if Req(7)>20000, Req(7)=1
_SEQ_MAX = 20000
_REQ_LEN = 7

# Live record: B0215:EVR1-Out:UDC0:Delay-SP is DBF_LONG, clamps at 1023 (10 ps/count).
_FINE_DELAY_MAX_COUNTS = 1023


def fine_delay_counts(bucket: int) -> int:
    """Extraction-kicker fine delay (raw counts) for a bucket number.

    Ports the legacy `BR_KE_FineDelay = 100*8*rem(31.25*rem(21*BucketNumber,328),1)`.
    `rem(x, 328)` is the integer SR-bucket fold; `rem(.., 1)` is the fractional
    part; the result is an integer count in [0, ~800] (10 ps/count), well within
    the record's 0-1023 range. Clamped defensively to [0, 1023].
    """
    folded = (21 * bucket) % 328
    frac = (31.25 * folded) % 1.0
    counts = round(100 * 8 * frac)
    return max(0, min(_FINE_DELAY_MAX_COUNTS, counts))


def next_seq_num(current_seq: int) -> int:
    """Increment the TimInjReq sequence number, wrapping >20000 back to 1."""
    nxt = int(current_seq) + 1
    return 1 if nxt > _SEQ_MAX else nxt


def build_tim_inj_req(
    current_req: list[int],
    bucket: int,
    gun_bunches: int,
    mode: int,
    inhibit: int,
) -> list[int]:
    """Build the new 7-element TimInjReq waveform from the current one.

    Bumps the sequence number (element 7) and sets bucket/bunches/mode/inhibit
    (elements 1-4); elements 5,6 (unused IFGD/EFGD) are forced to 0. The current
    request is read live so we preserve the sequencer's counter and only step it.
    """
    if len(current_req) < _REQ_LEN:
        raise ValueError(
            f"TimInjReq must have {_REQ_LEN} elements, got {len(current_req)}"
        )
    seq = next_seq_num(current_req[6])
    return [int(bucket), int(gun_bunches), int(mode), int(inhibit), 0, 0, seq]
