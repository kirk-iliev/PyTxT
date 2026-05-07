"""FastAPI app factory.

Constructs the FastAPI app with all routers + WS bridge + static
frontend mount, given the shared AppState and IOC references.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pytxt.api.routes import health, cmd
from pytxt.api.routes import state as state_route
from pytxt.api import ws_bridge
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def create_app(state: AppState, ioc: Optional[Any] = None, settings: Optional[Any] = None) -> FastAPI:
    """Create and configure the FastAPI app.

    Parameters
    ----------
    state : AppState
        Shared in-process state. REST routes read it for projections;
        REST commands invoke handlers that mutate it.
    ioc : Any
        Reference to the running PyTxTIOC. WS bridge needs the IOC's
        prefix/port to subscribe via in-process CA. May be None in
        tests that only exercise REST.
    settings : Settings
        Settings instance. May be None in unit tests.
    """
    app = FastAPI(
        title="PyTxT",
        version=state.version or "0.0.0+dev",
        description=(
            "Turn-by-turn beam analysis service for the ALS injection chain. "
            "REST + WebSocket browser interface; canonical state interface is "
            "EPICS PVs published by the embedded soft IOC."
        ),
    )

    app.state.app_state = state
    app.state.ioc = ioc
    app.state.settings = settings

    # Permissive CORS for control-room network (no auth in v1)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(state_route.router)
    app.include_router(cmd.router)
    app.include_router(ws_bridge.router)

    # Static frontend — only mount if index.html exists (populated by Task 15)
    if (_FRONTEND_DIR / "index.html").exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")

    return app
