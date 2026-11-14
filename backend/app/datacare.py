"""Looking after your data folder without a terminal.

- check_database: is the data file readable? A damaged file puts the app in Recovery mode instead of crashing.
- check_disk: can the data folder be written, and is there room?
- Backups: daily (kept 7), made with a button (kept 10), automatic before an upgrade (backup.py, kept 10) and before any restore
  (kept 5). Database copies use SQLite's own backup, so they are consistent even while the app runs. Each backup records whether
  its copy passed SQLite's check and how many journal trades and practice orders it holds, so you can pick one by what's in it.
- Restore / rescue / start fresh are *scheduled* and done at the next start, before the database is opened. The current file is
  always moved to <data>/damaged/<time>/ (or replaced/), never deleted, and the result is written to last_recovery.json.
- make_help_file: one zip in your Downloads folder with the logs, Chart check results, chart setups and app status. Secret values
  are blanked out, .env is never included, and the database only if you ask.

Only the standard library is used, so this module still works when the rest of the app can't start.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)
DB_NAME = "study_terminal.db"
PENDING = "pending_recovery.json"
LAST = "last_recovery.json"
KEEP = {"before upgrade": 10, "daily": 7, "manual": 10, "before restore": 5}
DAILY_EVERY = timedelta(hours=20)
LOW_SPACE_MB = 300
SKIP = {"backups", "logs", "models", "__pycache__", "damaged", "replaced", "yf-cache", "live_prices", "help"}
COUNT_TABLES = {"journal_trades": "journal trades", "paper_orders": "practice orders", "futures_fills": "futures practice fills"}


# ---------------- checks ----------------

def check_database(path: Path) -> str | None:
    """None if the file is fine or doesn't exist yet; otherwise what's wrong, in SQLite's words."""
    path = Path(path)
    if not path.exists():
        return None
    if path.stat().st_size == 0:
        return "the data file is empty"
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            rows = [r[0] for r in con.execute("PRAGMA quick_check(20)")]
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        return str(e)
    if rows != ["ok"]:
        return "; ".join(rows[:3])
    return None


def check_disk(data_dir: Path, write_test: bool = True) -> dict:
    data_dir = Path(data_dir)
    out = {"writable": True, "free_mb": None, "low_space": False, "error": None}
    try:
        out["free_mb"] = int(shutil.disk_usage(data_dir).free / 2**20)
        out["low_space"] = out["free_mb"] < LOW_SPACE_MB
    except OSError as e:
        out["error"] = str(e)
    if write_test:
        probe = data_dir / ".write_test"
        try:
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as e:
            out.update(writable=False, error=f"{type(e).__name__}: {e}")
    return out


# ---------------- backups ----------------

def _copy_db(src: Path, dst: Path) -> None:
    a = sqlite3.connect(f"file:{Path(src).as_posix()}?mode=ro", uri=True, timeout=15)
    try:
        b = sqlite3.connect(dst)
        try:
            a.backup(b)
        finally:
            b.close()
    finally:
        a.close()


def _summary(db: Path) -> dict:
    out = {"ok": check_database(db) is None, "counts": {}}
    if out["ok"] and db.exists():
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            for t, label in COUNT_TABLES.items():
                if t in names:
                    out["counts"][label] = con.execute(f'select count(*) from "{t}"').fetchone()[0]
        finally:
            con.close()
    return out


def backup_now(data_dir: Path, kind: str = "manual", now: datetime | None = None, include_files: bool = True) -> dict:
    """Copy the database (and small data files) to backups/<time> <kind>. Never raises."""
    data_dir = Path(data_dir)
    db = data_dir / DB_NAME
    now = now or datetime.now()
    try:
        if not db.exists():
            return {"made": False, "error": "There's no data to back up yet."}
        if check_database(db) is not None:
            return {"made": False, "error": "The data file is damaged, so it wasn't copied over a good backup."}
        disk = check_disk(data_dir, write_test=False)
        if disk["low_space"]:
            return {"made": False, "error": f"Only {disk['free_mb']} MB free on the disk."}
        dest = data_dir / "backups" / f"{now.strftime('%Y-%m-%d %H%M%S')} {kind}"
        n = 1
        while dest.exists():
            n += 1
            dest = dest.with_name(f"{now.strftime('%Y-%m-%d %H%M%S')} {kind} {n}")
        dest.mkdir(parents=True)
        _copy_db(db, dest / DB_NAME)
        if include_files:
            for p in sorted(data_dir.iterdir()):
                if p.name in SKIP or p.name.startswith(DB_NAME) or p.name in (".env", PENDING, ".write_test"):
                    continue
                if p.is_dir():
                    shutil.copytree(p, dest / p.name)
                elif p.is_file():
                    shutil.copy2(p, dest / p.name)
        info = {"kind": kind, "made_at": now.isoformat(timespec="seconds"), **_summary(dest / DB_NAME)}
        (dest / "backup_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
        prune(data_dir)
        return {"made": True, "name": dest.name, "path": str(dest), **info}
    except Exception as e:  # noqa: BLE001 - a backup problem must never take the app down
        log.exception("backup failed")
        return {"made": False, "error": f"{type(e).__name__}: {e}"}


def _kind(name: str) -> str:
    if " before restore" in name:
        return "before restore"
    if " before " in name:
        return "before upgrade"
    for k in ("daily", "manual"):
        if f" {k}" in name:
            return k
    return "other"


def prune(data_dir: Path) -> None:
    folder = Path(data_dir) / "backups"
    if not folder.exists():
        return
    for kind, keep in KEEP.items():
        dirs = sorted(p for p in folder.iterdir() if p.is_dir() and _kind(p.name) == kind)
        for p in dirs[:-keep]:
            shutil.rmtree(p, ignore_errors=True)


def list_backups(data_dir: Path) -> list[dict]:
    folder = Path(data_dir) / "backups"
    if not folder.exists():
        return []
    out = []
    for p in sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        db = p / DB_NAME
        info_file = p / "backup_info.json"
        try:
            info = json.loads(info_file.read_text(encoding="utf-8")) if info_file.exists() else _summary(db)
        except (OSError, ValueError, sqlite3.Error):
            info = {"ok": False, "counts": {}}
        try:
            when = datetime.strptime(p.name[:17], "%Y-%m-%d %H%M%S").isoformat()
        except ValueError:
            when = None
        out.append({"name": p.name, "kind": _kind(p.name), "made_at": when, "has_database": db.exists(),
                    "ok": bool(info.get("ok")) and db.exists(), "counts": info.get("counts", {}),
                    "size_mb": round(db.stat().st_size / 2**20, 2) if db.exists() else 0})
    return out


def daily_backup_if_due(data_dir: Path, now: datetime | None = None) -> dict | None:
    now = now or datetime.now()
    for b in list_backups(data_dir):
        if b["kind"] in ("daily", "manual", "before upgrade") and b["ok"] and b["made_at"]:
            if now - datetime.fromisoformat(b["made_at"]) < DAILY_EVERY:
                return None
            break
    return backup_now(data_dir, "daily", now, include_files=False)


# ---------------- restore / rescue / fresh (done at the next start) ----------------

def when_text(name: str) -> str:
    """'2026-11-12 180000 daily' -> 'Nov 12, 6:00 PM'."""
    try:
        t = datetime.strptime(name[:17], "%Y-%m-%d %H%M%S")
    except ValueError:
        return name
    return f"{t:%b} {t.day}, {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'}"


def schedule(data_dir: Path, action: str, backup: str | None = None) -> dict:
    """action: restore (needs backup), rescue, fresh. Applied by apply_pending() before the database is opened."""
    if action not in ("restore", "rescue", "fresh"):
        raise ValueError("unknown action")
    if action == "restore":
        b = next((x for x in list_backups(data_dir) if x["name"] == backup), None)
        if b is None:
            raise ValueError("That backup doesn't exist.")
        if not b["ok"]:
            raise ValueError("That backup's data file didn't pass the check, so it can't be restored.")
    plan = {"action": action, "backup": backup, "asked_at": datetime.now().isoformat(timespec="seconds")}
    (Path(data_dir) / PENDING).write_text(json.dumps(plan), encoding="utf-8")
    return plan


def cancel(data_dir: Path) -> None:
    (Path(data_dir) / PENDING).unlink(missing_ok=True)


def pending(data_dir: Path) -> dict | None:
    f = Path(data_dir) / PENDING
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except (OSError, ValueError):
        return None


def _move_aside(data_dir: Path, folder: str, now: datetime) -> Path | None:
    """Move the database and its -wal/-shm files to <folder>/<time>/. Returns where, or None if there was nothing."""
    files = [p for p in Path(data_dir).glob(DB_NAME + "*") if p.is_file()]
    if not files:
        return None
    dest = Path(data_dir) / folder / now.strftime("%Y-%m-%d %H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    for p in files:
        shutil.move(str(p), str(dest / p.name))
    return dest


def rescue_into(damaged: Path, out: Path) -> dict:
    """Copy every table that can still be read from a damaged database into a new one. Returns what was saved."""
    src = sqlite3.connect(f"file:{Path(damaged).as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(out)
    saved, lost = {}, []
    try:
        tables = src.execute("select name, sql from sqlite_master where type='table' and name not like 'sqlite_%'").fetchall()
        for name, sql in tables:
            try:
                dst.execute(sql)
                rows = src.execute(f'select * from "{name}"').fetchall()
                if rows:
                    dst.executemany(f'insert into "{name}" values ({",".join("?" * len(rows[0]))})', rows)
                dst.commit()
                saved[name] = len(rows)
            except sqlite3.Error:
                dst.rollback()
                lost.append(name)
        for (sql,) in src.execute("select sql from sqlite_master where type='index' and sql is not null").fetchall():
            try:
                dst.execute(sql)
            except sqlite3.Error:
                pass
        dst.commit()
    finally:
        src.close()
        dst.close()
    return {"saved": saved, "lost": lost}


def apply_pending(data_dir: Path, now: datetime | None = None) -> dict | None:
    """Run a scheduled restore/rescue/fresh start. Called at start-up before the database is opened. Never raises."""
    data_dir = Path(data_dir)
    plan = pending(data_dir)
    if not plan:
        return None
    now = now or datetime.now()
    db = data_dir / DB_NAME
    result = {"action": plan["action"], "backup": plan.get("backup"), "done_at": now.isoformat(timespec="seconds"),
              "ok": False, "moved_to": None, "safety_backup": None, "detail": ""}
    try:
        damaged = check_database(db) is not None
        if plan["action"] == "restore":
            src = data_dir / "backups" / plan["backup"] / DB_NAME
            if check_database(src) is not None or not src.exists():
                raise RuntimeError("the backup's data file didn't pass the check")
            if db.exists() and not damaged:   # a good current file is kept as a backup you can go back to
                sb = backup_now(data_dir, "before restore", now, include_files=False)
                result["safety_backup"] = sb.get("name")
            moved = _move_aside(data_dir, "damaged" if damaged else "replaced", now)
            shutil.copy2(src, db)
            result.update(ok=True, moved_to=str(moved) if moved else None,
                          detail=f"Restored your data from the backup made {when_text(plan['backup'])}.")
        elif plan["action"] == "rescue":
            if not db.exists():
                raise RuntimeError("there's no data file to rescue")
            tmp = data_dir / "rescued-data.tmp"          # not named study_terminal.db*, so moving the damaged file leaves it
            tmp.unlink(missing_ok=True)
            r = rescue_into(db, tmp)
            if not r["saved"]:
                tmp.unlink(missing_ok=True)
                raise RuntimeError("nothing could be read from the damaged file")
            moved = _move_aside(data_dir, "damaged", now)
            tmp.replace(db)
            result.update(ok=True, moved_to=str(moved) if moved else None, rescued=r,
                          detail=f"Rescued {len(r['saved'])} of {len(r['saved']) + len(r['lost'])} parts of your data."
                          + (f" Couldn't read: {', '.join(r['lost'])}." if r["lost"] else ""))
        else:   # fresh
            moved = _move_aside(data_dir, "damaged" if damaged else "replaced", now)
            result.update(ok=True, moved_to=str(moved) if moved else None,
                          detail="Started with empty data. Your old data file was kept, not deleted.")
    except Exception as e:  # noqa: BLE001
        log.exception("recovery action failed")
        result["detail"] = f"That didn't work: {e}. Nothing was deleted."
    (data_dir / PENDING).unlink(missing_ok=True)
    (data_dir / LAST).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def last_recovery(data_dir: Path) -> dict | None:
    f = Path(data_dir) / LAST
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except (OSError, ValueError):
        return None


# ---------------- help file ----------------

def downloads_dir() -> Path:
    if sys.platform == "win32":
        try:   # the real Downloads folder, even if it was moved
            import ctypes
            import uuid
            from ctypes import wintypes
            guid = uuid.UUID("{374DE290-123F-4565-9164-39C4925E467B}")
            buf = ctypes.c_wchar_p()
            g = (ctypes.c_byte * 16).from_buffer_copy(guid.bytes_le)
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(buf)) == 0:
                p = Path(buf.value)
                ctypes.windll.ole32.CoTaskMemFree(buf)
                if p.is_dir():
                    return p
            del wintypes
        except Exception:  # noqa: BLE001
            pass
    p = Path.home() / "Downloads"
    return p if p.is_dir() else Path.home()


def _scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "[hidden]")
    return text


def make_help_file(data_dir: Path, secrets: list[str] | None = None, about: dict | None = None, include_database: bool = False,
                   dest_dir: Path | None = None, now: datetime | None = None, max_mb: int = 60) -> Path:
    """Zip what's needed to understand a problem. Returns the zip's path."""
    data_dir = Path(data_dir)
    secrets = [s for s in (secrets or []) if s]
    now = now or datetime.now()
    dest_dir = Path(dest_dir) if dest_dir else downloads_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"StudyTerminal-help-{now.strftime('%Y-%m-%d-%H%M%S')}.zip"
    budget = max_mb * 2**20
    info = {"made_at": now.isoformat(timespec="seconds"), "python": sys.version.split()[0], "platform": sys.platform,
            "data_folder": str(data_dir), "disk": check_disk(data_dir, write_test=False),
            "database_check": check_database(data_dir / DB_NAME) or "ok", "backups": list_backups(data_dir),
            "last_recovery": last_recovery(data_dir), "pending_recovery": pending(data_dir), **(about or {})}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("about.json", _scrub(json.dumps(info, indent=1, default=str), secrets))
        texts = []
        logs = data_dir / "logs"
        if logs.exists():
            texts += sorted(logs.glob("*.log*"))
        for name in ("installed_build.txt", "visual_profiles.json", "running.marker", LAST):
            if (data_dir / name).exists():
                texts.append(data_dir / name)
        cc = data_dir / "chart_checks"
        if (cc / "results.jsonl").exists():
            texts.append(cc / "results.jsonl")
        for p in texts:
            try:
                data = p.read_bytes()[-8 * 2**20:]        # the newest 8 MB of a long log
                text = _scrub(data.decode("utf-8", "replace"), secrets)
            except OSError:
                continue
            budget -= len(text)
            z.writestr(str(p.relative_to(data_dir)).replace("\\", "/"), text)
        if cc.exists():
            for img in sorted(cc.glob("*.jpg"), reverse=True):
                if budget < img.stat().st_size:
                    break
                budget -= img.stat().st_size
                z.write(img, f"chart_checks/{img.name}")
        if include_database and (data_dir / DB_NAME).exists() and check_database(data_dir / DB_NAME) is None:
            tmp = dest_dir / f".st-db-{os.getpid()}.tmp"
            try:
                _copy_db(data_dir / DB_NAME, tmp)
                z.write(tmp, DB_NAME)
            finally:
                tmp.unlink(missing_ok=True)
        z.writestr("README.txt", "Study Terminal help file. Contains logs, Chart check results and pictures, chart setups and app "
                   "status. Passwords and API keys are blanked out; the .env file is never included"
                   + (". Your data file IS included." if include_database else "; your data file is not included.") + "\n")
    return out


def open_folder(path: Path) -> bool:
    """Show a folder (or select a file) in Windows Explorer. Returns False where that isn't possible."""
    if sys.platform != "win32":
        return False
    p = Path(path)
    import subprocess
    if p.is_file():
        subprocess.Popen(["explorer", "/select,", str(p)])   # noqa: S603,S607
    else:
        os.startfile(str(p))  # noqa: S606
    return True
