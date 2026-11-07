"""WebSocket push channel for the desktop UI: ticks, bars, freshness, connection, events, paper orders/fills."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
log = logging.getLogger(__name__)


@router.websocket("/ws/market")
async def market_ws(ws: WebSocket):
    settings = ws.app.state.settings
    origin = ws.headers.get("origin")
    # Browsers always send Origin. Reject web pages that aren't our UI so a random
    # website can't read your market stream from localhost. Non-browser clients
    # (the CLI, tests) send no Origin and are allowed - the server binds to 127.0.0.1.
    host = ws.headers.get("host", "")
    same_origin = origin in (f"http://{host}", f"https://{host}")  # the UI served by this backend itself
    if origin and not same_origin and origin not in settings.allowed_origins:
        await ws.close(code=1008)
        return

    await ws.accept()
    monitor = ws.app.state.monitor
    paper = ws.app.state.paper
    q = monitor.broadcaster.subscribe()
    try:
        await ws.send_text(json.dumps({"type": "hello", "data": {"status": monitor.status(), "symbols": monitor.live_view(),
                                                                 "paper_account": paper.engine.summary()}}, default=str))
        while True:
            event = await q.get()
            await ws.send_text(json.dumps(event, default=str))
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        log.exception("websocket client error")
    finally:
        monitor.broadcaster.unsubscribe(q)
