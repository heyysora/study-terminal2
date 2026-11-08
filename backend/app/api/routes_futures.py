"""Futures API: contracts, sessions, levels, signals, prop-firm risk, the futures simulator, replay, backtests.
Simulator only: nothing here can reach a broker or TopstepX order endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..market_data.types import Timeframe

router = APIRouter(prefix="/api/futures", tags=["futures"])


def _f(request: Request):
    return request.app.state.futures


def _err(e: Exception):
    if isinstance(e, KeyError):
        raise HTTPException(404, str(e.args[0]) if e.args else str(e))
    if isinstance(e, PermissionError):
        raise HTTPException(403, str(e))
    if isinstance(e, (ValueError, RuntimeError)):
        raise HTTPException(400, str(e))
    raise e


@router.get("/info")
def info(request: Request):
    return _f(request).info()


@router.get("/contract/{root}")
def contract(root: str, request: Request):
    try:
        return _f(request).contract_info(root)
    except Exception as e:  # noqa: BLE001
        _err(e)


@router.get("/parse")
def parse(symbol: str):
    from ..futures.contracts import parse_symbol

    p = parse_symbol(symbol)
    return p.to_dict() if p else {"root": None, "note": "Not a recognized futures symbol."}


@router.get("/analysis/{symbol}")
async def analysis(symbol: str, request: Request, timeframe: Literal["1Min", "5Min", "15Min"] = "5Min"):
    try:
        return await _f(request).analysis(symbol, Timeframe(timeframe))
    except Exception as e:  # noqa: BLE001
        _err(e)


@router.get("/dashboard")
async def dashboard(request: Request, symbol: str | None = None):
    try:
        return await _f(request).dashboard(symbol)
    except Exception as e:  # noqa: BLE001
        _err(e)


# ---------------- risk profile ----------------

class PropIn(BaseModel):
    values: dict = Field(default_factory=dict)
    confirm: bool = False


@router.put("/risk/prop")
def set_prop(body: PropIn, request: Request):
    f = _f(request)
    out = f.set_prop(body.values, body.confirm)
    f.apply()
    return out


class PresetIn(BaseModel):
    preset_id: str


@router.post("/risk/preset")
def preset(body: PresetIn, request: Request):
    f = _f(request)
    try:
        out = f.use_preset(body.preset_id)
    except Exception as e:  # noqa: BLE001
        _err(e)
    f.apply()
    return out


@router.put("/risk/personal")
def set_personal(body: dict, request: Request):
    from ..futures.risk import PersonalRisk

    f = _f(request)
    p = PersonalRisk.from_dict({**f.personal().to_dict(), **body})
    f.store.update({"futures.personal": p.to_dict()})
    f.apply()
    return p.to_dict()


@router.get("/risk")
def risk(request: Request):
    return _f(request).account()["risk"]


class ReviewIn(BaseModel):
    note: str = Field(min_length=10, max_length=2000)


@router.post("/risk/review")
def review(body: ReviewIn, request: Request):
    try:
        return _f(request).review(body.note)
    except Exception as e:  # noqa: BLE001
        _err(e)


# ---------------- simulator ----------------

class BracketTarget(BaseModel):
    price: float
    qty: int = Field(ge=1)


class Bracket(BaseModel):
    stop: float | None = None
    targets: list[BracketTarget] = Field(default_factory=list)


class OrderIn(BaseModel):
    contract: str
    side: Literal[1, -1]
    qty: int = Field(ge=1, le=500)
    type: Literal["market", "limit", "stop"] = "market"
    limit_price: float | None = None
    stop_price: float | None = None
    bracket: Bracket | None = None
    confirm: bool = False
    signal_id: str | None = None


def _order_dict(body: OrderIn) -> dict:
    d = body.model_dump()
    if body.bracket:
        d["bracket"] = {"stop": body.bracket.stop, "targets": [t.model_dump() for t in body.bracket.targets]}
    return d


@router.get("/paper")
def paper(request: Request):
    return _f(request).account()


@router.post("/paper/preview")
async def paper_preview(body: OrderIn, request: Request):
    try:
        return await _f(request).preview(_order_dict(body))
    except Exception as e:  # noqa: BLE001
        _err(e)


@router.post("/paper/orders")
async def paper_submit(body: OrderIn, request: Request):
    try:
        return await _f(request).submit(_order_dict(body))
    except Exception as e:  # noqa: BLE001
        _err(e)


@router.delete("/paper/orders/{oid}")
def paper_cancel(oid: str, request: Request):
    try:
        return _f(request).cancel(oid)
    except Exception as e:  # noqa: BLE001
        _err(e)


class FlattenIn(BaseModel):
    contract: str | None = None


@router.post("/paper/flatten")
async def paper_flatten(body: FlattenIn, request: Request):
    try:
        return await _f(request).flatten(body.contract)
    except Exception as e:  # noqa: BLE001
        _err(e)


class ResetIn(BaseModel):
    confirm: bool = False
    starting_balance: float | None = Field(default=None, ge=0)


@router.post("/paper/reset")
def paper_reset(body: ResetIn, request: Request):
    if not body.confirm:
        raise HTTPException(400, "Confirm the reset: it erases the simulated futures account's history.")
    return _f(request).reset(body.starting_balance)


@router.get("/journal")
def journal(request: Request):
    return _f(request).journal()


# ---------------- backtest ----------------

class BacktestIn(BaseModel):
    root: str
    days: int = Field(59, ge=10, le=59)


@router.post("/backtest")
async def backtest(body: BacktestIn, request: Request):
    try:
        return await _f(request).backtest(body.root, body.days)
    except Exception as e:  # noqa: BLE001
        _err(e)


# ---------------- replay ----------------

class ReplayIn(BaseModel):
    symbol: str
    trade_date: str


@router.post("/replay/start")
async def replay_start(body: ReplayIn, request: Request):
    try:
        return await _f(request).replay_start(body.symbol, body.trade_date)
    except Exception as e:  # noqa: BLE001
        _err(e)


class StepIn(BaseModel):
    bars: int = Field(1, ge=0, le=500)


@router.post("/replay/step")
async def replay_step(body: StepIn, request: Request):
    try:
        return await _f(request).replay_step(body.bars)
    except Exception as e:  # noqa: BLE001
        _err(e)


@router.post("/replay/orders")
def replay_order(body: OrderIn, request: Request):
    try:
        return _f(request).replay_order(_order_dict(body))
    except Exception as e:  # noqa: BLE001
        _err(e)


@router.post("/replay/flatten")
def replay_flatten(request: Request):
    try:
        return _f(request).replay_flatten()
    except Exception as e:  # noqa: BLE001
        _err(e)


@router.get("/projectx/check")
async def projectx_check(request: Request):
    f = _f(request)
    if not f.projectx:
        return {"ok": False, "detail": "Not configured. Add STUDY_PROJECTX_USERNAME and STUDY_PROJECTX_API_KEY to your .env file, then restart."}
    return await f.projectx.check()


@router.get("/projectx/accounts")
async def projectx_accounts(request: Request):
    f = _f(request)
    if not f.projectx:
        raise HTTPException(400, "The TopstepX API isn't configured.")
    if not f.store.get("futures.projectx_read_account", False):
        raise HTTPException(403, "Reading your TopstepX account is off. Turn it on in Settings > Futures data first.")
    try:
        accts = await f.projectx.accounts()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, str(e)) from e
    return {"accounts": accts, "note": "Read-only balances from TopstepX. Study Terminal can't place or change anything on these accounts."}


@router.get("/decisions")
def decisions(request: Request, contract: str | None = None, outcome: str | None = None, limit: int = 100):
    """Stored decision-pipeline results, newest first, with every step's reasoning."""
    return {"decisions": _f(request).decisions(contract, outcome, limit)}
