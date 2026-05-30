"""Reference command handlers — the canonical functions both the CA
putters and the REST routes call. Parity by construction (CLAUDE.md §1).

M2 covers the file-free pair (PROMOTE/CLEAR). LOAD/SAVE land in M3.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from pytxt.api.schemas.reference import (
    ClearRefResponse,
    DiffSummary,
    LoadRefResponse,
    PromoteRefResponse,
    SaveRefResponse,
)
from pytxt.domain.first_turn_extract import extract_first_turn
from pytxt.domain.reference import (
    ReferenceLoadError,
    align_to_current,
    compute_diff,
    load_reference_mat,
    save_reference_mat,
    summarize_diff,
)
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


async def handle_load_ref(
    state: AppState,
    reference_dir: Path,
    name: str,
) -> LoadRefResponse:
    """Load a named reference from the library and arm its B − R0 diff.

    Resolves ``name`` safely inside ``reference_dir`` (→
    ``InvalidReferenceNameError``), requires the file to exist (→
    ``ReferenceNotFoundError``), parses it via the M1 domain loader through
    ``asyncio.to_thread`` (blocking scipy; → ``ReferenceLoadError`` on a bad
    ``.mat``), then soft-merges onto the current prefixes. If a successful
    acquire has happened, a diff against the live first-turn is computed and
    stored; otherwise ``last_diff`` is left unset (None). Zero BPM overlap is
    *not* an error — the ref loads with ``n_aligned=0`` and an all-NaN diff.

    SAVE-symmetric: LOAD mutates AppState (so the STATE:REF_* PVs confirm it).
    """
    path = _resolve_in_library(reference_dir, name)
    if not path.exists():
        raise ReferenceNotFoundError(name)

    ref = await asyncio.to_thread(load_reference_mat, path)
    aligned, n_aligned, n_unaligned = align_to_current(ref, state.bpm_prefixes)

    diff: DiffResult | None = None
    if state.last_acquire.ok_count > 0:
        live = _current_first_turn(state)
        dx, dy = compute_diff(live, aligned)
        diff = DiffResult(dx=dx, dy=dy, summary=summarize_diff(dx, dy))

    now = datetime.now(timezone.utc)
    await state.update(
        reference_loaded=True,
        reference_name=path.name,
        reference_loaded_at=now,
        reference_source=ReferenceSource.FILE,
        reference_first_turn=aligned,
        reference_file_path=path,
        reference_bpm_names=list(ref.bpm_names),
        last_diff=diff,
    )

    return LoadRefResponse(
        loaded=True,
        name=path.name,
        source=ReferenceSource.FILE,
        n_aligned=n_aligned,
        n_unaligned=n_unaligned,
    )


async def handle_save_ref(
    state: AppState,
    reference_dir: Path,
    name: str | None,
) -> SaveRefResponse:
    """Write the current live acquisition to a ``.mat`` in the library.

    Requires a prior successful acquire (→ ``NoLastAcquireError``). A None
    ``name`` defaults to the MATLAB-GUI timestamp pattern. The target is
    resolved safely (→ ``InvalidReferenceNameError``) and must not already
    exist (→ ``ReferenceExistsError`` — no overwrite). The blocking scipy
    writer runs via ``asyncio.to_thread``.

    SAVE does NOT mutate AppState (decision §3, spec §7.2): saving is not
    loading. Confirmation is the file appearing + GET /references listing it.
    """
    if state.last_acquire.ok_count == 0:
        raise NoLastAcquireError("No successful acquisition to save.")

    if name is None:
        name = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d_%H:%M:%S_reference_trajectory.mat"
        )

    path = _resolve_in_library(reference_dir, name)
    if path.exists():
        raise ReferenceExistsError(name)

    first_turn = _current_first_turn(state)
    await asyncio.to_thread(
        save_reference_mat,
        path,
        first_turn,
        state.last_acquire_raws,
        state.bpm_prefixes,
    )

    size = path.stat().st_size
    return SaveRefResponse(
        name=path.name,
        size_bytes=size,
        saved_at=datetime.now(timezone.utc),
    )
