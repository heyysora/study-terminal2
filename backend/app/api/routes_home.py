"""Home (five plain answers), Stop everything, and the word list. Home is read-only."""
from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import home, plain

ET = ZoneInfo("America/New_York")

router = APIRouter(prefix="/api", tags=["home"])
log = logging.getLogger(__name__)


def _point_value(code: str | None) -> float | None:
    from ..futures import contracts as fc
    try:
        ps = fc.parse_symbol(code, allow_bare_root=True)
        root = ps.root or (ps.contract.root if ps.contract else None)
        return float(fc.get(root).multiplier)               # dollars per 1.00 of price, per contract
    except Exception:  # noqa: BLE001 - unknown contract: no dollar estimate
        return None


@router.get("/watchdog")
def watchdog_view(request: Request):
    """Reliability status per watched chart, the newest changes, and whether the last session ended normally."""
    return request.app.state.watchdog.check(restart=False)


def _key_symbol(s, trades: str) -> str:
    if trades != "futures":
        return "SPY"
    try:
        for prof in s.visual.store.all():
            root = getattr(prof, "root", "") or ""
            if root and root != "auto":
                return f"{root.upper()}=F"
    except Exception:  # noqa: BLE001
        pass
    return "NQ=F"


def _last_session(s, sym: str) -> dict | None:
    """The last finished session's change from real daily bars (cached 10 minutes). None if it can't be fetched."""
    import time as _t
    from datetime import datetime, timedelta, timezone

    import anyio

    from ..market_data.types import Timeframe
    cache = getattr(s, "last_session_cache", None) or {}
    hit = cache.get(sym)
    if hit and _t.monotonic() - hit[0] < 600:
        return hit[1]
    out = None
    try:
        bars, _, _ = anyio.from_thread.run(s.monitor.bars, sym, Timeframe.D1, datetime.now(timezone.utc) - timedelta(days=12))
        bars = [b for b in bars if b.close]
        if len(bars) >= 2:
            last, prev = bars[-1], bars[-2]
            day = last.ts.astimezone(ET)
            out = {"close": float(last.close), "change_pct": round((float(last.close) / float(prev.close) - 1) * 100, 2),
                   "day": "On " + day.strftime("%A"), "as_of": last.ts.isoformat(),
                   "name": {"SPY": "S&P 500 fund, SPY"}.get(sym, sym.replace("=F", " futures, free delayed data"))}
    except Exception:  # noqa: BLE001 - no network or no data: just don't show a last result
        log.info("couldn't get the last session for %s", sym, exc_info=True)
    cache[sym] = (_t.monotonic(), out)
    s.last_session_cache = cache
    return out


@router.get("/home")
def home_view(request: Request):
    s = request.app.state
    store = s.settings_store
    trades = "futures" if store.get("app.market_mode", "equities") == "futures" else "stocks"
    err = None

    def safe(fn, default=None):
        nonlocal err
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - one failing part must not blank the whole Home screen
            log.exception("home: a status source failed")
            err = f"{type(e).__name__}: {e}"
            return default

    db_ok = True
    try:
        from sqlalchemy import text
        with s.db.session() as ses:
            ses.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    visual = safe(s.visual.status, {})
    days = safe(lambda: s.visual.capture_stats.days, {}) or {}
    chart_seen = any((d or {}).get("live", 0) > 0 for d in days.values()) or any(
        c.get("status") == "screen_capture" for c in (visual.get("charts") or {}).values())
    sig = s.signals
    wd = safe(lambda: s.watchdog.check(restart=False), None)
    from ..market_data.hours import public
    key = _key_symbol(s, trades)
    hours = safe(lambda: public(s.monitor.market_state(key)), None)
    last_session = _last_session(s, key) if hours and not hours.get("open") else None
    return home.build(
        trades=trades, db_ok=db_ok, monitor=safe(s.monitor.status, {}), visual=visual,
        automation=safe(s.futures.automation.status, {}), profiles=len(safe(s.visual.store.all, []) or []),
        futures_account=safe(s.futures.account, {}), stock_account=safe(s.paper.engine.summary, {}),
        decisions=safe(lambda: s.futures.decisions(limit=3), []) or [],
        signals={"market": sig.market, "summary": [sig.brief(e) for e in sig.latest.values()]},
        backup=getattr(s, "backup", None), trades_chosen=bool(store.get("ui.trades_chosen", False)) or trades == "futures",
        chart_seen=chart_seen, setup_dismissed=bool(store.get("ui.setup_dismissed", False)), ui_mode=store.get("ui.mode", "simple"),
        point_value_of=_point_value, engine_error=err, watchdog=wd, hours=hours, last_session=last_session)


class StopIn(BaseModel):
    confirm: bool = False


@router.post("/stop-everything")
async def stop_everything(body: StopIn, request: Request):
    """One button for the existing stops: automation emergency stop (cancels its practice orders and closes the practice trades it
    manages), Visual Monitor stop, screen watching stop. Practice trades you placed yourself are left alone. Nothing here can touch a
    real account: Study Terminal has no connection that places orders."""
    if not body.confirm:
        raise HTTPException(400, "Stopping everything needs confirmation.")
    s = request.app.state
    done, failed = [], []
    em = {}
    try:
        st = await s.futures.automation.emergency_stop("Stop everything pressed")
        em = st.get("emergency") or {}
        done.append("Market checking is stopped.")
    except Exception as e:  # noqa: BLE001 - keep stopping the rest
        log.exception("stop everything: automation")
        failed.append(f"Market checking couldn't be stopped ({type(e).__name__}).")
    for name, fn in (("Chart watching", s.visual.stop), ("Screen watching", s.screen.stop)):
        try:
            await fn()
            done.append(f"{name} is stopped.")
        except Exception as e:  # noqa: BLE001
            log.exception("stop everything: %s", name)
            failed.append(f"{name} couldn't be stopped ({type(e).__name__}).")
    try:
        s.alerts.emit("system", "high", "Everything is stopped", "Stop everything was pressed. Nothing is being watched or practiced "
                      "until you start again.", key="stop-everything")
    except Exception:  # noqa: BLE001
        pass
    return {"ok": not failed, "done": done, "failed": failed,
            "practice_orders_cancelled": em.get("orders_canceled", 0), "practice_trades_closed": em.get("positions_flattened", 0),
            "practice_trades_waiting_to_close": em.get("positions_queued", 0),
            "left_alone": "Practice trades you placed yourself are left as they are. You can close them from your practice account.",
            "real_account": "Your real TopstepX account is not affected. Study Terminal can't place, change or cancel real orders."}


class StartAgainIn(BaseModel):
    note: str = ""


@router.post("/start-again")
def start_again(body: StartAgainIn, request: Request):
    """Clears the stop (the existing rule still applies: you must write at least a sentence). It doesn't start anything by itself."""
    try:
        st = request.app.state.futures.automation.clear_emergency(body.note)
    except ValueError as e:
        raise HTTPException(422, "Write one sentence (at least 10 letters) about why you stopped.") from e
    return {"ok": st.get("status") != "emergency_stopped", "status": st.get("status")}


@router.get("/plain")
def words():
    return plain.export()


class ExplainIn(BaseModel):
    reason: str = ""
    action: str | None = None


@router.post("/plain/explain")
def explain(body: ExplainIn):
    return {**plain.plain_reason(body.reason), **({"action": plain.plain_action(body.action)} if body.action else {})}
