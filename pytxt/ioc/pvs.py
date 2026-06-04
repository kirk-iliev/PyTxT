"""caproto PVGroup defining the phase-1 + phase-2 PV namespaces.

Each pvproperty's `doc` becomes the .DESC field — discoverable to
agents reading the IOC's introspection PVs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import caproto as ca
from caproto.server import PVGroup, pvproperty

from pytxt.api.schemas.threading import InjectOneshotRequest, StepCMRequest
from pytxt.handlers.acquire import handle_acquire
from pytxt.handlers.ping import handle_ping
from pytxt.handlers.reference import (
    handle_clear_ref,
    handle_load_ref,
    handle_promote_ref,
    handle_save_ref,
)
from pytxt.handlers.threading import handle_inject_oneshot, handle_step_cm
from pytxt.state.app_state import AppState

_BPM_MAX = 128  # waveform max_length; accommodates ~120 BPMs with headroom


def _as_text(value) -> str:
    """Normalize a CHAR-array CA write to a str (caproto may deliver str,
    bytes, or a list of byte ints depending on the client encoding)."""
    if isinstance(value, str):
        return value.rstrip("\x00")
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8").rstrip("\x00")
    # list/tuple/ndarray of byte ints
    return bytes(bytearray(int(c) for c in value)).decode("utf-8").rstrip("\x00")


class PyTxTPVGroup(PVGroup):
    # === HEALTH:* ===
    heartbeat = pvproperty(
        value=0, dtype=int, read_only=True,
        name="HEALTH:HEARTBEAT",
        doc="Liveness counter; increments every 1 second",
    )
    uptime_s = pvproperty(
        value=0.0, dtype=float, read_only=True,
        name="HEALTH:UPTIME_S",
        doc="Seconds since process start",
    )

    # === STATE:* (phase 1) ===
    version = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:VERSION",
        doc="Semantic version of the running PyTxT app",
    )
    last_ping_at = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_PING_AT",
        doc="ISO-8601 UTC timestamp of most recent ping; empty before first ping",
    )
    ping_count = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:PING_COUNT",
        doc="Total pings received since startup",
    )

    # === STATE:ACQUIRE_* (phase 2) ===
    acquire_in_flight = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:ACQUIRE_IN_FLIGHT",
        doc="1 while an acquisition is running; rejects concurrent CMD:ACQUIRE writes",
    )
    last_acquire_status = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:LAST_ACQUIRE_STATUS",
        doc="Enum: 0=NEVER, 1=ACQUIRING, 2=OK, 3=PARTIAL, 4=FAILED",
    )
    last_acquire_ok_count = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:LAST_ACQUIRE_OK_COUNT",
        doc="BPMs that returned valid data on the most recent ACQUIRE",
    )
    last_acquire_fail_count = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:LAST_ACQUIRE_FAIL_COUNT",
        doc="BPMs that timed out or returned invalid data on the most recent ACQUIRE",
    )
    last_acquire_timestamp = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_ACQUIRE_TIMESTAMP",
        doc="ISO-8601 UTC timestamp of the most recent acquisition; empty before first ACQUIRE",
    )
    last_acquire_fail_reason = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_ACQUIRE_FAIL_REASON",
        doc="Short error message when LAST_ACQUIRE_STATUS=FAILED; empty otherwise",
    )
    last_acquire_failed_bpm_names = pvproperty(
        value=[""] * _BPM_MAX, dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:LAST_ACQUIRE_FAILED_BPM_NAMES",
        max_length=_BPM_MAX,
        doc="Names of failed BPMs from the most recent ACQUIRE",
    )

    # === STATE:REF_* (phase 3) ===
    ref_loaded = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:REF_LOADED",
        doc="1 when a reference trajectory is loaded; 0 when none",
    )
    ref_name = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:REF_NAME",
        doc="Name of the loaded reference ('<promoted>' under promote); empty when none",
    )
    ref_loaded_at = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:REF_LOADED_AT",
        doc="ISO-8601 UTC timestamp when the reference was loaded; empty when none",
    )
    ref_source = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:REF_SOURCE",
        doc="Provenance of the loaded reference: 'promoted', 'file', or empty when none",
    )

    # === STATE:CM_* (phase 4 — corrector step) ===
    cm_step_in_flight = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:CM_STEP_IN_FLIGHT",
        doc="1 while a CMD:STEP_CM is applying; rejects concurrent steps",
    )
    cm_last_status = pvproperty(
        value="NEVER", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:CM_LAST_STATUS",
        doc="Outcome of the most recent STEP_CM: NEVER, APPLIED, DRY_RUN, or REFUSED",
    )
    cm_last_family = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:CM_LAST_FAMILY",
        doc="Corrector family of the most recent STEP_CM (HCM/VCM); empty before first",
    )
    cm_last_n_applied = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:CM_LAST_N_APPLIED",
        doc="Number of correctors written by the most recent STEP_CM",
    )
    cm_last_n_clamped = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:CM_LAST_N_CLAMPED",
        doc="Number of correctors clamped to their limit in the most recent STEP_CM",
    )
    cm_last_timestamp = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:CM_LAST_TIMESTAMP",
        doc="ISO-8601 UTC timestamp of the most recent STEP_CM; empty before first",
    )

    # === STATE:INJ_* (phase 4 — injection one-shot) ===
    inject_in_flight = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:INJ_IN_FLIGHT",
        doc="1 while a CMD:INJECT_ONESHOT is firing; rejects concurrent shots",
    )
    inj_last_status = pvproperty(
        value="NEVER", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:INJ_LAST_STATUS",
        doc="Outcome of the most recent INJECT_ONESHOT: NEVER or FIRED",
    )
    inj_last_bucket = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:INJ_LAST_BUCKET",
        doc="SR bucket of the most recent injection shot",
    )
    inj_last_mode = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:INJ_LAST_MODE",
        doc="Injection mode of the most recent shot (40=SR inject, 42=bumps only)",
    )
    inj_last_inhibit = pvproperty(
        value=1, dtype=int, read_only=True,
        name="STATE:INJ_LAST_INHIBIT",
        doc="Gun-inhibit of the most recent shot: 1=gun blocked, 0=gun fired",
    )
    inj_last_seq_num = pvproperty(
        value=0, dtype=int, read_only=True,
        name="STATE:INJ_LAST_SEQ_NUM",
        doc="TimInjReq sequence number written by the most recent shot (echo confirm)",
    )
    inj_last_timestamp = pvproperty(
        value="", dtype=ca.ChannelType.STRING, read_only=True,
        name="STATE:INJ_LAST_TIMESTAMP",
        doc="ISO-8601 UTC timestamp of the most recent injection shot; empty before first",
    )

    # === RESULT:BPM:* (phase 2) ===
    result_bpm_x_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:X_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM X position (mm) at detected injection turn; NaN for failed BPMs",
    )
    result_bpm_y_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:Y_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM Y position (mm) at detected injection turn; NaN for failed BPMs",
    )
    result_bpm_x_diff_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:X_DIFF_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM X B-R0 (mm); NaN where either side NaN or no ref loaded",
    )
    result_bpm_y_diff_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:Y_DIFF_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM Y B-R0 (mm); NaN where either side NaN or no ref loaded",
    )
    result_bpm_sum_first_turn = pvproperty(
        value=[0.0] * _BPM_MAX, dtype=float, read_only=True,
        name="RESULT:BPM:SUM_FIRST_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM sum signal (AU) at detected injection turn; NaN for failed BPMs",
    )
    result_bpm_injection_turn = pvproperty(
        value=[0] * _BPM_MAX, dtype=int, read_only=True,
        name="RESULT:BPM:INJECTION_TURN",
        max_length=_BPM_MAX,
        doc="Per-BPM detected injection-turn sample index; -1 for failed BPMs",
    )
    result_bpm_names = pvproperty(
        value=[""] * _BPM_MAX, dtype=ca.ChannelType.STRING, read_only=True,
        name="RESULT:BPM:NAMES",
        max_length=_BPM_MAX,
        doc="Static-after-startup: canonical BPM prefix for each array index",
    )

    # === CMD:* ===
    cmd_ping = pvproperty(
        value=0, dtype=int,
        name="CMD:PING",
        doc="Write any value to issue a ping (value ignored; trigger only)",
    )
    cmd_acquire = pvproperty(
        value=0, dtype=int,
        name="CMD:ACQUIRE",
        doc="Write any value to trigger BPM acquisition (value ignored; trigger only)",
    )
    cmd_promote_ref = pvproperty(
        value=0, dtype=int,
        name="CMD:PROMOTE_REF",
        doc="Write any value to promote the current acquisition to an in-memory reference (value ignored; trigger only)",
    )
    cmd_clear_ref = pvproperty(
        value=0, dtype=int,
        name="CMD:CLEAR_REF",
        doc="Write any value to unload the current reference (value ignored; trigger only)",
    )
    cmd_load_ref = pvproperty(
        value="", dtype=ca.ChannelType.STRING,
        name="CMD:LOAD_REF",
        doc="Write a reference basename (e.g. 'foo.mat') to load it from the library and arm its B-R0 diff",
    )
    cmd_save_ref = pvproperty(
        value="", dtype=ca.ChannelType.STRING,
        name="CMD:SAVE_REF",
        doc="Write a basename (e.g. 'foo.mat') to save the current acquisition to the library; empty string uses a timestamp default",
    )
    # CHAR array (not DBF_STRING) so the JSON payload can exceed the 40-char
    # EPICS string limit; report_as_string makes it read/write as a plain string.
    cmd_step_cm = pvproperty(
        value="",
        dtype=ca.ChannelType.CHAR, max_length=8192,
        string_encoding="utf-8", report_as_string=True,
        name="CMD:STEP_CM",
        doc=(
            "Write a JSON payload to apply one corrector step (identical to "
            "POST /api/v1/cmd/step_cm): "
            '{"family":"HCM"|"VCM","device_list":[int],"deltas":[float amps],'
            '"expected_prior_a":[float amps],"tol_a":float,"dry_run":bool}. '
            "Compare-and-set: refused (CA error) if any live setpoint diverges."
        ),
    )

    # CHAR array so the JSON payload can exceed the 40-char DBF_STRING limit.
    cmd_inject_oneshot = pvproperty(
        value="",
        dtype=ca.ChannelType.CHAR, max_length=8192,
        string_encoding="utf-8", report_as_string=True,
        name="CMD:INJECT_ONESHOT",
        doc=(
            "Write a JSON payload to fire one injection shot (identical to "
            "POST /api/v1/cmd/inject_oneshot): "
            '{"bucket":int(default 308),"gun_bunches":int,"mode":int(40=SR,42=bumps),'
            '"inhibit":0|1(default 1=gun blocked),"allow_gun_fire":bool,"force":bool}. '
            "inhibit=0 (real gun fire) requires allow_gun_fire=true."
        ),
    )

    def __init__(
        self,
        *args,
        state: AppState,
        reader: Optional[object] = None,
        reference_dir: Optional[Path] = None,
        corrector_writer: Optional[object] = None,
        injection_trigger: Optional[object] = None,
        **kwargs,
    ):
        self._state = state
        self._reader = reader
        self._reference_dir = reference_dir
        self._corrector_writer = corrector_writer
        self._injection_trigger = injection_trigger
        super().__init__(*args, **kwargs)

    @cmd_ping.putter
    async def cmd_ping(self, instance, value):
        await handle_ping(self._state)
        return value

    @cmd_acquire.putter
    async def cmd_acquire(self, instance, value):
        """CA write to CMD:ACQUIRE dispatches to the canonical handler.

        If a reader is not configured (e.g., unit-style tests), the
        write is a no-op so the IOC remains testable in isolation.

        AcquisitionInFlightError is RE-RAISED so caproto surfaces it as a
        CA write error to the client — symmetric to REST's 409 returned
        by POST /api/v1/cmd/acquire when an acquire is in flight. The
        STATE:ACQUIRE_IN_FLIGHT PV continues to publish 1 during the
        busy window for subscribers who prefer observation over retry.
        """
        if self._reader is None:
            return value
        await handle_acquire(self._state, self._reader)
        return value

    @cmd_promote_ref.putter
    async def cmd_promote_ref(self, instance, value):
        """CA write to CMD:PROMOTE_REF promotes the live acquisition to a ref.

        Acts on self._state only — no reader required, unlike CMD:ACQUIRE.
        NoLastAcquireError is RE-RAISED so caproto surfaces it as a CA write
        error — symmetric to REST's 422 from POST /api/v1/cmd/promote_ref.
        STATE:REF_LOADED publishes the outcome for subscribers who prefer
        observation over retry.
        """
        await handle_promote_ref(self._state)
        return value

    @cmd_clear_ref.putter
    async def cmd_clear_ref(self, instance, value):
        """CA write to CMD:CLEAR_REF unloads the current reference.

        Acts on self._state only — no reader required. Idempotent: succeeds
        even when nothing is loaded (mirrors REST's /api/v1/cmd/clear_ref).
        """
        await handle_clear_ref(self._state)
        return value

    @cmd_load_ref.putter
    async def cmd_load_ref(self, instance, value):
        """CA write to CMD:LOAD_REF loads a named reference from the library.

        The written string is the reference basename. Resolves + parses via
        the canonical handler (using self._reference_dir injected at construct
        time). Typed exceptions (InvalidReferenceNameError, ReferenceNotFoundError,
        ReferenceLoadError) are RE-RAISED so caproto surfaces them as CA write
        errors — symmetric to REST's 422/404. STATE:REF_* PVs confirm the load.
        """
        await handle_load_ref(self._state, self._reference_dir, value)
        return value

    @cmd_save_ref.putter
    async def cmd_save_ref(self, instance, value):
        """CA write to CMD:SAVE_REF saves the current acquisition to the library.

        The written string is the target basename; an empty string maps to None
        → the handler's timestamp default. Typed exceptions (NoLastAcquireError,
        InvalidReferenceNameError, ReferenceExistsError) are RE-RAISED so caproto
        surfaces them as CA write errors — symmetric to REST's 422/409. SAVE does
        not mutate AppState; confirmation is the file appearing in the library.
        """
        name = value or None  # empty CA string → timestamp default
        await handle_save_ref(self._state, self._reference_dir, name)
        return value

    @cmd_step_cm.putter
    async def cmd_step_cm(self, instance, value):
        """CA write to CMD:STEP_CM applies one corrector step from a JSON payload.

        The written string is the same JSON as the REST body (StepCMRequest), so
        the CA and REST paths call the identical handler. If no corrector writer
        is configured (unit-style tests), the write is a no-op. Typed exceptions
        (CMStepInFlightError, CMPreconditionError) and a malformed payload are
        RE-RAISED so caproto surfaces them as CA write errors — symmetric to
        REST's 409/422. STATE:CM_LAST_* PVs confirm the outcome.
        """
        if self._corrector_writer is None:
            return value
        req = StepCMRequest.model_validate_json(_as_text(value))
        await handle_step_cm(
            self._state, self._corrector_writer,
            family=req.family, device_list=req.device_list, deltas=req.deltas,
            expected_prior_a=req.expected_prior_a, tol_a=req.tol_a,
            dry_run=req.dry_run,
        )
        return value

    @cmd_inject_oneshot.putter
    async def cmd_inject_oneshot(self, instance, value):
        """CA write to CMD:INJECT_ONESHOT fires one shot from a JSON payload.

        Same JSON as the REST body (InjectOneshotRequest), so CA and REST call
        the identical handler. No-op if no injection trigger is configured. Typed
        exceptions (GunFireNotAllowedError, InjectInFlightError,
        InjectionPreconditionError) and a malformed payload are RE-RAISED so
        caproto surfaces them as CA write errors — symmetric to REST's 403/409/422.
        STATE:INJ_LAST_* PVs confirm the shot.
        """
        if self._injection_trigger is None:
            return value
        req = InjectOneshotRequest.model_validate_json(_as_text(value))
        await handle_inject_oneshot(
            self._state, self._injection_trigger,
            bucket=req.bucket, gun_bunches=req.gun_bunches, mode=req.mode,
            inhibit=req.inhibit, allow_gun_fire=req.allow_gun_fire, force=req.force,
        )
        return value
