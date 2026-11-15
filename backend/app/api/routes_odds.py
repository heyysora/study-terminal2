"""Odds check for a practice plan (see app/backtest/odds.py). Free 5-minute bars only; nothing here can place an order."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..backtest.odds import data_symbol, default_start, odds_check
from ..market_data.hours import asset_kind
from ..market_data.providers.base import ProviderError
from ..market_data.types import Timeframe

router = APIRouter(prefix="/api", tags=["odds"])
CACHE_S = 900


class OddsIn(BaseModel):
    symbol: str
    direction: str              # long | short
    entry: float
    stop: float
    target: float
    start: str | None = None    # "HH:MM" New York time; default: now if the market is open, else 10:00
    flat_by: str | None = None  # "HH:MM" New York time; default: 15:55 for stocks, 4:10 PM for futures (Topstep's 3:10 PM CT)


async def _bars(request: Request, sym: str) -> list:
    st = request.app.state
    cache = getattr(st, "odds_bars", None) or {}
    hit = cache.get(sym)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    bars, _, _ = await st.monitor.bars(sym, Timeframe.M5, datetime.now(timezone.utc) - timedelta(days=60))
    cache[sym] = (time.monotonic(), bars)
    st.odds_bars = cache
    return bars


@router.post("/odds")
async def odds(body: OddsIn, request: Request):
    sym = data_symbol(body.symbol.strip())
    kind = asset_kind(sym)
    if kind == "crypto":
        raise HTTPException(400, "Crypto is watch-only here, so there's no practice plan to check.")
    futures = kind == "futures"
    flat = body.flat_by or ("16:10" if futures else getattr(request.app.state.paper.engine.risk, "flat_by", "15:55"))
    start, note = (body.start, None) if body.start else default_start(datetime.now(timezone.utc), "09:30", flat)
    try:
        bars = await _bars(request, sym)
    except ProviderError as e:
        raise HTTPException(502, f"Couldn't get price history for {sym}: {e}") from None
    try:
        res = await asyncio.to_thread(odds_check, bars, body.direction, body.entry, body.stop, body.target, start, flat)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    res["data"] = {"symbol": sym, "source": "Yahoo Finance 5-minute bars (free, unofficial, can be a little behind)"
                   + (f"; {sym} moves the same as {body.symbol.upper()}" if sym != body.symbol.upper() else "")}
    if note:
        res["notes"].insert(0, note)
    if futures:
        res["notes"].append("Futures plans are checked for the day session only (before the flat time), not overnight.")
    return res
