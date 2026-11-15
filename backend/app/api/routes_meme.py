"""Memecoins: watch (DexScreener, Solana public data), rug-risk checks, and a PRACTICE account. Nothing here can trade for real."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..memecoins.sources import SourceError

router = APIRouter(prefix="/api/meme", tags=["memecoins"])
ADDR = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")     # Solana base58 address


def _m(request: Request):
    return request.app.state.meme


def _addr(a: str) -> str:
    a = a.strip()
    if not ADDR.match(a):
        raise HTTPException(422, "That doesn't look like a Solana token address.")
    return a


@router.get("/feed")
async def feed(request: Request, kind: str = "profiles"):
    try:
        return await _m(request).feed("boosts" if kind == "boosts" else "profiles")
    except SourceError as e:
        raise HTTPException(502, str(e)) from None


@router.get("/search")
async def search(request: Request, q: str):
    if ADDR.match(q.strip()):
        return {"rows": [], "address": q.strip()}
    try:
        return {"rows": await _m(request).search(q)}
    except SourceError as e:
        raise HTTPException(502, str(e)) from None


@router.get("/token/{address}")
async def token(address: str, request: Request):
    try:
        out = await _m(request).token(_addr(address))
    except SourceError as e:
        raise HTTPException(502, str(e)) from None
    out.pop("raw_pair", None)
    return out


@router.get("/practice")
async def practice(request: Request):
    m = _m(request)
    try:
        pairs = await m.pairs_for_positions()
    except SourceError:
        pairs = {}
    return {**m.practice.summary(pairs), "history": m.practice.fills(50)}


class BuyIn(BaseModel):
    token: str
    usd: float
    stop_pct: float
    target_pct: float | None = None
    take_fraction: float = 1.0          # share sold at the target (1 = all)
    trail_pct: float | None = None      # trailing stop, % under the highest price
    confirm: bool = False


async def _pair(request: Request, token: str) -> dict:
    try:
        pair = (await _m(request).data.pairs_for([token], ttl=5)).get(token)
    except SourceError as e:
        raise HTTPException(502, str(e)) from None
    if not pair:
        raise HTTPException(404, "This token has no trading pool on DexScreener right now.")
    return pair


@router.post("/practice/preview")
async def preview(body: BuyIn, request: Request):
    pair = await _pair(request, _addr(body.token))
    return _m(request).practice.preview_buy(pair, body.usd, body.stop_pct, body.target_pct, body.take_fraction, body.trail_pct)


@router.post("/practice/buy")
async def buy(body: BuyIn, request: Request):
    if not body.confirm:
        raise HTTPException(400, "Please confirm first.")
    pair = await _pair(request, _addr(body.token))
    r = _m(request).practice.buy(pair, body.usd, body.stop_pct, body.target_pct, take_fraction=body.take_fraction, trail_pct=body.trail_pct)
    if not r.get("ok"):
        raise HTTPException(409, " ".join(r.get("errors") or ["Not allowed."]))
    return r


class SellIn(BaseModel):
    token: str
    fraction: float = 1.0


@router.post("/practice/sell")
async def sell(body: SellIn, request: Request):
    pair = await _pair(request, _addr(body.token))
    r = _m(request).practice.sell(pair, body.token, body.fraction)
    if not r.get("ok"):
        raise HTTPException(409, " ".join(r.get("errors") or ["Not allowed."]))
    return r


@router.get("/journal")
async def journal(request: Request):
    return _m(request).practice.journal()


class NoteIn(BaseModel):
    token: str
    why: str | None = None
    lesson: str | None = None


@router.post("/journal/note")
async def note(body: NoteIn, request: Request):
    return _m(request).practice.set_note(_addr(body.token), body.why, body.lesson)
