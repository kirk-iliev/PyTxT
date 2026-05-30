"""FastAPI app factory."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pytxt.api.routes import health, cmd, references, result
from pytxt.api.routes import state as state_route
from pytxt.api import ws_bridge
from pytxt.state.app_state import AppState

logger = logging.getLogger(__name__)

_FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


def create_app(
    state: AppState,
    settings: Optional[Any] = None,
    bpm_reader: Optional[Any] = None,
    reference_dir: Optional[Path] = None,
) -> FastAPI:
    """Create and configure the FastAPI app.

    Parameters
    ----------
    state : AppState
        Shared in-process state.
    settings : Settings
        Settings instance.
    bpm_reader : BpmReader | None
        Phase-2 CA client. None in tests that don't exercise ACQUIRE.
    reference_dir : Path | None
        Phase-3 reference-trajectory library dir. None in tests that don't
        exercise LOAD/SAVE.
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
    app.state.settings = settings
    app.state.bpm_reader = bpm_reader
    app.state.reference_dir = reference_dir

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
    app.include_router(result.router)
    app.include_router(references.router)
    app.include_router(ws_bridge.router)

    if (_FRONTEND_DIR / "index.html").exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")

    return app
