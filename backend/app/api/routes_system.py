"""System health: one place for the app, the data file, backups, the chart monitor, the Chrome extension, the last good start,
recent errors and whether a restart would help. Works in Recovery mode too (the parts that can't run say so)."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import datacare
from ..config import BUILD, VERSION

router = APIRouter(prefix="/api/system", tags=["system"])
_DB_CHECK: dict = {"at": 0.0, "result": None}


def _settings(request: Request):
    from ..config import get_settings
    st = request.app.state
    return getattr(st, "boot_settings", None) or getattr(st, "settings", None) or get_settings()


def _db_status(data_dir) -> dict:
    """SQLite's quick check at most once a minute (it reads the whole file)."""
    now = time.monotonic()
    if _DB_CHECK["result"] is None or now - _DB_CHECK["at"] > 60:
        db = data_dir / datacare.DB_NAME
        problem = datacare.check_database(db)
        _DB_CHECK.update(at=now, result={"ok": problem is None and db.exists(), "problem": problem, "exists": db.exists(),
                                         "size_mb": round(db.stat().st_size / 2**20, 2) if db.exists() else 0,
                                         "checked_at": datetime.now().isoformat(timespec="seconds")})
    return _DB_CHECK["result"]


def extension_status(st) -> dict:
    store = getattr(st, "settings_store", None)
    enabled = bool(store.get("extension.enabled", False)) if store else False
    seen = getattr(st, "extension_seen", None) or {}
    port = _port(st)
    if not enabled:
        word, level, do = "Off", "idle", "Optional. Turn it on in Settings > Chrome extension if you use TradingView."
    elif not seen:
        word, level, do = "Waiting for the extension", "attention", ("Open the extension's options in Chrome, paste the pairing code "
                                                                    "from Settings > Chrome extension, and click Save and test.")
    elif seen.get("ok") is False:
        word, level, do = "Pairing code doesn't match", "bad", ("Copy the pairing code again from Settings > Chrome extension and "
                                                               "paste it into the extension's options.")
    elif time.time() - seen.get("ts", 0) > 600:
        word, level, do = "Connected earlier", "ok", "It sends something when you switch TradingView charts."
    else:
        word, level, do = "Connected", "ok", ""
    return {"enabled": enabled, "word": word, "level": level, "do": do, "app_port": port, "last_seen": seen.get("at"),
            "extension_port": seen.get("port"), "extension_version": seen.get("version"), "last_error": seen.get("error")}


def _port(st) -> int | None:
    s = getattr(st, "boot_settings", None) or getattr(st, "settings", None)
    return getattr(s, "port", None)


@router.get("/health")
def health(request: Request):
    st, s = request.app.state, _settings(request)
    d = s.data_dir
    rec = getattr(st, "recovery", None)
    db = _db_status(d) if not rec else {"ok": False, "problem": rec.get("problem"), "exists": True}
    backups = datacare.backup_summary(d)
    disk = datacare.check_disk(d, write_test=False)
    starts = datacare.startup_history(d)
    errors = datacare.recent_errors(d, secrets=s.secret_values())
    wd = getattr(st, "watchdog", None)
    try:
        chart = wd.summary() if wd else None
    except Exception:  # noqa: BLE001
        chart = None
    ext = extension_status(st) if not rec else {"enabled": False, "word": "Not available in Recovery mode", "level": "idle", "do": ""}
    pend = datacare.pending(d)
    reasons = []
    if rec:
        reasons.append("Study Terminal is in Recovery mode. Pick a fix on the Recovery screen; it restarts by itself.")
    if pend:
        reasons.append("A restore or rescue is waiting for a restart.")
    if chart and chart.get("loop_restarts", 0) >= 3:
        reasons.append(f"The chart-reading loop has stopped and restarted {chart['loop_restarts']} times since the app started.")
    hour_ago = datetime.now().timestamp() - 3600
    recent = [e for e in errors if datetime.fromisoformat(e["at"]).timestamp() > hour_ago]
    if len(recent) >= 5:
        reasons.append(f"{len(recent)} errors were logged in the last hour.")
    started = getattr(getattr(st, "monitor", None), "started_at", None)
    problems = []
    if not db.get("ok"):
        problems.append("data file")
    if backups["warning"] or (backups["count"] and not backups["newest_ok"]):
        problems.append("backups")
    if disk.get("low_space"):
        problems.append("disk space")
    if chart and chart["overall"]["level"] == "bad":
        problems.append("chart monitor")
    if ext["level"] == "bad":
        problems.append("Chrome extension")
    overall = ("Problem" if rec or "data file" in problems else "Needs attention" if problems or reasons else "All good")
    return {
        "overall": overall, "problems": problems,
        "app": {"version": VERSION, "build": BUILD, "mode": "recovery" if rec else "normal", "port": _port(st),
                "started_at": started.isoformat() if started else None, "practice_only": True,
                "restart_requested": bool(getattr(st, "restart_requested", False))},
        "data_file": {**db, "folder": str(d), "disk": disk},
        "backups": backups,
        "chart_monitor": chart["overall"] if chart else {"word": "Not running", "level": "idle", "reason": "", "do": ""},
        "chart_loop_restarts": chart.get("loop_restarts", 0) if chart else 0,
        "extension": ext,
        "startups": {"last_ok": starts.get("last_ok"), "recent": starts.get("starts", [])[:5],
                     "unclean_last_time": (chart or {}).get("unclean_shutdown")},
        "recent_errors": errors,
        "restart_recommended": bool(reasons), "restart_reasons": reasons,
        "self_check": datacare.last_self_check(d),
        "last_recovery": datacare.last_recovery(d),
    }


class RestartIn(BaseModel):
    confirm: bool = False


@router.post("/restart")
def restart(body: RestartIn, request: Request):
    if not body.confirm:
        raise HTTPException(400, "Please confirm first.")
    request.app.state.restart_requested = True       # the desktop app stops the backend cleanly and starts it again
    return {"restart_requested": True}


@router.post("/self-check")
async def run_self_check(request: Request):
    s = _settings(request)
    lock = getattr(request.app.state, "self_check_lock", None)
    if lock is None:
        lock = request.app.state.self_check_lock = asyncio.Lock()
    if lock.locked():
        raise HTTPException(409, "The check is already running.")
    async with lock:
        return await asyncio.to_thread(datacare.self_check, s.data_dir, VERSION)


@router.post("/check-backups")
async def check_backups(request: Request):
    s = _settings(request)
    backups = await asyncio.to_thread(datacare.verify_all, s.data_dir)
    return {"backups": backups, "summary": datacare.backup_summary(s.data_dir)}
