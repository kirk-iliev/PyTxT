"""Integration: M2 — PROMOTE_REF / CLEAR_REF full pipeline (CA + REST).

Exercises the file-free reference pair end-to-end through the live IOC and
the REST surface, asserting the confirming STATE:REF_* PVs and the diff
waveform PVs (RESULT:BPM:{X,Y}_DIFF_FIRST_TURN) behave per spec §7.3/§7.5
and §10.3 (M2 subset):

- promote via CA → STATE:REF_LOADED=1, REF_SOURCE="promoted", REF_NAME="<promoted>";
  a subsequent acquire publishes finite diff arrays.
- promote via REST → /state surfaces reference.source="promoted" + last_diff.
- promote with no prior acquire → CA alarm (write times out) / REST 422.
- clear → STATE:REF_LOADED=0, diff PVs NaN-filled; idempotent.

The CA arm mirrors test_acquire_concurrent_ca.py (PyTxTIOC + AsyncMock reader
+ ClientContext); the reader is exercised for real because CMD:ACQUIRE's
putter calls handle_acquire(self._state, self._reader). The REST arm mirrors
test_state_endpoint.py.
"""
import asyncio
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


@pytest.mark.asyncio
async def test_promote_ref_via_ca(test_pv_prefix):
    """acquire → caput CMD:PROMOTE_REF → REF_* PVs confirm; a 2nd acquire
    publishes finite diff arrays (zeros for unchanged synthetic data)."""
    prefixes = ["FAKE:BPM1", "FAKE:BPM2"]
    state = AppState(version="m2-test", bpm_prefixes=prefixes)
    reader = _make_reader(prefixes)

    ioc = PyTxTIOC(
        prefix=test_pv_prefix,
        host="127.0.0.1", port=0, repeater_port=0,
        state=state, reader=reader,
    )
    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    client: ClientContext | None = None
    try:
        client = ClientContext()
        acquire_pv, promote_pv = await client.get_pvs(
            test_pv_prefix + "CMD:ACQUIRE",
            test_pv_prefix + "CMD:PROMOTE_REF",
        )

        # Acquire so there's a live first-turn to promote.
        await acquire_pv.write(1)
        await asyncio.sleep(0.2)

        # Promote the live acquisition.
        await promote_pv.write(1)
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
        assert source.data[0] == b"promoted" or source.data[0] == "promoted"
        assert name.data[0] == b"<promoted>" or name.data[0] == "<promoted>"

        # A subsequent acquire republishes diff arrays. The synthetic data is
        # identical run-to-run, so the diff is zeros — crucially, FINITE
        # (not NaN) for aligned indices.
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
async def test_promote_ref_via_rest():
    """POST /cmd/acquire → /cmd/promote_ref → GET /state shows promoted ref
    and a non-null last_diff summary."""
    from pytxt.api.server import create_app

    prefixes = ["A", "B"]
    state = AppState(version="m2-test", bpm_prefixes=prefixes)
    reader = _make_reader(prefixes)

    app = create_app(state=state)
    app.state.bpm_reader = reader

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        assert (await ac.post("/api/v1/cmd/acquire", json={})).status_code == 200
        rp = await ac.post("/api/v1/cmd/promote_ref", json={})
        assert rp.status_code == 200, rp.text
        body = rp.json()
        assert body["loaded"] is True
        assert body["source"] == "promoted"
        assert body["name"] == "<promoted>"

        # A second acquire computes the real (zero) diff.
        assert (await ac.post("/api/v1/cmd/acquire", json={})).status_code == 200

        rs = await ac.get("/api/v1/state")
        assert rs.status_code == 200
        snap = rs.json()

    assert snap["reference"] is not None
    assert snap["reference"]["source"] == "promoted"
    assert snap["reference"]["name"] == "<promoted>"
    assert snap["last_diff"] is not None
    assert snap["last_diff"]["n_valid"] >= 1


@pytest.mark.asyncio
async def test_promote_ref_no_acquire_via_ca(test_pv_prefix):
    """Promote on a fresh state (no successful acquire) → CA alarm.

    The putter re-raises NoLastAcquireError; caproto drops the write-ACK so
    the client times out (CaprotoTimeoutError) — symmetric to REST's 422.
    See test_acquire_concurrent_ca.py for the same alarm-as-timeout pattern.
    """
    state = AppState(version="m2-test", bpm_prefixes=["FAKE:BPM1"])
    reader = AsyncMock()  # never read: promote refuses before any acquire

    ioc = PyTxTIOC(
        prefix=test_pv_prefix,
        host="127.0.0.1", port=0, repeater_port=0,
        state=state, reader=reader,
    )
    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    client: ClientContext | None = None
    try:
        client = ClientContext()
        promote_pv, = await client.get_pvs(test_pv_prefix + "CMD:PROMOTE_REF")
        with pytest.raises(CaprotoTimeoutError):
            await promote_pv.write(1)

        # State must remain unloaded — the refused promote changed nothing.
        assert state.reference_loaded is False
    finally:
        await _disconnect_quietly(client)
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


@pytest.mark.asyncio
async def test_promote_ref_no_acquire_via_rest():
    """Promote with no prior acquire → REST 422 (parity with CA alarm)."""
    from pytxt.api.server import create_app

    state = AppState(version="m2-test", bpm_prefixes=["A"])
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post("/api/v1/cmd/promote_ref", json={})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_clear_ref_via_ca(test_pv_prefix):
    """acquire → promote → caput CMD:CLEAR_REF → REF_LOADED=0 and the diff
    PVs are NaN-filled; a second clear is idempotent (no alarm)."""
    prefixes = ["FAKE:BPM1", "FAKE:BPM2"]
    state = AppState(version="m2-test", bpm_prefixes=prefixes)
    reader = _make_reader(prefixes)

    ioc = PyTxTIOC(
        prefix=test_pv_prefix,
        host="127.0.0.1", port=0, repeater_port=0,
        state=state, reader=reader,
    )
    server_task = asyncio.create_task(ioc.run())
    await ioc.wait_until_running()

    client: ClientContext | None = None
    try:
        client = ClientContext()
        acquire_pv, promote_pv, clear_pv = await client.get_pvs(
            test_pv_prefix + "CMD:ACQUIRE",
            test_pv_prefix + "CMD:PROMOTE_REF",
            test_pv_prefix + "CMD:CLEAR_REF",
        )

        await acquire_pv.write(1)
        await asyncio.sleep(0.2)
        await promote_pv.write(1)
        await asyncio.sleep(0.2)

        # Clear the reference.
        await clear_pv.write(1)
        await asyncio.sleep(0.2)

        loaded_pv, xdiff_pv, ydiff_pv = await client.get_pvs(
            test_pv_prefix + "STATE:REF_LOADED",
            test_pv_prefix + "RESULT:BPM:X_DIFF_FIRST_TURN",
            test_pv_prefix + "RESULT:BPM:Y_DIFF_FIRST_TURN",
        )
        loaded = await loaded_pv.read()
        xdiff = await xdiff_pv.read()
        ydiff = await ydiff_pv.read()

        assert int(loaded.data[0]) == 0

        n = len(prefixes)
        x_aligned = np.asarray(xdiff.data[:n], dtype=float)
        y_aligned = np.asarray(ydiff.data[:n], dtype=float)
        assert np.all(np.isnan(x_aligned)), x_aligned
        assert np.all(np.isnan(y_aligned)), y_aligned

        # Idempotent: clearing again succeeds (no alarm / no timeout).
        await clear_pv.write(1)
        await asyncio.sleep(0.1)
        loaded2 = await loaded_pv.read()
        assert int(loaded2.data[0]) == 0
    finally:
        await _disconnect_quietly(client)
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


@pytest.mark.asyncio
async def test_clear_ref_idempotent_via_rest():
    """Clear via REST succeeds (200, loaded=False) even with nothing loaded,
    and again on a second call."""
    from pytxt.api.server import create_app

    state = AppState(version="m2-test", bpm_prefixes=["A"])
    app = create_app(state=state)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        r1 = await ac.post("/api/v1/cmd/clear_ref", json={})
        r2 = await ac.post("/api/v1/cmd/clear_ref", json={})
    assert r1.status_code == 200
    assert r1.json()["loaded"] is False
    assert r2.status_code == 200
    assert r2.json()["loaded"] is False
