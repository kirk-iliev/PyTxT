"""Integration: M4 — GET /api/v1/result/ref/raw reference-waveform drill-down.

Covers spec §10.3 ``test_result_ref_raw`` + ``test_legacy_mat_file_loads``:

- PyTxT-saved reference (extended schema → has waveforms): returns the BPM's
  full TBT arrays, re-parsed lazily from disk.
- no reference loaded → 404.
- missing ``bpm`` query param → 400.
- unknown BPM (not in the ref's set) → 404.
- MATLAB-only reference (the real legacy .mat, raws=None) → 404 with the
  explanatory detail.
- promoted reference (no file) → 404 with the explanatory detail.
"""
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from httpx import AsyncClient, ASGITransport

from pytxt.api.server import create_app
from pytxt.domain.types import RawBPM
from pytxt.state.app_state import AppState

_LEGACY_MAT = Path("legacy/TxT_GUI/2025-03-23_12:43:16_reference_trajectory.mat")
_NO_WF_DETAIL = "Reference has no full waveforms (loaded from MATLAB-only schema)"


def _fake_raw(prefix):
    sum_wf = np.full(100000, 1000, dtype=np.int32)
    sum_wf[1370:] = 200000
    return RawBPM(
        prefix=prefix,
        x_wf=np.full(100000, 80_000, dtype=np.int32),
        y_wf=np.full(100000, -40_000, dtype=np.int32),
        sum_wf=sum_wf,
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )


def _make_reader(prefixes):
    from unittest.mock import AsyncMock

    reader = AsyncMock()
    reader.read_all.return_value = {p: _fake_raw(p) for p in prefixes}
    return reader


def _app(tmp_path, prefixes):
    state = AppState(version="m4-test", bpm_prefixes=prefixes)
    app = create_app(state=state, reference_dir=tmp_path)
    app.state.bpm_reader = _make_reader(prefixes)
    return app


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_result_ref_raw_pytxt_ref(tmp_path):
    """Acquire → save (PyTxT extended schema) → load → drill into a BPM's TBT."""
    prefixes = ["SR01C:BPM1", "SR02C:BPM1"]
    app = _app(tmp_path, prefixes)
    async with _client(app) as ac:
        assert (await ac.post("/api/v1/cmd/acquire", json={})).status_code == 200
        assert (await ac.post("/api/v1/cmd/save_ref", json={"name": "wf.mat"})).status_code == 200
        assert (await ac.post("/api/v1/cmd/load_ref", json={"name": "wf.mat"})).status_code == 200

        r = await ac.get("/api/v1/result/ref/raw", params={"bpm": "SR01C:BPM1"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["bpm_prefix"] == "SR01C:BPM1"
        assert len(body["x_nm"]) == 100000
        assert len(body["y_nm"]) == 100000
        assert len(body["sum_au"]) == 100000


@pytest.mark.asyncio
async def test_result_ref_raw_no_ref(tmp_path):
    app = _app(tmp_path, ["SR01C:BPM1"])
    async with _client(app) as ac:
        r = await ac.get("/api/v1/result/ref/raw", params={"bpm": "SR01C:BPM1"})
        assert r.status_code == 404
        assert "No reference loaded" in r.json()["detail"]


@pytest.mark.asyncio
async def test_result_ref_raw_missing_bpm_param(tmp_path):
    app = _app(tmp_path, ["SR01C:BPM1"])
    async with _client(app) as ac:
        r = await ac.get("/api/v1/result/ref/raw")
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_result_ref_raw_unknown_bpm(tmp_path):
    prefixes = ["SR01C:BPM1", "SR02C:BPM1"]
    app = _app(tmp_path, prefixes)
    async with _client(app) as ac:
        assert (await ac.post("/api/v1/cmd/acquire", json={})).status_code == 200
        assert (await ac.post("/api/v1/cmd/save_ref", json={"name": "wf.mat"})).status_code == 200
        assert (await ac.post("/api/v1/cmd/load_ref", json={"name": "wf.mat"})).status_code == 200

        r = await ac.get("/api/v1/result/ref/raw", params={"bpm": "SR99X:BPM9"})
        assert r.status_code == 404
        assert "not in reference" in r.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.skipif(not _LEGACY_MAT.exists(), reason="legacy MATLAB .mat fixture absent")
async def test_result_ref_raw_matlab_only(tmp_path):
    """The real legacy GUI .mat has no waveform vars → 404 explanatory detail.

    Doubles as test_legacy_mat_file_loads: the file parses + LOADs through the
    full REST stack (n_bpms=104, first name SR01C:BPM1)."""
    # Align state prefixes to the legacy BPM set so the load fully aligns.
    prefixes = [f"SR{s:02d}C:BPM1" for s in range(1, 13)]
    app = _app(tmp_path, prefixes)
    shutil.copy(_LEGACY_MAT, tmp_path / "legacy.mat")

    async with _client(app) as ac:
        load = await ac.post("/api/v1/cmd/load_ref", json={"name": "legacy.mat"})
        assert load.status_code == 200, load.text
        assert load.json()["loaded"] is True

        r = await ac.get("/api/v1/result/ref/raw", params={"bpm": "SR01C:BPM1"})
        assert r.status_code == 404
        assert r.json()["detail"] == _NO_WF_DETAIL


@pytest.mark.asyncio
async def test_result_ref_raw_promoted(tmp_path):
    """A promoted reference has no file → 404 explanatory detail."""
    prefixes = ["SR01C:BPM1", "SR02C:BPM1"]
    app = _app(tmp_path, prefixes)
    async with _client(app) as ac:
        assert (await ac.post("/api/v1/cmd/acquire", json={})).status_code == 200
        assert (await ac.post("/api/v1/cmd/promote_ref", json={})).status_code == 200

        r = await ac.get("/api/v1/result/ref/raw", params={"bpm": "SR01C:BPM1"})
        assert r.status_code == 404
        assert r.json()["detail"] == _NO_WF_DETAIL
