"""News, catalysts and the economic calendar."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(prefix="/api", tags=["news"])
_SYM = r"^[A-Za-z0-9.\-^=]{1,15}$"


@router.get("/news/{symbol}")
async def catalysts(request: Request, symbol: str, refresh: bool = False):
    import re
    if not re.match(_SYM, symbol):
        raise HTTPException(400, "Bad symbol")
    return await request.app.state.news.catalysts(symbol, force=refresh)


@router.get("/news")
def history(request: Request, symbol: str | None = None, limit: int = Query(200, ge=1, le=2000)):
    return request.app.state.news.history(symbol, limit)


@router.get("/calendar")
async def calendar(request: Request, days: int = Query(14, ge=1, le=120), refresh: bool = False):
    n = request.app.state.news
    m = await n.macro(force=refresh)
    econ = await n.econ_values(force=refresh)
    return {"events": n.upcoming(days), "published_values": econ, "errors": m["errors"], "bls": m["bls"], "fetched_at": m["fetched_at"],
            "now": n.event_risk(None),
            "note": "Official schedules: Federal Reserve and BEA pages are read live; BLS dates are bundled (BLS blocks automated downloads)."}
