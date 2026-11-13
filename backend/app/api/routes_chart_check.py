"""Chart check: guided real-chart testing (see app/validation/chart_check.py)."""
from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/chart-check", tags=["chart-check"])


def _c(request: Request):
    return request.app.state.chart_check


def _err(e: Exception):
    raise HTTPException(404 if isinstance(e, KeyError) else 400, str(e).strip("'\"")) from e


@router.get("")
def summary(request: Request):
    return _c(request).summary()


@router.get("/results")
def results(request: Request):
    return {"results": _c(request).results()[::-1]}


class SampleIn(BaseModel):
    step: str
    profile: str | None = None


@router.post("/sample")
def sample(body: SampleIn, request: Request):
    try:
        return _c(request).sample(body.step, body.profile)
    except (ValueError, KeyError) as e:
        _err(e)


class AnswerIn(BaseModel):
    sample: str
    matches: bool | None = None
    actual: dict | None = None
    note: str = ""


@router.post("/answer")
def answer(body: AnswerIn, request: Request):
    try:
        return _c(request).answer(body.sample, body.matches, body.actual, body.note)
    except (ValueError, KeyError) as e:
        _err(e)


class WatchIn(BaseModel):
    step: str | None = None
    phase: str | None = None
    note: str = ""
    price_still_right: bool | None = None


@router.get("/watch")
def watch(request: Request):
    return {"watch": _c(request).watch_state()}


@router.post("/watch/{action}")
def watch_action(action: str, body: WatchIn, request: Request):
    c = _c(request)
    try:
        if action == "start":
            return {"watch": c.watch_start(body.step or "")}
        if action == "phase":
            if body.phase not in ("did", "undid"):
                raise ValueError("phase must be 'did' or 'undid'")
            return {"watch": c.watch_phase(body.phase)}
        if action == "finish":
            return {"result": c.watch_finish(body.note, body.price_still_right)}
        if action == "cancel":
            c.watch = None
            return {"watch": None}
    except (ValueError, KeyError) as e:
        _err(e)
    raise HTTPException(404, "Unknown action.")


class ManualIn(BaseModel):
    step: str
    answers: dict
    note: str = ""


@router.post("/manual")
def manual(body: ManualIn, request: Request):
    try:
        return _c(request).manual(body.step, body.answers, body.note)
    except ValueError as e:
        _err(e)


@router.get("/image/{name}")
def image(name: str, request: Request):
    if not re.fullmatch(r"[0-9a-f]{12}\.jpg", name):
        raise HTTPException(404, "No such picture.")
    p = _c(request).dir / name
    if not p.exists():
        raise HTTPException(404, "No such picture.")
    return FileResponse(p, media_type="image/jpeg")
