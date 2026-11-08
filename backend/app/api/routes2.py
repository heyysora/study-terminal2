"""API for Stages 2-10: analysis, signals, scanner, backtests/ML, alerts, AI, learning, screen, settings, desktop."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel

from ..market_data.providers.base import ProviderError
from ..market_data.types import Timeframe
from .routes import _provider_http, _sym

router = APIRouter(prefix="/api")


def st(request: Request):
    return request.app.state


# ---------------- analysis & signals ----------------

@router.get("/analysis/{symbol}")
async def analysis(symbol: str, request: Request, timeframes: str = "5Min,15Min,1Hour", chart: Timeframe | None = None,
                   extended: bool = False):
    s = st(request)
    try:
        tfs = [Timeframe(t) for t in timeframes.split(",") if t]
    except ValueError as e:
        raise HTTPException(422, str(e))
    try:
        out = await s.analysis.analyze(_sym(symbol), tfs, chart or tfs[0], extended)
    except ProviderError as e:
        raise _provider_http(e) from e
    out["data_label"] = s.monitor.label(_sym(symbol)).model_dump(mode="json")
    return out


@router.get("/signals")
def signals_all(request: Request):
    s = st(request)
    return {"market": s.signals.market, "summary": [s.signals.brief(e) for e in s.signals.latest.values()],
            "positions": s.signals.position_advice, "cycles": s.signals.cycles}


@router.get("/signals/{symbol}")
async def signals_symbol(symbol: str, request: Request, timeframe: Timeframe | None = None):
    s = st(request)
    try:
        ev, snap, _ = await s.signals.evaluate_symbol(_sym(symbol), timeframe)
    except ProviderError as e:
        raise _provider_http(e) from e
    return ev


@router.post("/signals/refresh")
async def signals_refresh(request: Request):
    await st(request).signals.cycle()
    return signals_all(request)


# ---------------- scanner ----------------

@router.get("/scanner")
def scanner(request: Request):
    return st(request).scanner.snapshot()


@router.post("/scanner/run")
async def scanner_run(request: Request, body: dict | None = None):
    from ..scanner.service import ScanFilters

    s = st(request)
    f = ScanFilters(**{**s.scanner.filters.model_dump(), **(body or {})}) if body else None
    return await s.scanner.run_once(f)


# ---------------- backtests & ML ----------------

class BacktestIn(BaseModel):
    symbols: list[str]
    timeframe: Timeframe = Timeframe.M5
    days: int = 58
    mode: str = "backtest"  # backtest | walk_forward | optimize
    setups: list[str] | None = None
    params: dict[str, Any] | None = None
    grid: dict[str, list] | None = None
    starting_cash: float = 25_000
    risk_pct: float = 0.5
    slippage_bps: float = 1.0
    slippage_min: float = 0.01
    commission_per_share: float = 0.0
    allow_short: bool = True
    oos_fraction: float = 0.3
    train_sessions: int = 20
    test_sessions: int = 5


@router.post("/backtest")
async def backtest_run(body: BacktestIn, request: Request):
    s = st(request)
    if body.mode not in ("backtest", "walk_forward", "optimize"):
        raise HTTPException(422, "mode must be backtest, walk_forward or optimize")
    try:
        res = await s.backtests.execute({**body.model_dump(mode="json"), "symbols": [_sym(x) for x in body.symbols]})
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    from ..analysis.engine import to_jsonable

    res["equity"] = res.get("equity", [])[:: max(1, len(res.get("equity", [])) // 1500)]
    return to_jsonable(res)


@router.get("/backtest/runs")
def backtest_runs(request: Request):
    return st(request).backtests.runs()


@router.get("/backtest/runs/{rid}")
def backtest_get(rid: int, request: Request):
    from ..analysis.engine import to_jsonable

    r = st(request).backtests.get_run(rid)
    if not r:
        raise HTTPException(404, "Run not found")
    return to_jsonable(r)


@router.get("/calibration")
def calibration(request: Request):
    return st(request).backtests.calibration


@router.post("/ml/train")
async def ml_train(request: Request, run_id: int | None = None):
    import asyncio

    from ..ml.model import train

    s = st(request)
    runs = [r for r in s.backtests.runs(50) if r["kind"] == "walk_forward"]
    rid = run_id or (runs[0]["id"] if runs else None)
    if not rid:
        raise HTTPException(409, "Run a walk-forward backtest first: the model trains on out-of-sample trades.")
    detail = s.backtests.get_run(rid)
    meta = await asyncio.to_thread(train, detail.get("trades", []), s.settings.data_dir / "models")
    s.models.load()
    return {**meta, "trained_on_run": rid}


@router.get("/ml")
def ml_status(request: Request):
    s = st(request)
    return {"model": s.models.meta, "drift": s.models.drift(list(s.signals.recent_features)),
            "note": "XGBoost is evaluated automatically if you `pip install xgboost`; otherwise scikit-learn models are compared."}


# ---------------- alerts ----------------

@router.get("/alerts")
def alerts(request: Request, limit: int = Query(200, le=2000), symbol: str | None = None):
    s = st(request)
    return {"alerts": s.alerts.history(limit, symbol), "prefs": s.alerts.prefs, "sent": s.alerts.sent,
            "suppressed_duplicates": s.alerts.suppressed,
            "desktop_notifications": "available" if s.alerts.notifier.available else "unavailable on this OS (in-app only)"}


@router.post("/alerts/read")
def alerts_read(request: Request):
    st(request).alerts.mark_read()
    return {"ok": True}


@router.post("/alerts/test")
def alerts_test(request: Request):
    ok = st(request).alerts.emit("system", "high", "Test alert - Study Terminal", "If you can see this, notifications work.",
                                 key=f"test|{__import__('time').time()}", fingerprint="x")
    return {"sent": ok}


# ---------------- AI assistant ----------------

class AskIn(BaseModel):
    question: str
    symbol: str | None = None
    timeframe: Timeframe | None = None


@router.post("/ai/ask")
async def ai_ask(body: AskIn, request: Request):
    s = st(request)
    sym = _sym(body.symbol) if body.symbol else ((s.screen.fusion or {}).get("ticker") if s.screen.fusion else None)
    from ..ai.assistant import classify

    ctx = await s.build_context(sym, body.timeframe, fetch_news=classify(body.question) in ("why_moving", "missing", "explain"))
    res = await s.assistant.ask(body.question, ctx, level=s.settings_store.get("learning.level", "beginner"))
    res["context_symbol"] = sym
    return res


@router.get("/ai/explain/{symbol}")
async def ai_explain(symbol: str, request: Request, timeframe: Timeframe = Timeframe.M5):
    from ..ai.assistant import explain_chart

    s = st(request)
    ctx = await s.build_context(_sym(symbol), timeframe)
    sections = explain_chart(ctx.get("analysis") or {}, s.settings_store.get("learning.level", "beginner"),
                             set(ctx.get("known_terms") or []))
    out = {"symbol": _sym(symbol), "timeframe": timeframe.value, "sections": sections, "engine": "built-in"}
    if s.assistant.provider.name != "none":
        llm = await s.assistant.ask("Explain this chart to me, step by step, for my level.", ctx,
                                    level=s.settings_store.get("learning.level", "beginner"))
        out["ai"] = llm
    return out


@router.get("/ai/status")
async def ai_status(request: Request):
    s = st(request)
    return {"engine": s.assistant.provider_desc, "provider": s.assistant.provider.name,
            "vision": s.assistant.provider.supports_vision and s.settings_store.get("ai.vision", False)}


# ---------------- learning ----------------

@router.get("/learn/lessons")
def lessons(request: Request):
    return st(request).education.lessons()


@router.get("/learn/lessons/{lid}")
def lesson(lid: str, request: Request):
    l = st(request).education.lesson(lid)
    if not l:
        raise HTTPException(404, "Lesson not found")
    return l


class QuizIn(BaseModel):
    answers: list[int]


@router.post("/learn/lessons/{lid}/quiz")
def quiz(lid: str, body: QuizIn, request: Request):
    try:
        return st(request).education.grade(lid, body.answers)
    except KeyError:
        raise HTTPException(404, "Lesson not found")


@router.post("/learn/lessons/{lid}/complete")
def complete(lid: str, request: Request):
    st(request).education.complete(lid)
    return {"ok": True}


@router.get("/learn/progress")
def progress(request: Request):
    e = st(request).education
    return {**e.progress(), "recommendations": e.recommendations()}


@router.get("/learn/glossary")
def glossary(request: Request, q: str | None = None):
    return st(request).education.glossary(q)


@router.post("/learn/exercise")
async def exercise_new(request: Request):
    s = st(request)
    try:
        return await s.education.new_exercise(s.monitor.watchlist_symbols() or ["SPY"])
    except (RuntimeError, ProviderError) as e:
        raise HTTPException(503, str(e))


class ExAnswer(BaseModel):
    choice: str


@router.post("/learn/exercise/{eid}")
def exercise_answer(eid: str, body: ExAnswer, request: Request):
    try:
        return st(request).education.answer_exercise(eid, body.choice)
    except KeyError:
        raise HTTPException(404, "Exercise expired; start a new one")


# ---------------- screen intelligence ----------------

@router.get("/screen/targets")
def screen_targets():
    from ..screen.capture import list_targets

    return {"targets": list_targets(), "window_capture_supported": sys.platform == "win32"}


class ScreenStartIn(BaseModel):
    target: dict
    consent: bool = False


@router.post("/screen/start")
async def screen_start(body: ScreenStartIn, request: Request):
    try:
        return await st(request).screen.start(body.target, body.consent)
    except PermissionError as e:
        raise HTTPException(400, str(e))


@router.post("/screen/pause")
def screen_pause(request: Request):
    return st(request).screen.pause()


@router.post("/screen/resume")
def screen_resume(request: Request):
    return st(request).screen.resume()


@router.post("/screen/stop")
async def screen_stop(request: Request):
    return await st(request).screen.stop()


@router.get("/screen/status")
def screen_status(request: Request):
    return st(request).screen.status()


@router.post("/screen/analyze-image")
async def screen_analyze_image(request: Request, file: UploadFile = File(...), title: str = Form("")):
    data = await file.read()
    if len(data) > 25_000_000:
        raise HTTPException(413, "Image too large")
    try:
        return await st(request).screen.analyze_upload(data, title)
    except ValueError as e:
        raise HTTPException(422, str(e))


# ---------------- settings & monitoring control & desktop ----------------

@router.get("/settings")
def settings_get(request: Request):
    from ..signals.setups import SETUPS

    return {"values": st(request).settings_store.all(), "setups": {k: v[1] for k, v in SETUPS.items()}}


@router.put("/settings")
def settings_put(body: dict, request: Request):
    try:
        return {"values": st(request).settings_store.update(body)}
    except (KeyError, ValueError) as e:
        raise HTTPException(422, str(e))


@router.post("/monitoring/pause")
async def monitoring_pause(request: Request):
    await st(request).monitor.pause()
    return st(request).monitor.status()


@router.post("/monitoring/resume")
async def monitoring_resume(request: Request):
    await st(request).monitor.resume()
    return st(request).monitor.status()


@router.post("/desktop/startup")
def desktop_startup(request: Request, enabled: bool):
    """Start Study Terminal when you log in to Windows (adds/removes a Startup-folder shortcut)."""
    if sys.platform != "win32":
        raise HTTPException(400, "Start-on-login is a Windows feature.")
    import os

    from ..config import FROZEN

    startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "StudyTerminal.cmd"
    root = Path(__file__).resolve().parents[3]
    if enabled:
        if FROZEN:   # installed app: start the exe straight to the tray
            body = f'@echo off\r\nstart "" "{sys.executable}" --minimized\r\n'
        else:        # running from source
            body = (f'@echo off\r\ncd /d "{root}"\r\nstart "" /min powershell -WindowStyle Hidden -ExecutionPolicy Bypass '
                    f'-File "{root / "scripts" / "run-desktop.ps1"}" --minimized\r\n')
        startup.write_text(body, encoding="utf-8")
    else:
        installer_lnk = startup.with_name("Study Terminal.lnk")   # created by the installer's optional task
        for f in (startup, installer_lnk):
            if f.exists():
                f.unlink()
    st(request).settings_store.update({"desktop.start_on_login": enabled})
    return {"enabled": enabled, "path": str(startup)}


@router.get("/desktop/info")
def desktop_info(request: Request):
    """Version and where your data, settings and logs live (so you can find, back up or send logs)."""
    from ..config import ENV_FILES, FROZEN, VERSION

    s = st(request).settings
    return {"version": VERSION, "installed_app": FROZEN, "data_dir": str(s.data_dir), "log_file": str(s.data_dir / "logs" / "study_terminal.log"),
            "database": s.resolved_database_url.replace("sqlite:///", ""), "settings_files": list(ENV_FILES),
            "start_on_login": bool(st(request).settings_store.get("desktop.start_on_login", False)),
            "update_procedure": "Download the new installer and run it: it replaces the program files and keeps your data, settings "
                                "and journal (they live in the data folder above, not in the program folder)."}


@router.post("/desktop/open-folder")
def desktop_open_folder(request: Request, which: str = Query(..., pattern="^(logs|data)$")):
    if sys.platform != "win32":
        raise HTTPException(400, "Opening folders is a Windows desktop feature.")
    import os

    d = st(request).settings.data_dir / ("logs" if which == "logs" else "")
    d.mkdir(parents=True, exist_ok=True)
    os.startfile(str(d))  # noqa: S606 - opens Explorer on our own folder only
    return {"opened": str(d)}


@router.post("/desktop/focus")
def desktop_focus_request(request: Request):
    """A second launch of the app asks the running one to show its window."""
    request.app.state.focus_requested = True
    return {"ok": True}


@router.get("/desktop/focus")
def desktop_focus_poll(request: Request):
    want = bool(getattr(request.app.state, "focus_requested", False))
    request.app.state.focus_requested = False
    return {"show": want}
