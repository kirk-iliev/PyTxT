"""Composition root."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from importlib.metadata import PackageNotFoundError, version as pkg_version
from pathlib import Path

import uvicorn

from pytxt.api.server import create_app
from pytxt.ca_client.bpm_reader import BpmReader
from pytxt.ca_client.corrector_writer import CorrectorWriter
from pytxt.ca_client.injection_trigger import InjectionTrigger
from pytxt.config.bpm_prefixes import load_bpm_prefixes
from pytxt.config.corrector_channels import load_corrector_channels
from pytxt.config.settings import Settings
from pytxt.domain.response_matrix import ResponseMatrixError, load_response_matrix
from pytxt.ioc.server import PyTxTIOC
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)


def _resolve_version() -> str:
    try:
        return pkg_version("pytxt")
    except PackageNotFoundError:
        return "0.0.0+dev"


def _ensure_local_ioc_in_ca_addr_list(host: str, port: int) -> None:
    """Prepend our IOC's host:port to EPICS_CA_ADDR_LIST.

    On appsdev2 (and any ALS control-room host), EPICS_CA_ADDR_LIST is
    set to the ring's broadcast addresses and EPICS_CA_AUTO_ADDR_LIST=NO,
    so localhost is invisible to CA clients. Our own IOC binds at
    `{host}:{port}` (typically 127.0.0.1:59064 per als-profiles safety
    rules), which means in-process CA clients — the WS-to-CA bridge and
    BpmReader — can't find our IOC's PVs unless we add it explicitly.

    EPICS_CA_ADDR_LIST entries accept the `host:port` form; an entry
    without a port falls back to EPICS_CA_SERVER_PORT (typically 5064
    for the ring). Prepending here gives our IOC the first response slot
    for `OSPREY:TEST:TXT:*` searches while leaving ring-BPM searches
    (`SR01C:BPM3:*`) to fall through to the existing ring entries.
    """
    entry = f"{host}:{port}"
    current = os.environ.get("EPICS_CA_ADDR_LIST", "").strip()
    parts = current.split() if current else []
    if entry in parts:
        return
    os.environ["EPICS_CA_ADDR_LIST"] = " ".join([entry, *parts])
    # If AUTO_ADDR_LIST is not explicitly NO, caproto will also broadcast
    # on every local interface — harmless but noisy. Leave whatever the
    # operator set; only set NO if completely unset.
    os.environ.setdefault("EPICS_CA_AUTO_ADDR_LIST", "NO")


async def main() -> None:
    settings = Settings()
    settings.version = _resolve_version()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    bpm_prefixes = load_bpm_prefixes(settings.bpm_prefixes_path)

    # Resolve + create the reference-trajectory library dir. Kept out of
    # Settings (side-effect-free) so unit tests don't litter the repo; the
    # one place the dir actually materializes is here. Threaded into both
    # adapters (IOC + REST app) as the injected reference_dir dependency.
    reference_dir = settings.reference_dir.resolve()
    reference_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Reference library dir: %s", reference_dir)

    # Must run before gather() — once IOC / WS bridge / BpmReader start
    # constructing caproto Contexts, they capture EPICS_CA_ADDR_LIST as-is.
    _ensure_local_ioc_in_ca_addr_list(settings.ioc_host, settings.ioc_port)

    if os.environ.get("PYTXT_USE_SYNTHETIC_READER") == "1":
        from pytxt.ca_client.synthetic_reader import SyntheticBpmReader
        bpm_prefixes = [f"SR{s:02d}C:BPM1" for s in range(1, 13)]
        reader = SyntheticBpmReader(prefixes=bpm_prefixes)
        logger.info(
            "PYTXT_USE_SYNTHETIC_READER=1 — using SyntheticBpmReader with 12 fake BPMs"
        )
    else:
        reader = BpmReader(
            prefixes=bpm_prefixes,
            per_pv_timeout_s=settings.bpm_read_timeout_s,
        )

    logger.info(
        "PyTxT %s starting | prefix=%s | ioc=%s:%d | api=%s:%d | bpms=%d (%s) | "
        "EPICS_CA_ADDR_LIST=%r",
        settings.version, settings.pv_prefix,
        settings.ioc_host, settings.ioc_port,
        settings.api_host, settings.api_port,
        len(bpm_prefixes), settings.bpm_prefixes_path,
        os.environ.get("EPICS_CA_ADDR_LIST", ""),
    )

    state = AppState(
        version=settings.version,
        started_at=time.time(),
        bpm_prefixes=bpm_prefixes,
    )

    # Phase 4 corrector writer — OFF by default (active machine commanding is
    # opt-in). When disabled, STEP_CM returns 503; the analysis path is unaffected.
    corrector_writer = None
    if os.environ.get("PYTXT_USE_SYNTHETIC_READER") == "1":
        from pytxt.ca_client.synthetic_corrector_writer import SyntheticCorrectorWriter
        hcm = load_corrector_channels(settings.hcm_channels_path, "HCM")
        vcm = load_corrector_channels(settings.vcm_channels_path, "VCM")
        corrector_writer = SyntheticCorrectorWriter(hcm_channels=hcm, vcm_channels=vcm)
        logger.info(
            "PYTXT_USE_SYNTHETIC_READER=1 — using SyntheticCorrectorWriter "
            "(%d HCM + %d VCM, in-memory setpoints)", len(hcm), len(vcm)
        )
    elif settings.enable_corrector_writer:
        hcm = load_corrector_channels(settings.hcm_channels_path, "HCM")
        vcm = load_corrector_channels(settings.vcm_channels_path, "VCM")
        corrector_writer = CorrectorWriter(
            hcm_channels=hcm, vcm_channels=vcm,
            per_pv_timeout_s=settings.corrector_io_timeout_s,
        )
        logger.info("Corrector writer ENABLED: %d HCM + %d VCM channels", len(hcm), len(vcm))
    else:
        logger.info("Corrector writer disabled (set PYTXT_ENABLE_CORRECTOR_WRITER=true to arm)")

    # Phase 4 injection trigger — OFF by default. When disabled, INJECT_ONESHOT
    # returns 503. Even enabled, real gun fire still needs per-request opt-in.
    injection_trigger = None
    if os.environ.get("PYTXT_USE_SYNTHETIC_READER") == "1":
        from pytxt.ca_client.synthetic_injection_trigger import SyntheticInjectionTrigger
        injection_trigger = SyntheticInjectionTrigger()
        logger.info(
            "PYTXT_USE_SYNTHETIC_READER=1 — using SyntheticInjectionTrigger (in-memory)"
        )
    elif settings.enable_injection_trigger:
        injection_trigger = InjectionTrigger(per_pv_timeout_s=settings.injection_io_timeout_s)
        logger.warning("Injection trigger ENABLED — INJECT_ONESHOT can command the machine")
    else:
        logger.info("Injection trigger disabled (set PYTXT_ENABLE_INJECTION_TRIGGER=true to arm)")

    # Phase 4 response matrix — load the cached artifact if present (THREAD_START
    # returns 503 without one). Absent/corrupt is non-fatal: log and continue.
    response_matrix = None
    rm_path = Path(settings.response_matrix_path)
    if rm_path.exists():
        try:
            response_matrix = load_response_matrix(rm_path)
            logger.info(
                "Response matrix loaded: %s (%d HCM + %d VCM, %d BPMs) — %s",
                rm_path, response_matrix.n_hcm, response_matrix.n_vcm,
                response_matrix.n_bpms, response_matrix.provenance,
            )
        except ResponseMatrixError:
            logger.exception("Failed to load response matrix %s — THREAD_START disabled", rm_path)
    else:
        logger.info("No response matrix at %s — THREAD_START disabled until generated", rm_path)

    ioc = PyTxTIOC(
        prefix=settings.pv_prefix,
        host=settings.ioc_host,
        port=settings.ioc_port,
        repeater_port=settings.ioc_repeater_port,
        state=state,
        reader=reader,
        reference_dir=reference_dir,
        corrector_writer=corrector_writer,
        injection_trigger=injection_trigger,
        response_matrix=response_matrix,
    )

    api_app = create_app(
        state=state,
        settings=settings,
        bpm_reader=reader,
        reference_dir=reference_dir,
        corrector_writer=corrector_writer,
        injection_trigger=injection_trigger,
        response_matrix=response_matrix,
    )
    config = uvicorn.Config(
        api_app,
        host=settings.api_host,
        port=settings.api_port,
        log_config=None,
        access_log=False,
    )
    api_server = uvicorn.Server(config)

    async def heartbeat_loop() -> None:
        while True:
            await asyncio.sleep(settings.heartbeat_interval_s)
            await state.update(
                heartbeat=state.heartbeat + 1,
                uptime_s_pushed=state.uptime_s,
            )

    # Start reader once the IOC is running so name resolution sees the network.
    async def start_reader_after_warmup() -> None:
        await asyncio.sleep(1.0)
        try:
            await reader.start()
            logger.info("BpmReader connected to %d BPMs", len(bpm_prefixes))
        except Exception:
            logger.exception("BpmReader.start() failed — ACQUIRE will fail until reachable")

    async def start_corrector_writer_after_warmup() -> None:
        if corrector_writer is None:
            return
        await asyncio.sleep(1.0)
        try:
            await corrector_writer.start()
            logger.info("CorrectorWriter connected")
        except Exception:
            logger.exception("CorrectorWriter.start() failed — STEP_CM will fail until reachable")

    async def start_injection_trigger_after_warmup() -> None:
        if injection_trigger is None:
            return
        await asyncio.sleep(1.0)
        try:
            await injection_trigger.start()
            logger.info("InjectionTrigger connected")
        except Exception:
            logger.exception("InjectionTrigger.start() failed — INJECT_ONESHOT will fail until reachable")

    await asyncio.gather(
        ioc.run(),
        api_server.serve(),
        heartbeat_loop(),
        start_reader_after_warmup(),
        start_corrector_writer_after_warmup(),
        start_injection_trigger_after_warmup(),
    )
