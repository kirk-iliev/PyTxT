"""GET /api/v1/references — reference-library listing.

M3 ships only the listing endpoint. Multipart upload (POST /references),
download-by-name (GET /references/{name}), and the lazy /result/ref/raw are
M4. The bulk file-transfer surface lives in REST (not PVs) per CLAUDE.md §3.
"""
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from pytxt.api.schemas.reference import ReferenceLibraryEntry, ReferenceLibraryList

router = APIRouter(prefix="/api/v1", tags=["references"])


@router.get("/references", response_model=ReferenceLibraryList)
async def list_references(request: Request) -> ReferenceLibraryList:
    """List the .mat files in the reference library, newest first.

    Returns 503 when the library dir is not configured (e.g. an app built
    without ``reference_dir``).
    """
    reference_dir = getattr(request.app.state, "reference_dir", None)
    if reference_dir is None:
        raise HTTPException(503, "Reference library not configured")

    entries = []
    for p in sorted(
        Path(reference_dir).glob("*.mat"),
        key=lambda q: q.stat().st_mtime,
        reverse=True,
    ):
        st = p.stat()
        entries.append(
            ReferenceLibraryEntry(
                name=p.name,
                size_bytes=st.st_size,
                modified_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
            )
        )
    return ReferenceLibraryList(references=entries)
