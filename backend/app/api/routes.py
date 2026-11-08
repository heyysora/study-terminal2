"""REST API: health, market data, watchlists, events, and the paper trading simulator."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, func, select, text

from ..db.models import AppEvent, Watchlist, WatchlistSymbol
from ..market_data.providers.base import ProviderError, ProviderRateLimited, SymbolNotFound
from ..market_data.service import MarketMonitor
from ..market_data.types import Timeframe
from ..paper.engine import OrderRequest, OrderStatus, position_size
from ..paper.service import PaperService

router = APIRouter(prefix="/api")
SYMBOL_RE = re.compile(r"^\^?[A-Z0-9][A-Z0-9.\-=]{0,14}$")  # AAPL, BRK-B, ^GSPC, BTC-USD, ES=F


def mon(request: Request) -> MarketMonitor:
    return request.app.state.monitor


def paper(request: Request) -> PaperService:
    return request.app.state.paper


def _sym(raw: str) -> str:
    s = raw.strip().upper()
    if not SYMBOL_RE.match(s):
        raise HTTPException(422, f"Invalid ticker symbol: {raw!r}")
    return s


def _provider_http(e: ProviderError) -> HTTPException:
    if isinstance(e, SymbolNotFound):
        return HTTPException(404, str(e))
    if isinstance(e, ProviderRateLimited):
        return HTTPException(429, str(e))
    return HTTPException(502, f"Market data provider error: {e}")


# ---------------- health ----------------

@router.get("/health")
def health(m: MarketMonitor = Depends(mon), p: PaperService = Depends(paper)):
    db_ok = True
    try:
        with m.db.session() as s:
            s.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "app": "Study Terminal",
        "brokerage_connected": False,
        "brokerage_required": False,
        "execution": "local paper simulator only",
        "database_ok": db_ok,
        "started_at": m.started_at.isoformat(),
        "market_data": m.status(),
        "paper_account": p.engine.summary(),
        "websocket_clients": m.broadcaster.subscriber_count,
    }


@router.get("/market/clock")
def market_clock(m: MarketMonitor = Depends(mon)):
    return m.clock.session_at().to_dict()


@router.get("/market/provider")
def provider_info(m: MarketMonitor = Depends(mon)):
    return m.provider.info.model_dump()


# ---------------- market data ----------------

@router.get("/market/live")
def live(m: MarketMonitor = Depends(mon)):
    """Every monitored symbol: latest price, freshness label, feed timeliness, and whether signals may use it."""
    return {"status": m.status(), "symbols": m.live_view()}


@router.get("/market/quote/{symbol}")
async def quote(symbol: str, m: MarketMonitor = Depends(mon)):
    sym = _sym(symbol)
    try:
        return await m.quote(sym)
    except ProviderError as e:
        raise _provider_http(e) from e


@router.get("/market/bars/{symbol}")
async def bars(symbol: str, timeframe: Timeframe = Timeframe.M5,
               days: int = Query(5, ge=1, le=10_000, description="Calendar days back"), m: MarketMonitor = Depends(mon)):
    sym = _sym(symbol)
    try:
        rows, notes, label = await m.bars(sym, timeframe, datetime.now(timezone.utc) - timedelta(days=days))
    except ProviderError as e:
        raise _provider_http(e) from e
    return {"symbol": sym, "timeframe": timeframe.value, "count": len(rows), "label": label.model_dump(mode="json"),
            "notes": notes, "bars": [b.model_dump(mode="json") for b in rows]}


# ---------------- watchlists ----------------

class WatchlistIn(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _n(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 64:
            raise ValueError("name must be 1-64 characters")
        return v


class SymbolsIn(BaseModel):
    symbols: list[str]


def _wl(w: Watchlist) -> dict:
    return {"id": w.id, "name": w.name, "symbols": [s.symbol for s in w.symbols]}


@router.get("/watchlists")
def list_watchlists(m: MarketMonitor = Depends(mon)):
    with m.db.session() as s:
        return [_wl(w) for w in s.scalars(select(Watchlist).order_by(Watchlist.id)).all()]


@router.post("/watchlists", status_code=201)
def create_watchlist(body: WatchlistIn, m: MarketMonitor = Depends(mon)):
    with m.db.session() as s:
        if s.scalar(select(Watchlist).where(Watchlist.name == body.name)):
            raise HTTPException(409, "A watchlist with that name already exists")
        w = Watchlist(name=body.name)
        s.add(w)
        s.flush()
        return _wl(w)


@router.delete("/watchlists/{wl_id}", status_code=204)
async def delete_watchlist(wl_id: int, m: MarketMonitor = Depends(mon)):
    with m.db.session() as s:
        w = s.get(Watchlist, wl_id)
        if not w:
            raise HTTPException(404, "Watchlist not found")
        s.delete(w)
    await m.refresh_symbols()


@router.post("/watchlists/{wl_id}/symbols")
async def add_symbols(wl_id: int, body: SymbolsIn, m: MarketMonitor = Depends(mon)):
    syms = [_sym(x) for x in body.symbols]
    with m.db.session() as s:
        w = s.get(Watchlist, wl_id)
        if not w:
            raise HTTPException(404, "Watchlist not found")
        have = {x.symbol for x in w.symbols}
        pos = (s.scalar(select(func.max(WatchlistSymbol.position)).where(WatchlistSymbol.watchlist_id == wl_id)) or 0) + 1
        for sym in syms:
            if sym not in have:
                s.add(WatchlistSymbol(watchlist_id=wl_id, symbol=sym, position=pos))
                have.add(sym)
                pos += 1
        s.flush()
        s.refresh(w)
        out = _wl(w)
    await m.refresh_symbols()
    out["monitoring"] = {"monitored": m.monitored_symbols(), "not_monitored_over_limit": m.over_limit()}
    return out


@router.delete("/watchlists/{wl_id}/symbols/{symbol}")
async def remove_symbol(wl_id: int, symbol: str, m: MarketMonitor = Depends(mon)):
    sym = _sym(symbol)
    with m.db.session() as s:
        res = s.execute(delete(WatchlistSymbol).where(WatchlistSymbol.watchlist_id == wl_id, WatchlistSymbol.symbol == sym))
        if res.rowcount == 0:
            raise HTTPException(404, "Symbol not in watchlist")
    await m.refresh_symbols()
    return {"removed": sym}


@router.get("/events")
def events(limit: int = Query(100, ge=1, le=1000), m: MarketMonitor = Depends(mon)):
    with m.db.session() as s:
        rows = s.scalars(select(AppEvent).order_by(AppEvent.id.desc()).limit(limit)).all()
        return [{"ts": r.ts.isoformat(), "level": r.level, "category": r.category, "message": r.message} for r in rows]


# ---------------- paper trading (local simulator) ----------------

class PlaceOrderIn(OrderRequest):
    confirm: bool = False  # must be true: every order is an explicit user action


class ResetIn(BaseModel):
    confirm: bool = False
    starting_cash: float | None = None


@router.get("/paper/account")
def paper_account(p: PaperService = Depends(paper)):
    return p.engine.summary()


@router.get("/paper/positions")
def paper_positions(p: PaperService = Depends(paper)):
    return p.positions()


@router.get("/paper/orders")
def paper_orders(status: OrderStatus | None = None, limit: int = Query(200, ge=1, le=5000), p: PaperService = Depends(paper)):
    orders = sorted(p.engine.orders.values(), key=lambda o: o.created_at, reverse=True)
    if status:
        orders = [o for o in orders if o.status == status]
    return [o.to_dict() for o in orders[:limit]]


@router.get("/paper/fills")
def paper_fills(limit: int = Query(200, ge=1, le=5000), p: PaperService = Depends(paper)):
    return [f.to_dict() for f in sorted(p.engine.fills, key=lambda f: f.ts, reverse=True)[:limit]]


@router.get("/paper/size")
def paper_size(entry: float = Query(..., gt=0), stop: float = Query(..., gt=0), risk_pct: float | None = Query(None, gt=0, le=100),
               p: PaperService = Depends(paper)):
    """Position size calculator: shares so that hitting the stop loses risk_pct% of equity."""
    pct = risk_pct or p.risk.max_per_trade_pct
    eq = p.engine.equity()
    qty = position_size(eq, pct, entry, stop)
    return {"equity": round(eq, 2), "risk_pct": pct, "risk_dollars": round(eq * pct / 100, 2),
            "risk_per_share": round(abs(entry - stop), 4), "shares": qty, "notional": round(qty * entry, 2)}


@router.post("/paper/orders/preview")
async def paper_preview(body: OrderRequest, p: PaperService = Depends(paper)):
    _sym(body.symbol)
    return await p.preview(body)


@router.post("/paper/orders", status_code=201)
async def paper_place(body: PlaceOrderIn, request: Request, p: PaperService = Depends(paper)):
    _sym(body.symbol)
    if not body.confirm:
        raise HTTPException(400, "Orders need explicit confirmation: resend with \"confirm\": true after reviewing the preview.")
    req = OrderRequest(**body.model_dump(exclude={"confirm"}))
    journal = getattr(request.app.state, "journal", None)
    ctx = journal.capture_context(req.symbol, req.signal_id) if journal else None
    res = await p.submit(req, context=ctx)
    if journal:
        journal.sync()
    if res["order"]["status"] == "rejected":
        raise HTTPException(422, {"message": res["order"]["reject_reason"], **res})
    return res


@router.delete("/paper/orders/{order_id}")
async def paper_cancel(order_id: str, p: PaperService = Depends(paper)):
    try:
        return await p.cancel(order_id)
    except KeyError:
        raise HTTPException(404, "Order not found")
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/paper/positions/{symbol}/close")
async def paper_close(symbol: str, confirm: bool = False, p: PaperService = Depends(paper)):
    if not confirm:
        raise HTTPException(400, "Closing needs explicit confirmation: add ?confirm=true")
    try:
        res = await p.close_position(_sym(symbol))
    except KeyError:
        raise HTTPException(404, "No open position in that symbol")
    if res["order"]["status"] == "rejected":
        raise HTTPException(422, {"message": res["order"]["reject_reason"], **res})
    return res


@router.post("/paper/reset")
async def paper_reset(body: ResetIn, p: PaperService = Depends(paper)):
    if not body.confirm:
        raise HTTPException(400, "Reset erases all paper positions, orders and history. Resend with \"confirm\": true.")
    return await p.reset(body.starting_cash)
