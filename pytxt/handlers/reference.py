"""Reference command handlers — the canonical functions both the CA
putters and the REST routes call. Parity by construction (CLAUDE.md §1).

M2 covers the file-free pair (PROMOTE/CLEAR). LOAD/SAVE land in M3.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pytxt.api.schemas.reference import (
    ClearRefResponse,
    DiffSummary,
    PromoteRefResponse,
)
from pytxt.domain.first_turn_extract import extract_first_turn
from pytxt.domain.reference import compute_diff, summarize_diff
from pytxt.domain.types import DiffResult, ReferenceSource
from pytxt.state.app_state import AppState


class NoLastAcquireError(Exception):
    """Promote attempted with no successful acquisition to source from.

    Re-raised by the CA putter (→ alarm); mapped to HTTP 422 by the REST route.
    Mirrors how AcquisitionInFlightError is shared by the acquire putter/route.
    """


def _current_first_turn(state: AppState):
    """Re-derive the live first-turn arrays aligned to current prefixes.

    Mirrors server.py:_publish_last_acquire: last_acquire_raws holds only the
    successful BPMs, so reconstruct the full prefix-aligned dict (None for the
    failed/missing ones) before extracting. extract_first_turn keys off dict
    order, so iterating bpm_prefixes guarantees index alignment.
    """
    aligned = {p: state.last_acquire_raws.get(p) for p in state.bpm_prefixes}
    return extract_first_turn(aligned)


async def handle_promote_ref(state: AppState) -> PromoteRefResponse:
    """Promote the current live acquisition to an in-memory reference.

    The promoted R0 is the recomputed live first-turn (already aligned to
    current prefixes, so align_to_current is a no-op). The accompanying
    last_diff is the self-diff (zeros, NaN where the live value was NaN), so
    the diff PVs read sane until the next real acquire recomputes them.
    """
    if state.last_acquire.ok_count == 0:
        raise NoLastAcquireError("No successful acquisition to promote.")

    first_turn = _current_first_turn(state)
    dx, dy = compute_diff(first_turn, first_turn)  # self-diff → zeros
    summary = summarize_diff(dx, dy)
    diff = DiffResult(dx=dx, dy=dy, summary=summary)
    now = datetime.now(timezone.utc)

    await state.update(
        reference_loaded=True,
        reference_name="<promoted>",
        reference_loaded_at=now,
        reference_source=ReferenceSource.PROMOTED,
        reference_first_turn=first_turn,
        reference_file_path=None,  # file backing is M3
        reference_bpm_names=list(state.bpm_prefixes),
        last_diff=diff,
    )

    return PromoteRefResponse(
        loaded=True,
        name="<promoted>",
        source=ReferenceSource.PROMOTED,
        n_aligned=summary.n_valid,
        n_unaligned=len(state.bpm_prefixes) - summary.n_valid,
        summary=DiffSummary(**summary.__dict__),
    )


async def handle_clear_ref(state: AppState) -> ClearRefResponse:
    """Unload the reference and reset every reference/diff field to default.

    Idempotent: succeeds even when nothing was loaded.
    """
    await state.update(
        reference_loaded=False,
        reference_name="",
        reference_loaded_at=None,
        reference_source=ReferenceSource.NONE,
        reference_first_turn=None,
        reference_file_path=None,
        reference_bpm_names=None,
        last_diff=None,
    )
    return ClearRefResponse(loaded=False)
