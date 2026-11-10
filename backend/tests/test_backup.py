"""Automatic backup before an upgrade: originals are only read, a failure never blocks start-up."""
import hashlib
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from app.backup import KEEP, MARKER, backup_before_upgrade, list_backups
from app.main import create_app

from .fakes import FakeProvider, always_open_clock


def _seed(d: Path) -> dict:
    d.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(d / "study_terminal.db")
    con.execute("create table journal_notes (id integer primary key, text text)")
    con.executemany("insert into journal_notes (text) values (?)", [("first trade",), ("second trade",)])
    con.commit()
    con.close()
    (d / "visual_profiles.json").write_text('[{"name": "My MNQ"}]')
    (d / "calibration").mkdir()
    (d / "calibration" / "results.jsonl").write_text('{"id": "a"}\n')
    (d / "logs").mkdir()
    (d / "logs" / "study_terminal.log").write_text("log line")
    (d / ".env").write_text("TOPSTEPX_API_KEY=secret")
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.rglob("*")) if p.is_file()}


def test_fresh_folder_makes_no_backup(tmp_path):
    r = backup_before_upgrade(tmp_path, "build-1")
    assert r == {"made": False, "path": None, "previous": None, "error": None}
    assert (tmp_path / MARKER).read_text() == "build-1" and not (tmp_path / "backups").exists()


def test_existing_data_is_copied_and_originals_are_untouched(tmp_path):
    before = _seed(tmp_path)
    r = backup_before_upgrade(tmp_path, "0.12.0 preview 1", now=datetime(2026, 11, 10, 9, 30))
    assert r["made"] and r["error"] is None and r["previous"] is None
    dest = Path(r["path"])
    assert dest.name == "2026-11-10 093000 before 0.12.0 preview 1"
    con = sqlite3.connect(dest / "study_terminal.db")
    assert [x[0] for x in con.execute("select text from journal_notes order by id")] == ["first trade", "second trade"]
    con.close()
    assert (dest / "visual_profiles.json").read_text() == '[{"name": "My MNQ"}]'
    assert (dest / "calibration" / "results.jsonl").exists() and (dest / "README.txt").exists()
    assert not (dest / ".env").exists() and not (dest / "logs").exists()            # credentials and logs are never copied
    after = {k: v for k, v in ((str(p.relative_to(tmp_path)), hashlib.sha256(p.read_bytes()).hexdigest())
                               for p in sorted(tmp_path.rglob("*")) if p.is_file()) if not k.startswith("backups") and k != MARKER}
    assert after == before


def test_one_backup_per_build(tmp_path):
    _seed(tmp_path)
    assert backup_before_upgrade(tmp_path, "b1", now=datetime(2026, 1, 1, 10))["made"]
    assert not backup_before_upgrade(tmp_path, "b1", now=datetime(2026, 1, 1, 11))["made"]
    r = backup_before_upgrade(tmp_path, "b2", now=datetime(2026, 1, 2, 10))
    assert r["made"] and r["previous"] == "b1" and len(list_backups(tmp_path)) == 2


def test_only_the_newest_backups_are_kept(tmp_path):
    _seed(tmp_path)
    t0 = datetime(2026, 1, 1)
    for i in range(KEEP + 3):
        assert backup_before_upgrade(tmp_path, f"b{i}", now=t0 + timedelta(days=i))["made"]
    names = [b["name"] for b in list_backups(tmp_path)]
    assert len(names) == KEEP and names[0].endswith(f"before b{KEEP + 2}") and not any(n.endswith("before b0") for n in names)


def test_a_failed_backup_reports_and_never_raises(tmp_path):
    before = _seed(tmp_path)
    (tmp_path / "backups").write_text("a file where the folder should be")
    r = backup_before_upgrade(tmp_path, "b1")
    assert not r["made"] and r["error"]
    assert not (tmp_path / MARKER).exists()                    # it will try again next start
    assert hashlib.sha256((tmp_path / "study_terminal.db").read_bytes()).hexdigest() == before["study_terminal.db"]


async def test_the_app_backs_up_existing_data_on_first_start_of_a_new_build(settings):
    app = create_app(settings, provider=FakeProvider(), clock=always_open_clock(), start_loops=False)
    async with app.router.lifespan_context(app):
        assert app.state.backup["made"] is False               # fresh folder: nothing to back up
    (settings.data_dir / MARKER).write_text("an older build")
    app = create_app(settings, provider=FakeProvider(), clock=always_open_clock(), start_loops=False)
    async with app.router.lifespan_context(app):
        b = app.state.backup
        assert b["made"] and b["previous"] == "an older build" and (Path(b["path"]) / "study_terminal.db").exists()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/api/home")).json()["backup"]["made"] is True
