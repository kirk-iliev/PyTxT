"""Reference command handlers — the canonical functions both the CA
putters and the REST routes call. Parity by construction (CLAUDE.md §1).

M2 covers the file-free pair (PROMOTE/CLEAR). LOAD/SAVE land in M3.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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


class InvalidReferenceNameError(Exception):
    """Reference name is not a safe bare ``.mat`` basename within the library.

    Raised by ``_resolve_in_library`` for empty names, path separators,
    ``.``/``..``, a missing ``.mat`` extension, or any name that resolves
    outside the library dir. CA putter re-raises → alarm; REST → HTTP 422.
    """


class ReferenceNotFoundError(Exception):
    """LOAD target does not exist in the library. CA → alarm; REST → HTTP 404."""


class ReferenceExistsError(Exception):
    """SAVE target already exists in the library (no overwrite).

    CA putter re-raises → alarm; REST → HTTP 409.
    """


def _resolve_in_library(reference_dir: Path, name: str) -> Path:
    """Resolve ``name`` to an absolute path inside ``reference_dir``, safely.

    Rejects empty names, path separators, ``.``/``..``, and names without a
    ``.mat`` extension, then defends against ``../`` and symlink escapes via
    ``Path.is_relative_to`` (3.9+). Raises *only* ``InvalidReferenceNameError``;
    existence (LOAD) and collision (SAVE) checks live in the handlers.
    """
    if not name:
        raise InvalidReferenceNameError("Reference name must not be empty.")
    if "/" in name or "\\" in name or name in (".", ".."):
        raise InvalidReferenceNameError(
            f"Reference name must be a bare basename: {name!r}"
        )
    if not name.endswith(".mat"):
        raise InvalidReferenceNameError(
            f"Reference name must end in '.mat': {name!r}"
        )
    candidate = reference_dir / name
    resolved = candidate.resolve()
    base = reference_dir.resolve()
    if not resolved.is_relative_to(base):  # 3.9+; defends ../ and symlink escapes
        raise InvalidReferenceNameError(
            f"Reference path escapes the library: {name!r}"
        )
    return resolved


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
