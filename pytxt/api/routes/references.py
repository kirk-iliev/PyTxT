"""``/api/v1/references`` — reference-library REST surface.

The bulk file-transfer half of the reference workflow (CLAUDE.md §3 — files,
not PVs):

- ``GET  /references``         list the library (M3)
- ``POST /references``         multipart upload of a new ``.mat`` (M4)
- ``GET  /references/{name}``  download a library ``.mat`` (M4)

Upload is the one reference action with no CA-parity path — a file's bytes
can't be a PV (the acknowledged design §15 asymmetry). Loading a reference
*by name* from the library keeps full CA parity via ``CMD:LOAD_REF``.
"""
import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from pytxt.api.schemas.reference import ReferenceLibraryEntry, ReferenceLibraryList
from pytxt.domain.reference import ReferenceLoadError, load_reference_mat
from pytxt.handlers.reference import InvalidReferenceNameError, _resolve_in_library

router = APIRouter(prefix="/api/v1", tags=["references"])

_UPLOAD_CHUNK = 1 << 20  # 1 MiB stream chunk


def _require_reference_dir(request: Request) -> Path:
    """Return the configured library dir, or 503 if the app was built without one."""
    reference_dir = getattr(request.app.state, "reference_dir", None)
    if reference_dir is None:
        raise HTTPException(503, "Reference library not configured")
    return reference_dir


@router.get("/references", response_model=ReferenceLibraryList)
async def list_references(request: Request) -> ReferenceLibraryList:
    """List the .mat files in the reference library, newest first.

    Returns 503 when the library dir is not configured (e.g. an app built
    without ``reference_dir``).
    """
    reference_dir = _require_reference_dir(request)

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


@router.post("/references", status_code=201, response_model=ReferenceLibraryEntry)
async def upload_reference(
    request: Request, file: UploadFile = File(...)
) -> ReferenceLibraryEntry:
    """Upload a new reference ``.mat`` into the library (multipart form).

    The uploaded filename is validated by the same path-safety rules as
    ``CMD:LOAD_REF`` (bare ``*.mat`` basename, no separators / traversal).
    Bytes stream to disk with a running byte cap, then the written file is
    parse-validated via ``load_reference_mat`` — a bad upload is deleted, not
    left as junk in the library.

    Returns:
        201: ``ReferenceLibraryEntry`` for the stored file.
        409: a file of that name already exists (no overwrite).
        413: upload exceeds ``settings.max_upload_bytes``.
        422: invalid basename, or the bytes are not a valid reference ``.mat``.
    """
    reference_dir = _require_reference_dir(request)
    settings = getattr(request.app.state, "settings", None)
    cap = getattr(settings, "max_upload_bytes", 200 * 1024 * 1024)

    try:
        path = _resolve_in_library(reference_dir, file.filename or "")
    except InvalidReferenceNameError as e:
        raise HTTPException(422, str(e))
    if path.exists():
        raise HTTPException(409, f"Reference already exists: {path.name}")

    written = 0
    try:
        with open(path, "wb") as fh:
            while chunk := await file.read(_UPLOAD_CHUNK):
                written += len(chunk)
                if written > cap:
                    raise HTTPException(413, f"Upload exceeds {cap} bytes")
                fh.write(chunk)
        # Parse-validate the freshly-written file (blocking scipy → thread).
        await asyncio.to_thread(load_reference_mat, path)
    except ReferenceLoadError as e:
        path.unlink(missing_ok=True)
        raise HTTPException(422, f"Not a valid reference .mat: {e}")
    except BaseException:
        # 413, validation crashes, client disconnect — never leave a partial
        # or unvalidated file in the library.
        path.unlink(missing_ok=True)
        raise

    st = path.stat()
    return ReferenceLibraryEntry(
        name=path.name,
        size_bytes=st.st_size,
        modified_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
    )


@router.get("/references/{name}")
async def download_reference(request: Request, name: str) -> FileResponse:
    """Download a library reference ``.mat`` as ``application/octet-stream``.

    Returns:
        200: the file bytes.
        404: no file of that (valid) name in the library.
        422: invalid basename.
    """
    reference_dir = _require_reference_dir(request)
    try:
        path = _resolve_in_library(reference_dir, name)
    except InvalidReferenceNameError as e:
        raise HTTPException(422, str(e))
    if not path.exists():
        raise HTTPException(404, f"Reference not found: {name}")
    return FileResponse(
        path, media_type="application/octet-stream", filename=path.name
    )
