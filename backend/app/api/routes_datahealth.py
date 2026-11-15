"""Data Health: what Study Terminal has checked about its own data, in plain words and in full. Read-only apart from 'check now'."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/datahealth", tags=["datahealth"])


def _dh(request: Request):
    dh = getattr(request.app.state, "datahealth", None)
    if dh is None:
        raise HTTPException(503, "Data checks aren't available.")
    return dh


def _safety(request: Request) -> dict | None:
    sc = getattr(request.app.state, "safety", None)
    return sc.status() if sc else None


@router.get("")
def summary(request: Request):
    return {**_dh(request).summary(), "safety": _safety(request)}


@router.get("/report")
def report(request: Request):
    return {**_dh(request).report(), "safety": _safety(request)}


@router.post("/run")
async def run(request: Request):
    """Check every source now (it also happens by itself in the background)."""
    return {**await _dh(request).run_all(), "safety": _safety(request)}


@router.get("/history/{source}")
def history(source: str, request: Request):
    return {"source": source, "history": _dh(request).history(source, 500)}


@router.get("/chart")
def chart(request: Request):
    dh = _dh(request)
    if not dh.chartwatch:
        raise HTTPException(404, "Chart validation isn't available.")
    return dh.chartwatch.summary()
