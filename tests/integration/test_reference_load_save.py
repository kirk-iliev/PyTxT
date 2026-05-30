"""Integration: M3 — LOAD_REF / SAVE_REF full file-backed pipeline (CA + REST).

Exercises the reference *library* end-to-end through the live IOC and the REST
surface (spec §10.3 M3 subset). Both arms inject a per-test ``tmp_path``
reference_dir into ``PyTxTIOC(..., reference_dir=...)`` / ``create_app(...,
reference_dir=...)``.

- save via CA → file appears in the library; load it → STATE:REF_* PVs confirm
  source="file"/name; a subsequent acquire publishes finite diff arrays.
- save via REST → 200 + file; GET /references lists it; load → /state shows
  reference.source="file".
- save on a fresh state → CA alarm (write timeout) / REST 422.
- save the same name twice → CA alarm / REST 409.
- load a missing name → CA alarm / REST 404.
- save with no name → timestamp-pattern file appears + is listed.

Mirrors test_reference_promote_clear.py for the CA / REST harness shape.
"""
import asyncio
import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import numpy as np
import pytest
from caproto import CaprotoTimeoutError
from caproto.asyncio.client import Context as ClientContext
from httpx import AsyncClient, ASGITransport

from pytxt.domain.types import RawBPM
from pytxt.ioc.server import PyTxTIOC
from pytxt.state.app_state import AppState


def _fake_raw(prefix):
    sum_wf = np.full(100000, 1000, dtype=np.int32)
    sum_wf[1370:] = 200000
    return RawBPM(
        prefix=prefix,
        x_wf=np.full(100000, 80_000, dtype=np.int32),
        y_wf=np.zeros(100000, dtype=np.int32),
        sum_wf=sum_wf,
        armed=0,
        read_timestamp=datetime.now(timezone.utc),
    )


def _make_reader(prefixes):
    reader = AsyncMock()
    reader.read_all.return_value = {p: _fake_raw(p) for p in prefixes}
    return reader


async def _disconnect_quietly(client):
    if client is None:
        return
    try:
        await asyncio.wait_for(client.disconnect(), timeout=2.0)
    except (asyncio.TimeoutError, Exception):
        pass


# Timestamp default pattern (handle_save_ref): YYYY-MM-DD_HH:MM:SS_reference_trajectory.mat
_TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}:\d{2}:\d{2}_reference_trajectory\.mat$")


@pytest.mark.asyncio
async def test_save_then_load_via_ca(test_pv_prefix, tmp_path):
    """acquire → caput CMD:SAVE_REF foo.mat → file exists → caput CMD:LOAD_REF
    foo.mat → REF_* PVs confirm source="file"; a 2nd acquire → finite diff."""
    prefixes = ["FAKE:BPM1", "FAKE:BPM2"]
    state = AppState(version="m3-test", bpm_prefixes=prefixes)
    reader = _make_reader(prefixes)

    ioc = PyTxTIOC(
        prefix=test_pv_prefix,
        host="127.0.0.1", port=0, repeater_port=0,
        state=state, reader=reader, reference_dir=tmp_path,
    )
    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    client: ClientContext | None = None
    try:
        client = ClientContext()
        acquire_pv, save_pv, load_pv = await client.get_pvs(
            test_pv_prefix + "CMD:ACQUIRE",
            test_pv_prefix + "CMD:SAVE_REF",
            test_pv_prefix + "CMD:LOAD_REF",
        )

        await acquire_pv.write(1)
        await asyncio.sleep(0.2)

        await save_pv.write("foo.mat")
        await asyncio.sleep(0.2)
        assert (tmp_path / "foo.mat").exists()

        await load_pv.write("foo.mat")
        await asyncio.sleep(0.2)

        loaded_pv, source_pv, name_pv = await client.get_pvs(
            test_pv_prefix + "STATE:REF_LOADED",
            test_pv_prefix + "STATE:REF_SOURCE",
            test_pv_prefix + "STATE:REF_NAME",
        )
        loaded = await loaded_pv.read()
        source = await source_pv.read()
        name = await name_pv.read()

        assert int(loaded.data[0]) == 1
        assert source.data[0] in (b"file", "file")
        assert name.data[0] in (b"foo.mat", "foo.mat")

        # A subsequent acquire republishes diff arrays — FINITE for aligned.
        await acquire_pv.write(1)
        await asyncio.sleep(0.2)

        xdiff_pv, ydiff_pv = await client.get_pvs(
            test_pv_prefix + "RESULT:BPM:X_DIFF_FIRST_TURN",
            test_pv_prefix + "RESULT:BPM:Y_DIFF_FIRST_TURN",
        )
        xdiff = await xdiff_pv.read()
        ydiff = await ydiff_pv.read()

        n = len(prefixes)
        x_aligned = np.asarray(xdiff.data[:n], dtype=float)
        y_aligned = np.asarray(ydiff.data[:n], dtype=float)
        assert np.all(np.isfinite(x_aligned)), x_aligned
        assert np.all(np.isfinite(y_aligned)), y_aligned
        # Self-diff of unchanged synthetic data → zeros.
        assert np.allclose(x_aligned, 0.0)
        assert np.allclose(y_aligned, 0.0)
    finally:
        await _disconnect_quietly(client)
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


@pytest.mark.asyncio
async def test_save_then_load_via_rest(tmp_path):
    """POST /cmd/acquire → /cmd/save_ref {name} (200 + file) → GET /references
    lists it → /cmd/load_ref {name} → /state shows reference.source="file"."""
    from pytxt.api.server import create_app

    prefixes = ["A", "B"]
    state = AppState(version="m3-test", bpm_prefixes=prefixes)
    reader = _make_reader(prefixes)

    app = create_app(state=state, reference_dir=tmp_path)
    app.state.bpm_reader = reader

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        assert (await ac.post("/api/v1/cmd/acquire", json={})).status_code == 200

        rs = await ac.post("/api/v1/cmd/save_ref", json={"name": "foo.mat"})
        assert rs.status_code == 200, rs.text
        body = rs.json()
        assert body["name"] == "foo.mat"
        assert body["size_bytes"] > 0
        assert (tmp_path / "foo.mat").exists()

        rl = await ac.get("/api/v1/references")
        assert rl.status_code == 200
        names = [e["name"] for e in rl.json()["references"]]
        assert "foo.mat" in names

        rload = await ac.post("/api/v1/cmd/load_ref", json={"name": "foo.mat"})
        assert rload.status_code == 200, rload.text
        lbody = rload.json()
        assert lbody["loaded"] is True
        assert lbody["source"] == "file"
        assert lbody["name"] == "foo.mat"

        # A second acquire computes the real (zero) diff.
        assert (await ac.post("/api/v1/cmd/acquire", json={})).status_code == 200

        rstate = await ac.get("/api/v1/state")
        assert rstate.status_code == 200
        snap = rstate.json()

    assert snap["reference"] is not None
    assert snap["reference"]["source"] == "file"
    assert snap["reference"]["name"] == "foo.mat"
    assert snap["last_diff"] is not None


@pytest.mark.asyncio
async def test_save_no_acquire_via_ca(test_pv_prefix, tmp_path):
    """Save on a fresh state (no successful acquire) → CA alarm (write timeout).

    The putter re-raises NoLastAcquireError; caproto drops the write-ACK so the
    client times out — symmetric to REST's 422.
    """
    state = AppState(version="m3-test", bpm_prefixes=["FAKE:BPM1"])
    reader = AsyncMock()  # never read: save refuses before any acquire

    ioc = PyTxTIOC(
        prefix=test_pv_prefix,
        host="127.0.0.1", port=0, repeater_port=0,
        state=state, reader=reader, reference_dir=tmp_path,
    )
    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    client: ClientContext | None = None
    try:
        client = ClientContext()
        save_pv, = await client.get_pvs(test_pv_prefix + "CMD:SAVE_REF")
        with pytest.raises(CaprotoTimeoutError):
            await save_pv.write("foo.mat")

        # Nothing written.
        assert not (tmp_path / "foo.mat").exists()
    finally:
        await _disconnect_quietly(client)
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


@pytest.mark.asyncio
async def test_save_no_acquire_via_rest(tmp_path):
    """Save with no prior acquire → REST 422 (parity with CA alarm)."""
    from pytxt.api.server import create_app

    state = AppState(version="m3-test", bpm_prefixes=["A"])
    app = create_app(state=state, reference_dir=tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/save_ref", json={"name": "foo.mat"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_save_exists_via_ca(test_pv_prefix, tmp_path):
    """acquire → save foo.mat (ok) → save foo.mat again → CA alarm; file kept."""
    prefixes = ["FAKE:BPM1", "FAKE:BPM2"]
    state = AppState(version="m3-test", bpm_prefixes=prefixes)
    reader = _make_reader(prefixes)

    ioc = PyTxTIOC(
        prefix=test_pv_prefix,
        host="127.0.0.1", port=0, repeater_port=0,
        state=state, reader=reader, reference_dir=tmp_path,
    )
    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    client: ClientContext | None = None
    try:
        client = ClientContext()
        acquire_pv, save_pv = await client.get_pvs(
            test_pv_prefix + "CMD:ACQUIRE",
            test_pv_prefix + "CMD:SAVE_REF",
        )

        await acquire_pv.write(1)
        await asyncio.sleep(0.2)

        await save_pv.write("foo.mat")
        await asyncio.sleep(0.2)
        assert (tmp_path / "foo.mat").exists()

        with pytest.raises(CaprotoTimeoutError):
            await save_pv.write("foo.mat")  # collision → ReferenceExistsError → alarm
        assert (tmp_path / "foo.mat").exists()
    finally:
        await _disconnect_quietly(client)
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


@pytest.mark.asyncio
async def test_save_exists_via_rest(tmp_path):
    """Save foo.mat twice via REST → second → 409."""
    from pytxt.api.server import create_app

    prefixes = ["A", "B"]
    state = AppState(version="m3-test", bpm_prefixes=prefixes)
    reader = _make_reader(prefixes)

    app = create_app(state=state, reference_dir=tmp_path)
    app.state.bpm_reader = reader

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        assert (await ac.post("/api/v1/cmd/acquire", json={})).status_code == 200
        r1 = await ac.post("/api/v1/cmd/save_ref", json={"name": "foo.mat"})
        r2 = await ac.post("/api/v1/cmd/save_ref", json={"name": "foo.mat"})
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_load_not_found_via_ca(test_pv_prefix, tmp_path):
    """Load a name not present in the library → CA alarm; state unchanged."""
    state = AppState(version="m3-test", bpm_prefixes=["FAKE:BPM1"])
    reader = AsyncMock()

    ioc = PyTxTIOC(
        prefix=test_pv_prefix,
        host="127.0.0.1", port=0, repeater_port=0,
        state=state, reader=reader, reference_dir=tmp_path,
    )
    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    client: ClientContext | None = None
    try:
        client = ClientContext()
        load_pv, = await client.get_pvs(test_pv_prefix + "CMD:LOAD_REF")
        with pytest.raises(CaprotoTimeoutError):
            await load_pv.write("missing.mat")

        assert state.reference_loaded is False
    finally:
        await _disconnect_quietly(client)
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


@pytest.mark.asyncio
async def test_load_not_found_via_rest(tmp_path):
    """Load a missing name → REST 404 (parity with CA alarm)."""
    from pytxt.api.server import create_app

    state = AppState(version="m3-test", bpm_prefixes=["A"])
    app = create_app(state=state, reference_dir=tmp_path)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/load_ref", json={"name": "missing.mat"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_save_default_name_via_rest(tmp_path):
    """POST /cmd/save_ref {} → timestamp-named file appears + GET /references
    lists it."""
    from pytxt.api.server import create_app

    prefixes = ["A", "B"]
    state = AppState(version="m3-test", bpm_prefixes=prefixes)
    reader = _make_reader(prefixes)

    app = create_app(state=state, reference_dir=tmp_path)
    app.state.bpm_reader = reader

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        assert (await ac.post("/api/v1/cmd/acquire", json={})).status_code == 200

        rs = await ac.post("/api/v1/cmd/save_ref", json={})
        assert rs.status_code == 200, rs.text
        saved_name = rs.json()["name"]
        assert _TS_PATTERN.match(saved_name), saved_name
        assert (tmp_path / saved_name).exists()

        rl = await ac.get("/api/v1/references")
        assert rl.status_code == 200
        names = [e["name"] for e in rl.json()["references"]]
        assert saved_name in names
