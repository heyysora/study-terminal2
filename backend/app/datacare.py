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

import hashlib
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
SKIP = {"backups", "logs", "models", "__pycache__", "damaged", "replaced", "yf-cache", "live_prices", "help", "selfcheck-scratch"}
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


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _summary(db: Path) -> dict:
    out = {"ok": check_database(db) is None and db.exists(), "counts": {}}
    if out["ok"]:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            for t, label in COUNT_TABLES.items():
                if t in names:
                    out["counts"][label] = con.execute(f'select count(*) from "{t}"').fetchone()[0]
        finally:
            con.close()
    return out


# A backup's status, in plain words for the screens:
USABLE, INCOMPLETE, DAMAGED, MISSING = "usable", "incomplete", "damaged", "missing files"
STATUS_TEXT = {USABLE: "Checked: can be restored.", INCOMPLETE: "Didn't finish (the app may have closed while it was being made).",
               DAMAGED: "Damaged: a file in it doesn't match what was saved.", MISSING: "Some of its files are missing."}


def verify_backup(folder: Path, full: bool = True) -> dict:
    """Is this backup usable? full=True re-reads every file (hash) and opens the data file with SQLite's check;
    full=False only checks that everything listed is there with the right size (fast, for lists)."""
    folder = Path(folder)
    db = folder / DB_NAME
    info_f, man_f = folder / "backup_info.json", folder / "manifest.json"
    problems: list[str] = []
    try:
        info = json.loads(info_f.read_text(encoding="utf-8")) if info_f.exists() else None
    except (OSError, ValueError):
        info = None
    try:
        manifest = json.loads(man_f.read_text(encoding="utf-8")) if man_f.exists() else None
    except (OSError, ValueError):
        manifest = None
    legacy = info is None and manifest is None and not (folder / ".in-progress").exists()   # made before 0.13.5
    if (folder / ".in-progress").exists() or (not legacy and (not info or not info.get("complete") or manifest is None)):
        return {"status": INCOMPLETE, "problems": ["The backup never finished."], "checked": "full" if full else "quick"}
    if not db.exists():
        return {"status": MISSING, "problems": ["The data file isn't in this backup."], "checked": "full" if full else "quick"}
    for rel, meta in (manifest or {}).get("files", {}).items():
        p = folder / rel
        if not p.exists():
            problems.append(f"missing: {rel}")
        elif p.stat().st_size != meta["size"]:
            problems.append(f"wrong size: {rel}")
        elif full and _sha256(p) != meta["sha256"]:
            problems.append(f"changed or damaged: {rel}")
    status = USABLE
    if any(x.startswith("missing") for x in problems):
        status = MISSING
    elif problems:
        status = DAMAGED
    if full or legacy:
        why = check_database(db)
        if why:
            status, problems = DAMAGED, problems + [f"data file: {why}"]
    return {"status": status, "problems": problems[:8], "checked": "full" if full else "quick", "legacy": legacy}


def backup_now(data_dir: Path, kind: str = "manual", now: datetime | None = None, include_files: bool = True) -> dict:
    """Copy the database (and small data files) to backups/<time> <kind>, then check the copy can be opened and read back.
    A backup is only 'complete' once backup_info.json is written, last. Never raises; never overwrites an existing backup."""
    data_dir = Path(data_dir)
    db = data_dir / DB_NAME
    now = now or datetime.now()
    try:
        if not db.exists():
            return {"made": False, "error": "There's no data to back up yet."}
        if check_database(db) is not None:
            return {"made": False, "error": "The data file is damaged, so it wasn't copied over as a backup."}
        disk = check_disk(data_dir, write_test=False)
        if disk["low_space"]:
            return {"made": False, "error": f"Only {disk['free_mb']} MB free on the disk."}
        stamp = now.strftime("%Y-%m-%d %H%M%S")
        dest = data_dir / "backups" / f"{stamp} {kind}"
        n = 1
        while dest.exists():
            n += 1
            dest = dest.with_name(f"{stamp} {kind} {n}")
        dest.mkdir(parents=True)
        (dest / ".in-progress").write_text("A backup was being made here.", encoding="utf-8")
        _copy_db(db, dest / DB_NAME)
        if include_files:
            for p in sorted(data_dir.iterdir()):
                if p.name in SKIP or p.name.startswith(DB_NAME) or p.name in (".env", PENDING, ".write_test") or p.suffix == ".tmp":
                    continue
                if p.is_dir():
                    shutil.copytree(p, dest / p.name)
                elif p.is_file():
                    shutil.copy2(p, dest / p.name)
        files = {}
        for p in sorted(dest.rglob("*")):
            if p.is_file() and p.name not in (".in-progress", "manifest.json", "backup_info.json"):
                files[p.relative_to(dest).as_posix()] = {"size": p.stat().st_size, "sha256": _sha256(p)}
        (dest / "manifest.json").write_text(json.dumps({"files": files}, indent=1), encoding="utf-8")
        (dest / ".in-progress").unlink()
        summary = _summary(dest / DB_NAME)
        info = {"kind": kind, "made_at": now.isoformat(timespec="seconds"), "complete": True, **summary}
        (dest / "backup_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
        v = verify_backup(dest, full=True)                 # read it all back: proves the copy can actually be used
        _remember_check(data_dir, dest.name, v, now)
        if v["status"] != USABLE:
            return {"made": False, "name": dest.name, "error": "The new backup didn't pass its check: " + "; ".join(v["problems"])}
        prune(data_dir)
        return {"made": True, "name": dest.name, "path": str(dest), "verified": True, **info}
    except Exception as e:  # noqa: BLE001 - a backup problem must never take the app down
        log.exception("backup failed")
        return {"made": False, "error": f"{type(e).__name__}: {e}"}


def _check_cache(data_dir: Path) -> dict:
    f = Path(data_dir) / "backups" / "checks.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        return {}


def _remember_check(data_dir: Path, name: str, v: dict, now: datetime | None = None) -> None:
    c = _check_cache(data_dir)
    c[name] = {**v, "checked_at": (now or datetime.now()).isoformat(timespec="seconds")}
    names = {p.name for p in (Path(data_dir) / "backups").iterdir() if p.is_dir()}
    c = {k: x for k, x in c.items() if k in names}
    (Path(data_dir) / "backups" / "checks.json").write_text(json.dumps(c, indent=1), encoding="utf-8")


def verify_all(data_dir: Path) -> list[dict]:
    """Full check of every backup (re-reads every file). For the 'Check my backups' button and the daily check."""
    folder = Path(data_dir) / "backups"
    if folder.exists():
        for p in folder.iterdir():
            if p.is_dir():
                _remember_check(data_dir, p.name, verify_backup(p, full=True))
    return list_backups(data_dir)


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
    """Keep the newest N *usable* backups of each kind; keep the newest 2 unusable ones of each kind to look at; and never
    delete the newest usable backup of all, whatever its kind."""
    backups = list_backups(data_dir)
    if not backups:
        return
    usable = [b for b in backups if b["usable"]]
    protect = {usable[0]["name"]} if usable else set()
    for kind, keep in KEEP.items():
        mine = [b for b in backups if b["kind"] == kind]
        good = [b for b in mine if b["usable"]]
        bad = [b for b in mine if not b["usable"]]
        for b in good[keep:] + bad[2:]:
            if b["name"] not in protect:
                shutil.rmtree(Path(data_dir) / "backups" / b["name"], ignore_errors=True)


def list_backups(data_dir: Path) -> list[dict]:
    """Newest first. 'usable' combines a quick look now with the last full check."""
    folder = Path(data_dir) / "backups"
    if not folder.exists():
        return []
    cache = _check_cache(data_dir)
    out = []
    for p in sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        db = p / DB_NAME
        quick = verify_backup(p, full=False)
        last = cache.get(p.name)
        status = quick["status"] if quick["status"] != USABLE else (last["status"] if last else USABLE)
        info_file = p / "backup_info.json"
        try:
            info = json.loads(info_file.read_text(encoding="utf-8")) if info_file.exists() else (_summary(db) if status == USABLE else {})
        except (OSError, ValueError, sqlite3.Error):
            info = {}
        try:
            when = datetime.strptime(p.name[:17], "%Y-%m-%d %H%M%S").isoformat()
        except ValueError:
            when = None
        out.append({"name": p.name, "kind": _kind(p.name), "made_at": when, "has_database": db.exists(),
                    "status": status, "status_text": STATUS_TEXT[status], "usable": status == USABLE, "ok": status == USABLE,
                    "problems": (quick["problems"] or (last or {}).get("problems") or [])[:5],
                    "last_full_check": (last or {}).get("checked_at"), "legacy": quick.get("legacy", False),
                    "counts": info.get("counts", {}), "size_mb": round(db.stat().st_size / 2**20, 2) if db.exists() else 0})
    return out


def backup_summary(data_dir: Path) -> dict:
    """For Home, Settings and System health: last good backup, whether the newest passed, and whether any usable one exists."""
    bl = list_backups(data_dir)
    usable = [b for b in bl if b["usable"]]
    newest = bl[0] if bl else None
    has_data = (Path(data_dir) / DB_NAME).exists()
    return {"count": len(bl), "usable_count": len(usable), "last_good": usable[0] if usable else None, "newest": newest,
            "newest_ok": bool(newest and newest["usable"]),
            "warning": None if usable or not has_data else "You have no usable backup. Click 'Back up now' in Settings > Your data."}


def daily_backup_if_due(data_dir: Path, now: datetime | None = None) -> dict | None:
    now = now or datetime.now()
    for b in list_backups(data_dir):
        if b["kind"] in ("daily", "manual", "before upgrade") and b["usable"] and b["made_at"]:
            if now - datetime.fromisoformat(b["made_at"]) < DAILY_EVERY:
                return None
            break
    r = backup_now(data_dir, "daily", now, include_files=False)
    try:
        verify_all(data_dir)        # once a day, re-read every backup so a damaged one is noticed before it's needed
    except Exception:  # noqa: BLE001
        log.exception("backup check failed")
    return r


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
        p = Path(data_dir) / "backups" / str(backup or "")
        if not backup or "/" in backup or "\\" in backup or not p.is_dir():
            raise ValueError("That backup doesn't exist.")
        v = verify_backup(p, full=True)
        _remember_check(data_dir, p.name, v)
        if v["status"] != USABLE:
            raise ValueError(f"That backup can't be restored: {STATUS_TEXT[v['status']]}")
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


def _db_files(data_dir: Path) -> list[Path]:
    return [p for p in Path(data_dir).glob(DB_NAME + "*") if p.is_file()]


def _move_aside(data_dir: Path, folder: str, now: datetime) -> Path | None:
    """Move the database and its -wal/-shm files to <folder>/<time>/. Returns where, or None if there was nothing."""
    files = _db_files(data_dir)
    if not files:
        return None
    dest = Path(data_dir) / folder / now.strftime("%Y-%m-%d %H%M%S")
    n = 1
    while dest.exists():
        n += 1
        dest = dest.with_name(f"{now.strftime('%Y-%m-%d %H%M%S')} {n}")
    dest.mkdir(parents=True)
    for p in files:
        shutil.move(str(p), str(dest / p.name))
    return dest


def _move_back(moved: Path | None, data_dir: Path) -> bool:
    """Undo _move_aside after a failure, so you end up exactly where you started."""
    if not moved or not moved.exists():
        return False
    for p in _db_files(data_dir):          # whatever half-finished file is there now
        p.unlink(missing_ok=True)
    for p in moved.iterdir():
        shutil.move(str(p), str(Path(data_dir) / p.name))
    moved.rmdir()
    return True


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
                dst.rollback()          # the table itself stays (empty) so the app still finds it; it's reported as lost
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


def apply_pending(data_dir: Path, now: datetime | None = None, _fail_after_move: bool = False) -> dict | None:
    """Run a scheduled restore/rescue/fresh start. Called at start-up before the database is opened. Never raises.
    Order for restore and rescue: build and check the new file first, then move the current one aside, then put the new one in
    place. If anything fails after the move, the original is moved back, so a failure never leaves you with less than before."""
    data_dir = Path(data_dir)
    plan = pending(data_dir)
    if not plan:
        return None
    now = now or datetime.now()
    db = data_dir / DB_NAME
    tmp = data_dir / "incoming-data.tmp"                   # not named study_terminal.db*, so moving the old file leaves it
    result = {"action": plan["action"], "backup": plan.get("backup"), "done_at": now.isoformat(timespec="seconds"),
              "ok": False, "moved_to": None, "safety_backup": None, "rolled_back": False, "detail": ""}
    moved = None
    try:
        damaged = check_database(db) is not None
        if plan["action"] in ("restore", "rescue"):
            tmp.unlink(missing_ok=True)
            if plan["action"] == "restore":
                folder = data_dir / "backups" / str(plan.get("backup"))
                v = verify_backup(folder, full=True)
                if folder.is_dir():
                    _remember_check(data_dir, folder.name, v, now)      # so the list shows it as damaged from now on
                if v["status"] != USABLE:
                    raise RuntimeError(f"the backup didn't pass its check ({STATUS_TEXT[v['status']]})")
                shutil.copy2(folder / DB_NAME, tmp)
                what = f"Restored your data from the backup made {when_text(plan['backup'])}."
            else:
                if not db.exists():
                    raise RuntimeError("there's no data file to rescue")
                r = rescue_into(db, tmp)
                if not r["saved"]:
                    raise RuntimeError("nothing could be read from the damaged file")
                result["rescued"] = r
                what = (f"Rescued {len(r['saved'])} of {len(r['saved']) + len(r['lost'])} parts of your data."
                        + (f" Couldn't read: {', '.join(r['lost'])}." if r["lost"] else ""))
            if check_database(tmp) is not None:
                raise RuntimeError("the new data file didn't pass its check")
            if db.exists() and not damaged and plan["action"] == "restore":   # a good current file is kept as a backup too
                sb = backup_now(data_dir, "before restore", now, include_files=False)
                if not sb.get("made"):
                    raise RuntimeError(f"couldn't back up your current data first ({sb.get('error')})")
                result["safety_backup"] = sb.get("name")
            moved = _move_aside(data_dir, "damaged" if damaged else "replaced", now)
            if _fail_after_move:
                raise OSError("simulated failure while putting the new file in place")
            tmp.replace(db)
            if check_database(db) is not None:
                raise RuntimeError("the data file didn't pass its check after it was put in place")
            result.update(ok=True, moved_to=str(moved) if moved else None, detail=what)
        else:   # fresh
            moved = _move_aside(data_dir, "damaged" if damaged else "replaced", now)
            result.update(ok=True, moved_to=str(moved) if moved else None,
                          detail="Started with empty data. Your old data file was kept, not deleted.")
    except Exception as e:  # noqa: BLE001
        (log.info if _fail_after_move else log.exception)("recovery action failed: %s", e)
        try:
            result["rolled_back"] = _move_back(moved, data_dir)
        except Exception:  # noqa: BLE001
            log.exception("moving the original back failed")
            result["detail_extra"] = f"Your original file is in {moved}."
        result["detail"] = (f"That didn't work: {e}. "
                            + ("Your data was put back exactly as it was. " if result["rolled_back"]
                               else "Your data wasn't touched. " if moved is None else "")
                            + "Nothing was deleted.")
    finally:
        tmp.unlink(missing_ok=True)
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
        for name in ("installed_build.txt", "visual_profiles.json", "running.marker", LAST, "startup_history.json",
                     "recovery_self_check.json", "backups/checks.json"):
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


# ---------------- startup history and recent errors (for System health) ----------------

STARTS = "startup_history.json"


def record_start(data_dir: Path, mode: str, version: str, now: datetime | None = None) -> None:
    """mode: normal | recovery. Keeps the last good (normal) start and the last 20 starts."""
    f = Path(data_dir) / STARTS
    try:
        h = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        h = {}
    at = (now or datetime.now()).isoformat(timespec="seconds")
    h["starts"] = ([{"at": at, "mode": mode, "version": version}] + h.get("starts", []))[:20]
    if mode == "normal":
        h["last_ok"] = {"at": at, "version": version}
    try:
        f.write_text(json.dumps(h, indent=1), encoding="utf-8")
    except OSError:
        log.warning("couldn't write the startup history")


def startup_history(data_dir: Path) -> dict:
    f = Path(data_dir) / STARTS
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except (OSError, ValueError):
        return {}


def recent_errors(data_dir: Path, limit: int = 12, secrets: list[str] | None = None, since_hours: float = 72) -> list[dict]:
    """The newest ERROR lines from the app's logs (first line of each; tracebacks are in the help file)."""
    out = []
    cutoff = datetime.now() - timedelta(hours=since_hours)
    for name in ("study_terminal.log", "desktop.log"):
        p = Path(data_dir) / "logs" / name
        if not p.exists():
            continue
        try:
            tail = p.read_bytes()[-2 * 2**20:].decode("utf-8", "replace").splitlines()
        except OSError:
            continue
        for line in tail:
            if " ERROR " not in line[:40] and " CRITICAL " not in line[:45]:
                continue
            try:
                at = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            if at < cutoff:
                continue
            msg = _scrub(line[19:].split("ERROR", 1)[-1].strip(" -:"), secrets or [])
            out.append({"at": at.isoformat(), "where": name, "text": msg[:300]})
    out.sort(key=lambda x: x["at"], reverse=True)
    return out[:limit]


# ---------------- recovery self-check on this computer ----------------

SELF_CHECK = "recovery_self_check.json"


def self_check(data_dir: Path, version: str = "") -> dict:
    """Runs every recovery action on a SCRATCH copy, in a folder on the same disk as your data, and checks the result:
    backup + read-back check, restore, restore over a damaged file, rescue of a partly damaged file, a failed restore rolling
    back, and detection of a damaged backup. Your real data file is only read (SQLite's own backup copy) and never changed.
    Results are saved and included in the help file, so they can count as evidence from YOUR computer."""
    data_dir = Path(data_dir)
    scratch = data_dir / "selfcheck-scratch"
    shutil.rmtree(scratch, ignore_errors=True)
    scratch.mkdir(parents=True)
    steps: list[dict] = []

    def step(name: str, fn):
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        steps.append({"step": name, "ok": bool(ok), "detail": detail})
        return ok

    def journal_count(p: Path) -> int:
        con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
        try:
            return con.execute("select count(*) from st_selfcheck").fetchone()[0]
        finally:
            con.close()

    db = scratch / DB_NAME
    t = datetime.now()
    try:
        def seed():
            if (data_dir / DB_NAME).exists() and check_database(data_dir / DB_NAME) is None:
                _copy_db(data_dir / DB_NAME, db)              # a copy of your real data, so the check uses its real size
                src = "a copy of your data"
            else:
                sqlite3.connect(db).close()
                src = "an empty test file (your data file isn't readable)"
            con = sqlite3.connect(db)
            con.execute("pragma journal_mode=delete")
            con.execute("drop table if exists st_selfcheck")
            con.execute("create table st_selfcheck (id integer primary key, note text)")
            con.executemany("insert into st_selfcheck (note) values (?)", [("check",)] * 5)
            con.commit()
            con.close()
            return True, f"Scratch file made from {src}."
        step("Make a scratch copy", seed)

        name = {}

        def backup():
            r = backup_now(scratch, "manual", t, include_files=False)
            name["b"] = r.get("name")
            return r.get("made") and r.get("verified"), "Backup made and read back." if r.get("made") else r.get("error")
        step("Back up and check the backup can be opened", backup)

        def restore():
            con = sqlite3.connect(db)
            con.execute("insert into st_selfcheck (note) values ('after backup')")
            con.commit()
            con.close()
            schedule(scratch, "restore", name["b"])
            r = apply_pending(scratch, t + timedelta(seconds=1))
            return r["ok"] and journal_count(db) == 5 and r["safety_backup"], r["detail"]
        step("Restore a backup (your current data is backed up first)", restore)

        def restore_damaged():
            with open(db, "r+b") as f:
                f.write(b"X" * 100)
            schedule(scratch, "restore", name["b"])
            r = apply_pending(scratch, t + timedelta(seconds=2))
            return r["ok"] and journal_count(db) == 5 and r["moved_to"] and "damaged" in r["moved_to"], r["detail"]
        step("Restore over a damaged data file", restore_damaged)

        def rescue():
            con = sqlite3.connect(db)
            con.execute("drop table if exists st_selfcheck_filler")
            con.execute("create table st_selfcheck_filler (id integer primary key, b text)")
            con.executemany("insert into st_selfcheck_filler (b) values (?)", [("x" * 2500,)] * 120)
            con.commit()
            con.close()
            size = db.stat().st_size
            with open(db, "r+b") as f:                         # wreck the last pages (the filler table's)
                f.seek(max(0, size - 4096 * 12))
                f.write(os.urandom(4096 * 10))
            if check_database(db) is None:
                return False, "The test damage wasn't detected."
            schedule(scratch, "rescue")
            r = apply_pending(scratch, t + timedelta(seconds=3))
            return r["ok"] and journal_count(db) == 5, r["detail"]
        step("Rescue a partly damaged file", rescue)

        def rollback():
            before = db.read_bytes()
            schedule(scratch, "restore", name["b"])
            r = apply_pending(scratch, t + timedelta(seconds=4), _fail_after_move=True)
            return (not r["ok"]) and r["rolled_back"] and db.read_bytes() == before, r["detail"]
        step("A failed restore puts everything back", rollback)

        def bad_backup():
            p = scratch / "backups" / name["b"] / DB_NAME
            with open(p, "r+b") as f:
                f.write(b"Y" * 100)
            v = verify_backup(p.parent, full=True)
            try:
                schedule(scratch, "restore", name["b"])
                refused = False
            except ValueError:
                refused = True
            return v["status"] == DAMAGED and refused, f"Damaged backup detected ({STATUS_TEXT[v['status']]}) and refused."
        step("A damaged backup is noticed and refused", bad_backup)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    import platform
    res = {"ran_at": datetime.now().isoformat(timespec="seconds"), "version": version,
           "computer": {"system": platform.system(), "release": platform.release(), "version": platform.version(),
                        "frozen_app": bool(getattr(sys, "frozen", False))},
           "passed": all(s["ok"] for s in steps) and len(steps) == 7, "steps": steps,
           "note": "Ran on this computer, on a scratch copy. Your real data file was only read."}
    try:
        (data_dir / SELF_CHECK).write_text(json.dumps(res, indent=1), encoding="utf-8")
    except OSError:
        pass
    return res


def last_self_check(data_dir: Path) -> dict | None:
    f = Path(data_dir) / SELF_CHECK
    try:
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None
    except (OSError, ValueError):
        return None
