"""The agentic-parity invariant test.

For every command that exists in PyTxT, issuing it via CA write and via
REST POST must produce bit-identical state effects. This test is the
load-bearing canary for agentic parity. **It must remain green forever.**
"""
import asyncio
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import numpy as np
import pytest
import caproto as ca
from caproto.asyncio.client import Context as ClientContext
from httpx import AsyncClient, ASGITransport

from pytxt.domain.first_turn_extract import extract_first_turn
from pytxt.domain.reference import save_reference_mat
from pytxt.domain.types import RawBPM


def _public_state(state) -> dict:
    """Explicit projection of AppState fields the parity test compares.

    Phase 2: also covers acquire_in_flight, last_acquire.status, ok/fail
    counts. Phase 3 (M2): reference status + last_diff summary. Raw waveform
    dicts, timestamps, and diff arrays are normalized because they differ by
    identity / across runs.
    """
    return {
        "heartbeat": state.heartbeat,
        "ping_count": state.ping_count,
        "last_ping_at": "<set>" if state.last_ping_at else None,
        "version": state.version,
        "uptime_s_pushed": state.uptime_s_pushed,
        # phase 2
        "acquire_in_flight": state.acquire_in_flight,
        "last_acquire_status": state.last_acquire.status.value,
        "last_acquire_ok_count": state.last_acquire.ok_count,
        "last_acquire_fail_count": state.last_acquire.fail_count,
        "last_acquire_failed_bpm_names": list(state.last_acquire.failed_bpm_names),
        "last_acquire_timestamp": "<set>" if state.last_acquire.timestamp else None,
        "last_acquire_raws_keys": sorted(state.last_acquire_raws.keys()),
        # phase 3 (M2): reference status + diff summary. Project last_diff to a
        # stable shape — raw dx/dy arrays differ by identity and break ==.
        "reference_loaded": state.reference_loaded,
        "reference_source": state.reference_source.value,
        "reference_name": state.reference_name,
        "reference_loaded_at": "<set>" if state.reference_loaded_at else None,
        # M3: reference_file_path is identity/dir-specific — project to set|None.
        "reference_file_path": "<set>" if state.reference_file_path else None,
        "last_diff": (
            None if state.last_diff is None
            else {"n_valid": state.last_diff.summary.n_valid}
        ),
        # phase 4: corrector-step state
        "cm_step_in_flight": state.cm_step_in_flight,
        "cm_last_status": state.last_cm_step.status,
        "cm_last_family": state.last_cm_step.family,
        "cm_last_n_applied": state.last_cm_step.n_applied,
        "cm_last_n_clamped": state.last_cm_step.n_clamped,
    }


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


async def _do_via_ca(prefix: str, cmd: str, pre_acquire: bool = False, cmd_value=1) -> None:
    client = ClientContext()
    try:
        if pre_acquire:
            # Commands like PROMOTE_REF / SAVE_REF need a prior successful
            # acquire to source from. Trigger one on this same state first.
            acq_pv, = await client.get_pvs(prefix + "CMD:ACQUIRE")
            await acq_pv.write(1)
            await asyncio.sleep(0.2)
        pv, = await client.get_pvs(prefix + cmd)
        # String-valued CMD PVs (LOAD_REF/SAVE_REF) take a name, not 1. Long
        # JSON payloads (STEP_CM) exceed the 40-char DBF_STRING limit, so write
        # them to the CHAR-array PV as a list of UTF-8 byte values.
        if isinstance(cmd_value, str) and len(cmd_value) > 40:
            await pv.write(cmd_value.encode("utf-8"), data_type=ca.ChannelType.CHAR)
        else:
            await pv.write(cmd_value)
        await asyncio.sleep(0.2)   # let listener fan-out complete
    finally:
        # Disconnect so background command-queue tasks don't outlive the test
        # and spin against a dead event loop on the next parametrize round.
        try:
            await asyncio.wait_for(client.disconnect(), timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            pass


async def _do_via_rest(app, path: str, pre_acquire: bool = False, rest_body: dict | None = None) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        if pre_acquire:
            ra = await ac.post("/api/v1/cmd/acquire", json={})
            assert ra.status_code == 200, f"REST pre-acquire failed: {ra.status_code} {ra.text}"
        r = await ac.post(path, json={} if rest_body is None else rest_body)
        assert r.status_code == 200, f"REST {path} failed: {r.status_code} {r.text}"


# Commands that act on a live acquisition (e.g. PROMOTE_REF, SAVE_REF) need BPM
# prefixes and a reader on both arms so the pre-acquire can run. LOAD_REF needs
# prefixes too so the pre-seeded reference aligns onto a non-empty BPM set.
_NEEDS_BPMS = {"acquire", "promote_ref", "clear_ref", "load_ref", "save_ref"}

# CMD PVs that carry a name string + a fixed reference filename used for the
# LOAD_REF parity row (pre-seeded identically into both arms' dirs).
_STRING_CMDS = {"load_ref", "save_ref"}
_LOAD_REF_NAME = "parity.mat"


def _seed_reference(reference_dir, prefixes):
    """Write a synthetic reference .mat into ``reference_dir`` so a LOAD_REF
    parity arm finds an identical file (same bytes, per-arm dir)."""
    raws = {p: _fake_raw(p) for p in prefixes}
    first_turn = extract_first_turn({p: raws[p] for p in prefixes})
    save_reference_mat(reference_dir / _LOAD_REF_NAME, first_turn, raws, list(prefixes))


def _bpms_for(command_name: str) -> list[str]:
    if command_name not in _NEEDS_BPMS:
        return []
    # LOAD/SAVE need ≥2 BPMs: scipy.io.savemat squeezes a single-BPM R0 from
    # (2, 1) to (2,), which load_reference_mat then rejects. Two BPMs keeps the
    # round-trip shape valid. The other rows keep the historical ["A"].
    if command_name in _STRING_CMDS:
        return ["A", "B"]
    return ["A"]


def _make_state(command_name: str):
    from pytxt.state.app_state import AppState
    return AppState(version="0.1.0", started_at=time.time(),
                    bpm_prefixes=_bpms_for(command_name))


def _make_reader(command_name: str):
    if command_name not in _NEEDS_BPMS:
        return None
    reader = AsyncMock()
    reader.read_all.return_value = {p: _fake_raw(p) for p in _bpms_for(command_name)}
    return reader


# STEP_CM parity: an in-process fake corrector writer injected into both arms,
# so a CA JSON write to CMD:STEP_CM and a REST POST drive the identical handler.
_STEP_CM_PAYLOAD = {
    "family": "HCM", "device_list": [0], "deltas": [1.0],
    "expected_prior_a": [0.0], "tol_a": 0.05,
}


class _ParityFakeWriter:
    def __init__(self):
        self.written = None

    def channels(self, family):
        from pytxt.config.corrector_channels import CorrectorChannel
        if family not in ("HCM", "VCM"):
            raise ValueError(f"unknown family {family!r}")
        return [CorrectorChannel(f"{family}{i}", 35.0, family, i) for i in range(8)]

    async def read_setpoints(self, family, indices):
        return [0.0 for _ in indices]

    async def write_setpoints(self, family, indices, values_a):
        self.written = (family, list(indices), list(values_a))


def _make_corrector_writer(command_name: str):
    return _ParityFakeWriter() if command_name == "step_cm" else None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command_name, ca_pv_suffix, rest_path, requires_acquire",
    [
        ("ping", "CMD:PING", "/api/v1/cmd/ping", False),
        ("acquire", "CMD:ACQUIRE", "/api/v1/cmd/acquire", False),
        ("promote_ref", "CMD:PROMOTE_REF", "/api/v1/cmd/promote_ref", True),
        ("clear_ref", "CMD:CLEAR_REF", "/api/v1/cmd/clear_ref", False),
        # M3 string-valued CMD PVs. LOAD: harness pre-seeds an identical .mat
        # into each arm's dir + sends the name. SAVE: needs a prior acquire and
        # mutates no state, so parity holds trivially (per-arm dir avoids 409).
        ("load_ref", "CMD:LOAD_REF", "/api/v1/cmd/load_ref", False),
        ("save_ref", "CMD:SAVE_REF", "/api/v1/cmd/save_ref", True),
        # Phase 4: STEP_CM carries a JSON payload (CHAR-array PV ⇄ REST body).
        ("step_cm", "CMD:STEP_CM", "/api/v1/cmd/step_cm", False),
    ],
)
async def test_parity_ca_vs_rest(test_pv_prefix, tmp_path, command_name, ca_pv_suffix, rest_path, requires_acquire):
    from pytxt.ioc.server import PyTxTIOC
    from pytxt.api.server import create_app

    # M3: each arm gets its OWN reference_dir so SAVE's file artifact doesn't
    # collide cross-arm (409). LOAD pre-seeds an identical .mat into both.
    ca_ref_dir = tmp_path / "ca"
    rest_ref_dir = tmp_path / "rest"
    ca_ref_dir.mkdir()
    rest_ref_dir.mkdir()

    # String-PV trigger values: LOAD/SAVE write the name; SAVE uses a stable
    # name (each arm has its own dir, so no collision).
    is_string_cmd = command_name in _STRING_CMDS
    if command_name == "load_ref":
        _seed_reference(ca_ref_dir, _make_state(command_name).bpm_prefixes)
        _seed_reference(rest_ref_dir, _make_state(command_name).bpm_prefixes)
    ca_value = _LOAD_REF_NAME if is_string_cmd else 1
    rest_body = {"name": _LOAD_REF_NAME} if is_string_cmd else None
    if command_name == "step_cm":
        import json
        ca_value = json.dumps(_STEP_CM_PAYLOAD)
        rest_body = _STEP_CM_PAYLOAD

    # --- Path 1: CA write ---
    state_ca = _make_state(command_name)
    reader_ca = _make_reader(command_name)
    ioc_ca = PyTxTIOC(prefix=test_pv_prefix, host="127.0.0.1", port=0,
                      repeater_port=0, state=state_ca, reader=reader_ca,
                      reference_dir=ca_ref_dir,
                      corrector_writer=_make_corrector_writer(command_name))
    server_task = asyncio.create_task(ioc_ca.run())
    await ioc_ca.wait_until_running()
    try:
        before_ca = _public_state(state_ca)
        await _do_via_ca(test_pv_prefix, ca_pv_suffix,
                         pre_acquire=requires_acquire, cmd_value=ca_value)
        after_ca = _public_state(state_ca)
    finally:
        server_task.cancel()
        try:
            await asyncio.wait_for(server_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    diff_ca = {k: (before_ca[k], after_ca[k]) for k in after_ca if before_ca[k] != after_ca[k]}

    # --- Path 2: REST POST ---
    state_rest = _make_state(command_name)
    reader_rest = _make_reader(command_name)
    app = create_app(state=state_rest, reference_dir=rest_ref_dir,
                     corrector_writer=_make_corrector_writer(command_name))
    if reader_rest is not None:
        app.state.bpm_reader = reader_rest

    before_rest = _public_state(state_rest)
    await _do_via_rest(app, rest_path, pre_acquire=requires_acquire, rest_body=rest_body)
    after_rest = _public_state(state_rest)
    diff_rest = {k: (before_rest[k], after_rest[k]) for k in after_rest if before_rest[k] != after_rest[k]}

    assert diff_ca == diff_rest, (
        f"Command {command_name!r} produced different effects via CA vs REST.\n"
        f"  CA diff:   {diff_ca}\n"
        f"  REST diff: {diff_rest}\n"
        "The agentic-parity invariant has been violated."
    )
