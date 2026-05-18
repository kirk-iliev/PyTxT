"""Composition root.

The single place that knows about every subsystem. Wires AppState, the
soft IOC, FastAPI/uvicorn, and the heartbeat loop onto one asyncio
event loop. Adding a subsystem in a future phase = add one `await` to
`gather()`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from importlib.metadata import PackageNotFoundError, version as pkg_version

import uvicorn

from pytxt.api.server import create_app
from pytxt.config.settings import Settings
from pytxt.ioc.server import PyTxTIOC
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)


def _resolve_version() -> str:
    """Read installed package version; fall back to dev marker for editable checkouts."""
    try:
        return pkg_version("pytxt")
    except PackageNotFoundError:
        return "0.0.0+dev"


async def main() -> None:
    settings = Settings()
    settings.version = _resolve_version()

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info(
        "PyTxT %s starting | prefix=%s | ioc=%s:%d | api=%s:%d",
        settings.version,
        settings.pv_prefix,
        settings.ioc_host,
        settings.ioc_port,
        settings.api_host,
        settings.api_port,
    )

    state = AppState(version=settings.version, started_at=time.time())

    ioc = PyTxTIOC(
        prefix=settings.pv_prefix,
        host=settings.ioc_host,
        port=settings.ioc_port,
        repeater_port=settings.ioc_repeater_port,
        state=state,
    )

    api_app = create_app(state=state, settings=settings)
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

    await asyncio.gather(
        ioc.run(),
        api_server.serve(),
        heartbeat_loop(),
    )
