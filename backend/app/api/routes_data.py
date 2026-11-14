"""Your data folder from inside the app: backups, restore, rescue, a fresh start, the help file, and Recovery mode.

Restore, rescue and a fresh start are scheduled and carried out at the next start, before the data file is opened; the desktop
app restarts itself to do it. Nothing is ever deleted: the file being replaced is moved to damaged/ or replaced/.
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .. import datacare
from ..config import BUILD, VERSION

router = APIRouter(prefix="/api/data", tags=["data"])
HELP_NAME = re.compile(r"^StudyTerminal-help-\d{4}-\d{2}-\d{2}-\d{6}\.zip$")


def _settings(request: Request):
    from ..config import get_settings
    st = request.app.state
    return getattr(st, "boot_settings", None) or getattr(st, "settings", None) or get_settings()


@router.get("/status")
def status(request: Request):
    st, d = request.app.state, _settings(request).data_dir
    summ = datacare.backup_summary(d)
    return {"recovery": getattr(st, "recovery", None), "restart_requested": getattr(st, "restart_requested", False),
            "pending": datacare.pending(d), "last_recovery": datacare.last_recovery(d),
            "disk": datacare.check_disk(d, write_test=False), "backups": summ["count"], "backup_summary": summ,
            "last_backup": summ["last_good"], "data_folder": str(d), "version": VERSION}


@router.get("/backups")
def backups(request: Request):
    d = _settings(request).data_dir
    return {"backups": datacare.list_backups(d), "summary": datacare.backup_summary(d)}


@router.post("/backup")
def backup(request: Request):
    if getattr(request.app.state, "recovery", None):
        raise HTTPException(409, "Your data file is damaged, so it can't be backed up. Restore a backup or rescue it first.")
    r = datacare.backup_now(_settings(request).data_dir, "manual")
    if not r.get("made"):
        raise HTTPException(409, r.get("error") or "The backup didn't work.")
    return r


class ScheduleIn(BaseModel):
    action: str                 # restore | rescue | fresh
    backup: str | None = None
    confirm: bool = False


@router.post("/schedule")
def schedule(body: ScheduleIn, request: Request):
    if not body.confirm:
        raise HTTPException(400, "Please confirm first.")
    try:
        plan = datacare.schedule(_settings(request).data_dir, body.action, body.backup)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    request.app.state.restart_requested = True      # the desktop app restarts and carries it out before opening the data
    return {"scheduled": plan, "restart_requested": True}


@router.post("/cancel")
def cancel(request: Request):
    datacare.cancel(_settings(request).data_dir)
    request.app.state.restart_requested = False
    return {"ok": True}


@router.post("/dismiss-last")
def dismiss_last(request: Request):
    (_settings(request).data_dir / datacare.LAST).unlink(missing_ok=True)
    return {"ok": True}


class HelpIn(BaseModel):
    include_database: bool = False


@router.post("/help-file")
def help_file(body: HelpIn, request: Request):
    s, st = _settings(request), request.app.state
    about = {"version": VERSION, "build": BUILD, "recovery": getattr(st, "recovery", None)}
    wd = getattr(st, "watchdog", None)
    if wd is not None:
        try:
            about["chart_status"] = wd.summary()
        except Exception as e:  # noqa: BLE001 - the help file must work even when parts of the app don't
            about["chart_status"] = f"unavailable: {e}"
    cc = getattr(st, "chart_check", None)
    if cc is not None:
        try:
            about["chart_check"] = cc.summary()
        except Exception as e:  # noqa: BLE001
            about["chart_check"] = f"unavailable: {e}"
    try:
        p = datacare.make_help_file(s.data_dir, s.secret_values(), about, include_database=body.include_database,
                                    dest_dir=getattr(st, "help_dir", None))
    except OSError as e:
        raise HTTPException(500, f"Couldn't save the help file: {e}") from None
    return {"name": p.name, "path": str(p), "folder": str(p.parent), "size_mb": round(p.stat().st_size / 2**20, 2)}


class ShowIn(BaseModel):
    what: str                   # data | backups | help
    name: str | None = None


@router.post("/show")
def show(body: ShowIn, request: Request):
    s, st = _settings(request), request.app.state
    if body.what == "data":
        target = s.data_dir
    elif body.what == "backups":
        target = s.data_dir / "backups"
    elif body.what == "help" and body.name and HELP_NAME.match(body.name):
        target = Path(getattr(st, "help_dir", None) or datacare.downloads_dir()) / body.name
        if not target.exists():
            raise HTTPException(404, "That help file isn't there any more.")
    else:
        raise HTTPException(400, "Unknown folder.")
    target.mkdir(parents=True, exist_ok=True) if body.what == "backups" else None
    return {"shown": datacare.open_folder(target), "path": str(target)}
