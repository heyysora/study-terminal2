"""Journal API (Stage 11): signal log, trades, notes, performance and mistakes."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/journal", tags=["journal"])


def _j(request: Request):
    return request.app.state.journal


def _filters(start, end, symbol, strategy, direction, mistake, followed, status) -> dict:
    return {"start": start, "end": end, "symbol": symbol, "strategy": strategy, "direction": direction, "mistake": mistake,
            "followed": followed, "status": status}


@router.get("/trades")
def trades(request: Request, start: date | None = None, end: date | None = None, symbol: str | None = None,
           strategy: str | None = None, direction: str | None = Query(None, pattern="^(long|short)$"),
           mistake: str | None = None, followed: bool | None = None, status: str | None = Query(None, pattern="^(open|closed)$")):
    return _j(request).trades(**_filters(start, end, symbol, strategy, direction, mistake, followed, status))


@router.get("/trades/{key}")
def trade(key: str, request: Request):
    t = _j(request).trade(key)
    if t is None:
        raise HTTPException(404, "No such trade")
    return t


class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@router.post("/trades/{key}/notes", status_code=201)
def add_note(key: str, body: NoteIn, request: Request):
    try:
        return _j(request).add_note(key, body.text)
    except KeyError:
        raise HTTPException(404, "No such trade") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, request: Request):
    try:
        _j(request).delete_note(note_id)
    except KeyError:
        raise HTTPException(404, "No such note") from None


class MetaIn(BaseModel):
    tags: list[str] | None = None
    followed_plan: bool | None = None
    clear_followed_plan: bool = False   # true = go back to the automatic verdict


@router.patch("/trades/{key}")
def set_meta(key: str, body: MetaIn, request: Request):
    fp = None if body.clear_followed_plan else (body.followed_plan if body.followed_plan is not None else "unchanged")
    try:
        _j(request).set_meta(key, tags=body.tags, followed_plan=fp)
    except KeyError:
        raise HTTPException(404, "No such trade") from None
    return _j(request).trade(key)


@router.get("/performance")
def perf(request: Request, start: date | None = None, end: date | None = None, symbol: str | None = None,
         strategy: str | None = None, direction: str | None = Query(None, pattern="^(long|short)$"),
         mistake: str | None = None, followed: bool | None = None):
    return _j(request).performance(**_filters(start, end, symbol, strategy, direction, mistake, followed, None))


@router.get("/signals")
def signals(request: Request, symbol: str | None = None, setup: str | None = None, action: str | None = None,
            start: date | None = None, end: date | None = None, limit: int = Query(300, ge=1, le=5000)):
    return _j(request).signals(symbol=symbol, setup=setup, action=action, start=start, end=end, limit=limit)
