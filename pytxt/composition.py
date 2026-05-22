"""Composition root."""
from __future__ import annotations

import asyncio
import logging
import os
import time
from importlib.metadata import PackageNotFoundError, version as pkg_version

import uvicorn

from pytxt.api.server import create_app
from pytxt.ca_client.bpm_reader import BpmReader
from pytxt.config.bpm_prefixes import load_bpm_prefixes
from pytxt.config.settings import Settings
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

    # Must run before gather() — once IOC / WS bridge / BpmReader start
    # constructing caproto Contexts, they capture EPICS_CA_ADDR_LIST as-is.
    _ensure_local_ioc_in_ca_addr_list(settings.ioc_host, settings.ioc_port)

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

    reader = BpmReader(
        prefixes=bpm_prefixes,
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
            logger.info("BpmReader connected to %d BPMs", len(bpm_prefixes))
        except Exception:
            logger.exception("BpmReader.start() failed — ACQUIRE will fail until reachable")

    await asyncio.gather(
        ioc.run(),
        api_server.serve(),
        heartbeat_loop(),
        start_reader_after_warmup(),
    )
