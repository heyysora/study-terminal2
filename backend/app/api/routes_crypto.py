"""Live crypto prices to WATCH (public exchange data, read-only). Crypto can't be practised or traded here."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/crypto", tags=["crypto"])


@router.get("/markets")
async def markets(request: Request):
    return await request.app.state.crypto.tickers()


@router.get("/price/{symbol}")
async def price(symbol: str, request: Request):
    r = await request.app.state.crypto.price(symbol)
    if not r:
        raise HTTPException(404, "No live exchange price for that symbol.")
    return r


@router.get("/lock-check")
async def lock_check():
    """Proof that the exchange library can only read public prices."""
    import asyncio

    from ..market_data.exchanges import lock_check as check
    return await asyncio.to_thread(check)
