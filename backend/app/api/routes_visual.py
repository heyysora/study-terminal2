"""Visual Market Monitor API: pick a chart window, preview it, save chart profiles, test a reading, start/stop monitoring.
Screen capture only; frames are kept in memory for the request and never stored. Nothing here can click, type or send orders."""
from __future__ import annotations

import asyncio
import json

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from ..screen import capture as cap
from ..screen import vision
from ..screen.chart_profile import ChartProfile
from ..screen.platforms import topstepx_title
from ..screen.vision import is_browser, title_looks_like_trading

router = APIRouter(prefix="/api/visual", tags=["visual"])


def _v(request: Request):
    return request.app.state.visual


def _privacy_check(title: str | None, process: str | None) -> None:
    if is_browser(process) and not title_looks_like_trading(title or "", process):
        raise HTTPException(403, "That browser window isn't showing a chart right now (privacy: nothing captured). Switch it to "
                                 "your TopstepX chart tab and try again.")


def _grab(request: Request, hwnd: int, method: str = "auto") -> tuple[np.ndarray, str, str | None, str]:
    title = cap.window_title(hwnd) if cap.IS_WIN else None
    targets = {int(t["id"]): t for t in cap.list_targets() if t.get("kind") == "window"}
    t = targets.get(hwnd)
    if t is None:
        raise HTTPException(404, "That window isn't open anymore.")
    title = title or t.get("title")
    _privacy_check(title, t.get("process"))
    res = _v(request).capture_manager.capture(hwnd, method)
    if res.frame is None:
        raise HTTPException(409, "Capture failed: " + "; ".join(f"{x['method']}: {x['error']}" for x in res.tried))
    return res.frame, title or "", t.get("process"), res.method


def edge_first(targets: list[dict]) -> dict:
    """Windows only (no whole screens), Microsoft Edge windows first, TopstepX-looking ones on top."""
    out = []
    for t in targets:
        if t.get("kind") != "window":
            continue
        out.append({**t, "is_edge": (t.get("process") or "").lower() == "msedge.exe",
                    "looks_like_topstepx": "topstep" in (t.get("title") or "").lower() or topstepx_title(t.get("title")) is not None})
    out.sort(key=lambda x: (not (x["is_edge"] and x["looks_like_topstepx"]), not x["is_edge"], not x["looks_like_topstepx"], x.get("title") or ""))
    return {"windows": out}


@router.get("/windows")
def windows():
    """Open windows (Windows only) with a hint for the ones that look like TopstepX."""
    from ..screen.capture_sources import wgc_available
    return {**edge_first(cap.list_targets()), "window_capture_supported": cap.IS_WIN, "wgc_available": wgc_available(),
            "note": None if cap.IS_WIN else "Window capture needs Windows. You can still set up and test a profile with a saved screenshot."}


@router.get("/preview")
async def preview(request: Request, hwnd: int, max_width: int = 1400, method: str = "auto"):
    """A fresh capture of the window as PNG (scaled down for display). Not stored. X-Capture-Method says which source worked."""
    if method not in ("auto", "wgc", "printwindow", "screen"):
        raise HTTPException(422, "Unknown capture method")
    frame, _, _, used = await asyncio.to_thread(_grab, request, hwnd, method)
    h, w = frame.shape[:2]
    scale = min(1.0, max_width / w)
    img = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else frame
    ok, png = cv2.imencode(".png", img)
    return Response(png.tobytes(), media_type="image/png",
                    headers={"X-Window-Width": str(w), "X-Window-Height": str(h), "X-Scale": f"{scale:.6f}", "X-Capture-Method": used,
                             "Cache-Control": "no-store"})


@router.get("/region-preview/{pid}")
def region_preview(pid: str, request: Request):
    """The newest captured chart region of a monitored profile (JPEG, from memory; nothing is stored)."""
    rt = _v(request).runtimes.get(pid)
    if rt is None or rt.last_img is None:
        raise HTTPException(404, "No capture yet for this chart.")
    ok, jpg = cv2.imencode(".jpg", rt.last_img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(jpg.tobytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "X-Captured-At": rt.last_capture_at.isoformat() if rt.last_capture_at else ""})


@router.get("/profiles")
def profiles(request: Request):
    return {"profiles": [p.to_dict() for p in _v(request).store.all()]}


@router.post("/profiles")
def save_profile(body: dict, request: Request):
    try:
        p = _v(request).store.save(ChartProfile.from_dict(body))
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e)) from e
    _v(request)._sync_profiles()
    return p.to_dict()


@router.delete("/profiles/{pid}")
def delete_profile(pid: str, request: Request):
    ok = _v(request).store.delete(pid)
    _v(request)._sync_profiles()
    if not ok:
        raise HTTPException(404, "No such profile.")
    return {"deleted": pid}


class TestIn(BaseModel):
    profile: dict
    hwnd: int


@router.post("/test-read")
async def test_read(body: TestIn, request: Request):
    """Read the chart once with this (unsaved) profile, so you can check the setup before monitoring."""
    try:
        prof = ChartProfile.from_dict(body.profile)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e)) from e
    frame, title, _, used = await asyncio.to_thread(_grab, request, body.hwnd, prof.capture_method)
    try:
        return {**await _v(request).read_once(prof, frame, title), "capture_method": used}
    except vision.OcrUnavailable as e:
        # Not a bad profile and not a bad chart: the text reader itself won't start. Say so, with the repair.
        raise HTTPException(503, {"message": f"The part of Study Terminal that reads text off your screen isn't working. {e.advice}".strip(),
                                  "error": e.detail, "kind": "ocr_unavailable"}) from None


@router.post("/upload-read")
async def upload_read(request: Request, file: UploadFile = File(...), profile: str = Form("{}")):
    """Read a saved screenshot with a profile (any OS; for setup and calibration). The image isn't stored."""
    data = await file.read()
    if len(data) > 25_000_000:
        raise HTTPException(413, "Image too large")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(422, "Not an image")
    try:
        prof = ChartProfile.from_dict(json.loads(profile or "{}"))
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        raise HTTPException(422, str(e)) from e
    try:
        return await _v(request).read_once(prof, img)
    except vision.OcrUnavailable as e:
        raise HTTPException(503, {"message": f"The part of Study Terminal that reads text off your screen isn't working. {e.advice}".strip(),
                                  "error": e.detail, "kind": "ocr_unavailable"}) from None


@router.get("/ocr-check")
async def ocr_check(refresh: bool = False):
    """Is the part that reads text off the screen actually working? Checks the library, the modules it loads by name
    at run time, the model files, that the engine starts, and that it can read known text out of a picture.
    This is what the Health page's button calls, and what CI runs inside the built .exe before a release goes out."""
    from ..screen import ocr_health
    return await asyncio.to_thread(ocr_health.summary, refresh)


@router.get("/status")
def status(request: Request):
    return _v(request).status()


@router.post("/{action}")
async def control(action: str, request: Request):
    v = _v(request)
    try:
        if action == "start":
            return await v.start()
        if action == "pause":
            return v.pause()
        if action == "resume":
            return await v.resume()
        if action == "stop":
            return await v.stop()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    raise HTTPException(404, "Unknown action")


# ---------------- live price (fast price-box reads + a tape of accepted prices) ----------------

RANGES = {"live": 5 * 60, "1h": 3600, "4h": 4 * 3600, "day": None}


@router.get("/live")
def live_default(request: Request, range: str = "day"):  # noqa: A002 - query name shown in the URL
    v = _v(request)
    v._sync_profiles()
    if not v.runtimes:
        return {"profile": None, "reason": "No chart is connected yet."}
    pid = next((p for p, rt in v.runtimes.items() if rt.status == "screen_capture"), next(iter(v.runtimes)))
    return live_view(pid, request, range)


@router.get("/live/{pid}")
def live_view(pid: str, request: Request, range: str = "day"):  # noqa: A002
    import time as _t
    from datetime import datetime, timezone

    from ..plain import plain_reason, plain_status
    from ..screen.live_price import session_start
    v = _v(request)
    v._sync_profiles()
    rt = v.runtimes.get(pid)
    if rt is None:
        raise HTTPException(404, "No such chart profile.")
    now = datetime.now(timezone.utc)
    tape = rt.tape
    sess = session_start(now).timestamp()
    span = RANGES.get(range, None)
    since = sess if span is None else _t.time() - span
    series = tape.series(since) if tape else []
    ref_t, ref_p = tape.session_reference(now) if tape else (None, None)
    last = tape.last() if tape else None
    live = rt.status == "screen_capture"
    r = rt.reading
    contract = None
    if rt.recommendation:
        contract = rt.recommendation.get("contract")
    if not contract and r is not None and r.instrument.value:
        contract = r.instrument.value
    price = last[1] if last else None
    age = (_t.time() - last[0]) if last else None
    ps = plain_status(rt.status)
    candles = []
    for b in (rt.bars or [])[-120:]:
        t = b.get("time") or b.get("ts")
        if hasattr(t, "timestamp"):
            t = t.timestamp()
        if isinstance(t, str):
            try:
                t = datetime.fromisoformat(t).timestamp()
            except ValueError:
                continue
        if t is None:
            continue
        candles.append({"time": int(t), "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"]})
    return {
        "profile": {"id": pid, "name": rt.profile.name}, "contract": contract or rt.profile.root,
        "timeframe": (r.timeframe.value if r is not None else None) or rt.profile.timeframe,
        "status": rt.status, "status_word": ps["word"], "status_level": ps["level"], "live": live and price is not None and (age or 99) < max(
            30.0, float(rt.profile.stale_seconds)),
        "reason": None if live else plain_reason(f"{rt.status.upper()}: {rt.reason}"),
        "price": price, "at": datetime.fromtimestamp(last[0], timezone.utc).isoformat() if last else None,
        "age_seconds": None if age is None else round(age, 1), "method": last[2] if last else None,
        "bid": r.bid.value if (r is not None and live) else None, "ask": r.ask.value if (r is not None and live) else None,
        "change": None if (price is None or ref_p is None) else round(price - ref_p, 6),
        "change_pct": None if (price is None or not ref_p) else round((price - ref_p) / ref_p * 100, 3),
        "reference": None if ref_p is None else {"price": ref_p, "at": datetime.fromtimestamp(ref_t, timezone.utc).isoformat(),
                                                 "session_start": datetime.fromtimestamp(sess, timezone.utc).isoformat(),
                                                 "from_session_open": ref_t - sess < 180},
        "range": range if range in RANGES else "day", "series": series,
        "candles": candles, "candles_note": "Candles are worked out from the picture of your chart (estimated); the line is the "
                                            "price read from the chart's price box.",
        "checks": {"accepted": tape.accepted if tape else 0, "rejected": tape.rejected if tape else 0,
                   "last_reject": tape.last_reject if tape else "",
                   "rule": "A price is used only if it is on the contract's price steps, matches where it sits on the price scale, and "
                           "isn't a sudden jump that the next read doesn't confirm."},
        "source": "Read from your TopstepX chart on screen. It shows what the chart shows; it is not an official exchange feed.",
        "live_seconds": rt.profile.live_seconds,
    }
