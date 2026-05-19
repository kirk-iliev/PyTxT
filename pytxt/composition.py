"""Composition root."""
from __future__ import annotations

import asyncio
import logging
import time
from importlib.metadata import PackageNotFoundError, version as pkg_version

import uvicorn

from pytxt.api.server import create_app
from pytxt.ca_client.bpm_reader import BpmReader
from pytxt.config.settings import Settings
from pytxt.ioc.server import PyTxTIOC
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)


def _resolve_version() -> str:
    try:
        return pkg_version("pytxt")
    except PackageNotFoundError:
        return "0.0.0+dev"


# M1: hardcoded single-BPM list. M2-T2 replaces this with config-file loading.
_PHASE_2_M1_BPM_PREFIXES = ["SR01C:BPM1"]


async def main() -> None:
    settings = Settings()
    settings.version = _resolve_version()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info(
        "PyTxT %s starting | prefix=%s | ioc=%s:%d | api=%s:%d | bpms=%d",
        settings.version, settings.pv_prefix,
        settings.ioc_host, settings.ioc_port,
        settings.api_host, settings.api_port,
        len(_PHASE_2_M1_BPM_PREFIXES),
    )

    state = AppState(
        version=settings.version,
        started_at=time.time(),
        bpm_prefixes=_PHASE_2_M1_BPM_PREFIXES,
    )

    reader = BpmReader(
        prefixes=_PHASE_2_M1_BPM_PREFIXES,
        per_pv_timeout_s=settings.bpm_read_timeout_s,
    )

    ioc = PyTxTIOC(
        prefix=settings.pv_prefix,
        host=settings.ioc_host,
        port=settings.ioc_port,
        repeater_port=settings.ioc_repeater_port,
        state=state,
        reader=reader,
    )

    api_app = create_app(state=state, settings=settings, bpm_reader=reader)
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
            logger.info("BpmReader connected to %d BPMs", len(_PHASE_2_M1_BPM_PREFIXES))
        except Exception:
            logger.exception("BpmReader.start() failed — ACQUIRE will fail until reachable")

    await asyncio.gather(
        ioc.run(),
        api_server.serve(),
        heartbeat_loop(),
        start_reader_after_warmup(),
    )
