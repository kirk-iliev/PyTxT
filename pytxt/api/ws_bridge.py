"""WebSocket-to-CA bridge.

Each connected browser client subscribes to PV names; the bridge runs an
in-process caproto async client that subscribes to those PVs and
forwards updates as JSON. Per the design (§6.5), routing browser
updates through CA — rather than directly through AppState — preserves
the "browser is just another CA client" invariant: browsers see
identical type coercions and update semantics as Phoebus or any
external CA agent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any

from caproto.asyncio.client import Context as ClientContext
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pytxt.api.schemas.ws import WSError, WSSubscribe, WSValueUpdate

logger = logging.getLogger(__name__)

router = APIRouter()


def _coerce_nan(v: Any) -> Any:
    """JSON has no NaN; map float NaN → None so the WS message parses on the client."""
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def _coerce_element(v: Any) -> Any:
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return _coerce_nan(v)


def _coerce_value(raw: Any) -> Any:
    """Convert caproto values to JSON-friendly Python primitives.

    Handles three shapes caproto delivers:
    - Numeric scalars and waveforms as numpy arrays / numpy scalars
      (unboxed via .tolist()).
    - String scalars as bytes / 1-element DbrStringArray (decoded to str).
    - String waveforms as multi-element DbrStringArray (decoded to list[str]).

    Multi-element containers become Python lists; size-1 containers are
    unwrapped to scalars so scalar PVs flow as plain values.
    """
    if isinstance(raw, (bytes, bytearray)):
        return raw.decode("utf-8", errors="replace")

    if hasattr(raw, "tolist"):                      # numpy arrays / scalars
        value = raw.tolist()
    elif hasattr(raw, "__len__") and not isinstance(raw, str):
        value = list(raw)                           # caproto DbrStringArray, etc.
    else:
        return _coerce_nan(raw)

    if isinstance(value, list):
        cleaned = [_coerce_element(v) for v in value]
        return cleaned[0] if len(cleaned) == 1 else cleaned

    return _coerce_nan(value)


@router.websocket("/api/v1/pvs")
async def pvs_ws(websocket: WebSocket) -> None:
    """Per-connection WS handler.

    State machine: accept → receive subscribe messages → fan out updates
    until disconnect → tear down all subscriptions.
    """
    await websocket.accept()
    subscriptions: dict[str, asyncio.Task] = {}  # pv_name → forwarding task

    async with ClientContext() as client_ctx:
        async def _forward_pv(pv_name: str) -> None:
            """Subscribe to one PV and forward updates to this WS client."""
            try:
                # Use timeout on get_pvs to handle unknown PVs that would otherwise
                # block indefinitely waiting for the channel to appear on the network.
                (pv,) = await asyncio.wait_for(
                    client_ctx.get_pvs(pv_name), timeout=2.0
                )
            except (asyncio.TimeoutError, Exception) as exc:
                logger.warning("WS bridge: PV lookup failed for %s: %s", pv_name, exc)
                await websocket.send_text(
                    WSError(pv=pv_name, error=str(exc)).model_dump_json()
                )
                return

            try:
                initial = await asyncio.wait_for(pv.read(), timeout=2.0)
                await websocket.send_text(
                    WSValueUpdate(
                        pv=pv_name,
                        value=_coerce_value(initial.data),
                        ts=datetime.now(timezone.utc).isoformat(),
                    ).model_dump_json()
                )
            except asyncio.TimeoutError:
                await websocket.send_text(
                    WSError(pv=pv_name, error="initial read timeout").model_dump_json()
                )
                return
            except Exception as exc:
                await websocket.send_text(
                    WSError(pv=pv_name, error=f"read failed: {exc}").model_dump_json()
                )
                return

            sub = pv.subscribe(data_type="time")
            try:
                async for response in sub:
                    await websocket.send_text(
                        WSValueUpdate(
                            pv=pv_name,
                            value=_coerce_value(response.data),
                            ts=datetime.now(timezone.utc).isoformat(),
                        ).model_dump_json()
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("WS bridge forwarder for %s failed", pv_name)
            finally:
                try:
                    await sub.clear()
                except Exception:
                    pass

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = WSSubscribe.model_validate(json.loads(raw))
                except Exception as exc:
                    logger.warning("WS bridge: bad client message: %s", exc)
                    continue

                if msg.action == "subscribe":
                    for pv_name in msg.pvs:
                        if pv_name in subscriptions:
                            continue
                        task = asyncio.create_task(_forward_pv(pv_name))
                        subscriptions[pv_name] = task
                else:  # unsubscribe
                    for pv_name in msg.pvs:
                        task = subscriptions.pop(pv_name, None)
                        if task:
                            task.cancel()

        except WebSocketDisconnect:
            pass
        except Exception:
            logger.exception("WS bridge connection error")
        finally:
            for task in subscriptions.values():
                task.cancel()
            await asyncio.gather(*subscriptions.values(), return_exceptions=True)
