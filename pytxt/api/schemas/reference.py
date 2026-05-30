"""Phase-3 REST schemas for the reference-trajectory surface.

Re-uses the domain `ReferenceSource` enum (lives in `pytxt/domain/types.py`,
not here, to avoid a state → api layering inversion — AppState references it).
M2 covers the file-free PROMOTE/CLEAR pair; LOAD/SAVE land in M3.
"""
from datetime import datetime

from pydantic import BaseModel, Field

from pytxt.domain.types import ReferenceSource  # re-use the domain enum

__all__ = [
    "ReferenceSource",
    "ReferenceStatus",
    "DiffSummary",
    "PromoteRefResponse",
    "ClearRefResponse",
    "LoadRefRequest",
    "SaveRefRequest",
    "LoadRefResponse",
    "SaveRefResponse",
    "ReferenceLibraryEntry",
    "ReferenceLibraryList",
]


class ReferenceStatus(BaseModel):
    """Snapshot of the currently-loaded reference. Mirrors STATE:REF_* PVs.
    Null in /state when nothing is loaded."""
    loaded: bool = Field(description="True when a reference is loaded")
    name: str = Field(description='Reference name; "<promoted>" under PROMOTE_REF')
    loaded_at: datetime | None = Field(
        default=None, description="UTC load time; null when nothing loaded"
    )
    source: ReferenceSource = Field(description="Provenance: PROMOTED | FILE | NONE")
    n_aligned: int = Field(description="BPMs the reference aligned onto current prefixes")
    n_unaligned: int = Field(description="Current prefixes with no reference value")


class DiffSummary(BaseModel):
    """Cheap NaN-aware summary of the latest B − R0 diff. Mirrors the
    domain `DiffSummary` dataclass field-for-field."""
    x_rms_mm: float = Field(description="RMS of the X diff (mm), NaN-ignoring")
    y_rms_mm: float = Field(description="RMS of the Y diff (mm), NaN-ignoring")
    x_max_abs_mm: float = Field(description="Max |X diff| (mm)")
    y_max_abs_mm: float = Field(description="Max |Y diff| (mm)")
    n_valid: int = Field(description="BPMs with a non-NaN diff on both X and Y")


class PromoteRefResponse(BaseModel):
    """Response body for POST /api/v1/cmd/promote_ref."""
    loaded: bool = Field(description="Always True on success")
    name: str = Field(description='Reference name; "<promoted>" under PROMOTE_REF')
    source: ReferenceSource = Field(description="Always PROMOTED for promote")
    n_aligned: int = Field(description="BPMs the promoted reference covers")
    n_unaligned: int = Field(description="Current prefixes with no reference value")
    summary: DiffSummary = Field(description="Self-diff summary (zeros, NaN where live NaN)")


class ClearRefResponse(BaseModel):
    """Response body for POST /api/v1/cmd/clear_ref. Idempotent."""
    loaded: bool = Field(default=False, description="Always False after clear")


class LoadRefRequest(BaseModel):
    """Request body for POST /api/v1/cmd/load_ref."""
    name: str = Field(
        min_length=1,
        description="Reference filename (basename, incl. .mat).",
    )


class SaveRefRequest(BaseModel):
    """Request body for POST /api/v1/cmd/save_ref."""
    name: str | None = Field(
        default=None,
        description="Basename incl. .mat; omit for timestamp default.",
    )


class LoadRefResponse(BaseModel):
    """Response body for POST /api/v1/cmd/load_ref."""
    loaded: bool = Field(description="Always True on success")
    name: str = Field(description="Loaded reference basename")
    source: ReferenceSource = Field(description="Always FILE for load")
    n_aligned: int = Field(description="BPMs the reference aligned onto current prefixes")
    n_unaligned: int = Field(description="Current prefixes with no reference value")


class SaveRefResponse(BaseModel):
    """Response body for POST /api/v1/cmd/save_ref."""
    name: str = Field(description="Saved reference basename")
    size_bytes: int = Field(description="Size of the written .mat file in bytes")
    saved_at: datetime = Field(description="UTC time the reference was written")


class ReferenceLibraryEntry(BaseModel):
    """One .mat file in the reference library. Mirrors a directory entry."""
    name: str = Field(description="Reference basename (incl. .mat)")
    size_bytes: int = Field(description="File size in bytes")
    modified_at: datetime = Field(description="UTC mtime of the file")


class ReferenceLibraryList(BaseModel):
    """Response body for GET /api/v1/references — newest first."""
    references: list[ReferenceLibraryEntry] = Field(
        description="Library .mat files, newest first"
    )
