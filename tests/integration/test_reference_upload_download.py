"""Integration: M4 — multipart upload + download of reference .mat files (REST).

Exercises the bulk file-transfer surface added in M4 (spec §10.3):

- upload a valid .mat → 201 + entry → GET /references lists it → it LOADs.
- download the uploaded file → identical bytes round-trip.
- collision (upload same name twice) → 409.
- bad .mat bytes → 422 AND the partial write is deleted (no junk in library).
- bad basename (separator / traversal / no .mat) → 422.
- download missing / bad name → 404 / 422.
- oversize upload → 413 (via a small per-app max_upload_bytes).

Upload is the one reference action with no CA parity — a file's bytes can't be
a PV (design §15). These tests cover only the REST arm by design.
"""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport

from pytxt.api.server import create_app
from pytxt.config.settings import Settings
from pytxt.domain.reference import save_reference_mat
from pytxt.domain.types import FirstTurnResult, RawBPM
from pytxt.state.app_state import AppState


def _synth_first_turn(n: int) -> FirstTurnResult:
    return FirstTurnResult(
        x_first_turn=np.array([0.01 * i for i in range(n)], dtype=np.float64),
        y_first_turn=np.array([-0.02 * i for i in range(n)], dtype=np.float64),
        sum_first_turn=np.full(n, 1234.0, dtype=np.float64),
        injection_turn=np.full(n, 1370, dtype=np.int32),
        failed_bpm_names=[],
    )


def _synth_raws(prefixes: list[str]) -> dict[str, RawBPM]:
    now = datetime.now(timezone.utc)
    return {
        p: RawBPM(
            prefix=p,
            x_wf=np.full(100000, i + 1, dtype=np.int32),
            y_wf=np.full(100000, -(i + 1), dtype=np.int32),
            sum_wf=np.full(100000, 1000 * (i + 1), dtype=np.int32),
            armed=0,
            read_timestamp=now,
        )
        for i, p in enumerate(prefixes)
    }


def _synth_mat_bytes(tmp_path: Path, prefixes: list[str]) -> bytes:
    """Build a valid reference .mat off to the side and return its raw bytes."""
    src = tmp_path / "_src.mat"
    save_reference_mat(src, _synth_first_turn(len(prefixes)), _synth_raws(prefixes), prefixes)
    data = src.read_bytes()
    src.unlink()
    return data


def _make_app(tmp_path: Path, *, max_upload_bytes: int | None = None):
    prefixes = ["SR01C:BPM1", "SR02C:BPM1"]
    state = AppState(version="m4-test", bpm_prefixes=prefixes)
    settings = None
    if max_upload_bytes is not None:
        settings = Settings(max_upload_bytes=max_upload_bytes)
    return create_app(state=state, settings=settings, reference_dir=tmp_path)


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_upload_round_trip(tmp_path):
    """Upload a valid .mat → 201 → it's listed → it LOADs by name."""
    lib = tmp_path / "lib"
    lib.mkdir()
    data = _synth_mat_bytes(tmp_path, ["SR01C:BPM1", "SR02C:BPM1"])
    app = _make_app(lib)

    async with _client(app) as ac:
        up = await ac.post(
            "/api/v1/references",
            files={"file": ("foo.mat", data, "application/octet-stream")},
        )
        assert up.status_code == 201, up.text
        entry = up.json()
        assert entry["name"] == "foo.mat"
        assert entry["size_bytes"] == len(data)
        assert (lib / "foo.mat").exists()

        listing = await ac.get("/api/v1/references")
        assert "foo.mat" in [e["name"] for e in listing.json()["references"]]

        load = await ac.post("/api/v1/cmd/load_ref", json={"name": "foo.mat"})
        assert load.status_code == 200, load.text
        assert load.json()["loaded"] is True


@pytest.mark.asyncio
async def test_download_round_trip(tmp_path):
    """Bytes uploaded come back identical from GET /references/{name}."""
    lib = tmp_path / "lib"
    lib.mkdir()
    data = _synth_mat_bytes(tmp_path, ["SR01C:BPM1"])
    app = _make_app(lib)

    async with _client(app) as ac:
        up = await ac.post(
            "/api/v1/references",
            files={"file": ("dl.mat", data, "application/octet-stream")},
        )
        assert up.status_code == 201, up.text

        dn = await ac.get("/api/v1/references/dl.mat")
        assert dn.status_code == 200
        assert dn.headers["content-type"] == "application/octet-stream"
        assert dn.content == data


@pytest.mark.asyncio
async def test_upload_collision(tmp_path):
    """Uploading the same name twice → 409 (no overwrite)."""
    lib = tmp_path / "lib"
    lib.mkdir()
    data = _synth_mat_bytes(tmp_path, ["SR01C:BPM1"])
    app = _make_app(lib)

    async with _client(app) as ac:
        first = await ac.post(
            "/api/v1/references",
            files={"file": ("dup.mat", data, "application/octet-stream")},
        )
        assert first.status_code == 201
        second = await ac.post(
            "/api/v1/references",
            files={"file": ("dup.mat", data, "application/octet-stream")},
        )
        assert second.status_code == 409


@pytest.mark.asyncio
async def test_upload_bad_mat_is_deleted(tmp_path):
    """Junk bytes → 422 AND the partial write is removed from the library."""
    lib = tmp_path / "lib"
    lib.mkdir()
    app = _make_app(lib)

    async with _client(app) as ac:
        up = await ac.post(
            "/api/v1/references",
            files={"file": ("bad.mat", b"not a real mat file", "application/octet-stream")},
        )
        assert up.status_code == 422, up.text
    assert not (lib / "bad.mat").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_name", ["noext", "a/b.mat", "../escape.mat", "/etc/passwd"])
async def test_upload_bad_name(tmp_path, bad_name):
    """Unsafe basenames are rejected with 422 by the path-safety helper."""
    lib = tmp_path / "lib"
    lib.mkdir()
    data = _synth_mat_bytes(tmp_path, ["SR01C:BPM1"])
    app = _make_app(lib)

    async with _client(app) as ac:
        up = await ac.post(
            "/api/v1/references",
            files={"file": (bad_name, data, "application/octet-stream")},
        )
        assert up.status_code == 422, up.text
    # No file leaked into the library under any guise.
    assert list(lib.glob("*.mat")) == []


@pytest.mark.asyncio
async def test_upload_empty_filename(tmp_path):
    """An empty filename is a degenerate multipart part (no Content-Disposition
    filename) — Starlette/python-multipart treats it as a form field and the
    body trips the parser's field-size cap before our handler runs. Either way
    it's a 4xx rejection and nothing is written to the library."""
    lib = tmp_path / "lib"
    lib.mkdir()
    data = _synth_mat_bytes(tmp_path, ["SR01C:BPM1"])
    app = _make_app(lib)

    async with _client(app) as ac:
        up = await ac.post(
            "/api/v1/references",
            files={"file": ("", data, "application/octet-stream")},
        )
        assert up.status_code in (400, 422), up.text
    assert list(lib.glob("*.mat")) == []


@pytest.mark.asyncio
async def test_download_not_found(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    app = _make_app(lib)
    async with _client(app) as ac:
        dn = await ac.get("/api/v1/references/missing.mat")
        assert dn.status_code == 404


@pytest.mark.asyncio
async def test_download_bad_name(tmp_path):
    lib = tmp_path / "lib"
    lib.mkdir()
    app = _make_app(lib)
    async with _client(app) as ac:
        # 'noext' fails the .mat basename rule → 422 (not 404).
        dn = await ac.get("/api/v1/references/noext")
        assert dn.status_code == 422


@pytest.mark.asyncio
async def test_upload_over_cap(tmp_path):
    """Upload larger than max_upload_bytes → 413, partial write deleted."""
    lib = tmp_path / "lib"
    lib.mkdir()
    data = _synth_mat_bytes(tmp_path, ["SR01C:BPM1", "SR02C:BPM1"])
    # Cap below the synthetic file size so the streamed write overflows.
    app = _make_app(lib, max_upload_bytes=max(1, len(data) // 2))

    async with _client(app) as ac:
        up = await ac.post(
            "/api/v1/references",
            files={"file": ("big.mat", data, "application/octet-stream")},
        )
        assert up.status_code == 413, up.text
    assert not (lib / "big.mat").exists()
