"""Automatic backup before an upgrade.

The first time a new build starts on an existing data folder, the database and the data files are copied to
<data dir>/backups/<timestamp> before <build>/ before the database is opened. Originals are only read.
A failed backup is reported and never stops the app from starting.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
MARKER = "installed_build.txt"
KEEP = 10
SKIP_DIRS = {"backups", "logs", "models", "__pycache__"}
DB_NAME = "study_terminal.db"


def _copy_db(src: Path, dst: Path) -> None:
    """Consistent copy of a SQLite file (includes anything still in the write-ahead log)."""
    a = sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True)
    try:
        b = sqlite3.connect(dst)
        try:
            a.backup(b)
        finally:
            b.close()
    finally:
        a.close()


def backup_before_upgrade(data_dir: Path, build: str, now: datetime | None = None) -> dict:
    """Returns {"made": bool, "path": str | None, "previous": str | None, "error": str | None}."""
    data_dir = Path(data_dir)
    marker = data_dir / MARKER
    previous = marker.read_text(encoding="utf-8").strip() if marker.exists() else None
    out = {"made": False, "path": None, "previous": previous, "error": None}
    if previous == build:
        return out
    db = data_dir / DB_NAME
    try:
        if db.exists():                                   # an existing installation: copy before anything is opened
            from .datacare import backup_now               # same verified backup as every other kind (file list, read-back check)
            safe = "".join(c if c.isalnum() or c in ".-_ " else "_" for c in build)
            r = backup_now(data_dir, f"before {safe}", now or datetime.now(), include_files=True)
            if not r.get("made"):
                raise RuntimeError(r.get("error") or "backup failed")
            dest = Path(r["path"])
            (dest / "README.txt").write_text(
                f"Study Terminal data as it was before the first start of build {build} (previous build: {previous or 'unknown'}).\n"
                "To restore it, use Settings > Your data > Restore in Study Terminal.\n", encoding="utf-8")
            out.update(made=True, path=str(dest))
        marker.write_text(build, encoding="utf-8")       # only after a successful (or unnecessary) backup
    except Exception as e:  # noqa: BLE001 - a backup problem must never stop the app
        out["error"] = f"{type(e).__name__}: {e}"
        log.exception("backup before upgrade failed")
    return out


def _prune(folder: Path) -> None:
    from .datacare import prune   # one place decides how many of each kind of backup are kept
    prune(folder.parent)


def list_backups(data_dir: Path) -> list[dict]:
    folder = Path(data_dir) / "backups"
    if not folder.exists():
        return []
    return [{"name": p.name, "path": str(p)} for p in sorted(folder.iterdir(), reverse=True) if p.is_dir()]
