"""Looking after the data folder without a terminal: damaged-file detection, Recovery mode, backups, restore, rescue, a fresh
start, the help file, and moving to a free port. Real files on disk in a temp folder; nothing here is evidence about your PC."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from app import datacare as dc
from app.main import create_app

from .test_futures_api import FutProvider, always_open_clock


def make_db(path: Path, trades: int = 3) -> None:
    con = sqlite3.connect(path)
    con.execute("create table journal_trades (id integer primary key, note text)")
    con.execute("create table paper_orders (id integer primary key, sym text)")
    con.executemany("insert into journal_trades (note) values (?)", [(f"t{i}",) for i in range(trades)])
    con.execute("insert into paper_orders (sym) values ('MNQ')")
    con.commit()
    con.close()


def damage(path: Path) -> None:
    with open(path, "r+b") as f:
        f.seek(0)
        f.write(b"X" * 100)


def test_check_database(tmp_path):
    db = tmp_path / dc.DB_NAME
    assert dc.check_database(db) is None                      # not created yet: fine
    db.write_bytes(b"")
    assert "empty" in dc.check_database(db)
    db.unlink()
    make_db(db)
    assert dc.check_database(db) is None
    damage(db)
    assert "not a database" in dc.check_database(db)


def test_backup_now_lists_whats_inside_and_never_copies_secrets(tmp_path):
    make_db(tmp_path / dc.DB_NAME, trades=4)
    (tmp_path / ".env").write_text("STUDY_PROJECTX_API_KEY=supersecretvalue")
    (tmp_path / "visual_profiles.json").write_text("{}")
    r = dc.backup_now(tmp_path, "manual")
    assert r["made"] and r["ok"] and r["counts"] == {"journal trades": 4, "practice orders": 1}
    dest = Path(r["path"])
    assert (dest / "visual_profiles.json").exists() and not (dest / ".env").exists()
    b = dc.list_backups(tmp_path)[0]
    assert b["kind"] == "manual" and b["ok"] and b["counts"]["journal trades"] == 4
    damage(tmp_path / dc.DB_NAME)                              # a damaged file is never copied over as a "backup"
    r2 = dc.backup_now(tmp_path, "manual")
    assert not r2["made"] and "damaged" in r2["error"]


def test_each_kind_keeps_its_own_count(tmp_path):
    make_db(tmp_path / dc.DB_NAME)
    t = datetime(2026, 11, 1, 9, 0)
    upg = tmp_path / "backups" / "2026-10-01 090000 before 0.13.2"
    upg.mkdir(parents=True)
    dc._copy_db(tmp_path / dc.DB_NAME, upg / dc.DB_NAME)
    for i in range(9):
        dc.backup_now(tmp_path, "daily", t + timedelta(days=i), include_files=False)
    for i in range(7):
        dc.backup_now(tmp_path, "before restore", t + timedelta(days=i, hours=1), include_files=False)
    kinds = [b["kind"] for b in dc.list_backups(tmp_path)]
    assert kinds.count("daily") == 7 and kinds.count("before restore") == 5 and kinds.count("before upgrade") == 1


def test_daily_backup_only_when_due(tmp_path):
    make_db(tmp_path / dc.DB_NAME)
    t = datetime(2026, 11, 10, 18, 0)
    assert dc.daily_backup_if_due(tmp_path, t)["made"]
    assert dc.daily_backup_if_due(tmp_path, t + timedelta(hours=5)) is None
    assert dc.daily_backup_if_due(tmp_path, t + timedelta(hours=21))["made"]


def test_restore_keeps_current_data_and_moves_it_aside(tmp_path):
    db = tmp_path / dc.DB_NAME
    make_db(db, trades=2)
    name = dc.backup_now(tmp_path, "manual", datetime(2026, 11, 12, 18, 0))["name"]
    con = sqlite3.connect(db)
    con.execute("insert into journal_trades (note) values ('after backup')")
    con.commit()
    con.close()
    try:
        dc.schedule(tmp_path, "restore", "nope")
        raise AssertionError("unknown backup accepted")
    except ValueError:
        pass
    dc.schedule(tmp_path, "restore", name)
    r = dc.apply_pending(tmp_path, datetime(2026, 11, 13, 9, 0))
    assert r["ok"] and r["safety_backup"] and "Nov 12, 6:00 PM" in r["detail"]
    assert sqlite3.connect(db).execute("select count(*) from journal_trades").fetchone()[0] == 2
    replaced = Path(r["moved_to"])
    assert replaced.parent.name == "replaced" and (replaced / dc.DB_NAME).exists()   # nothing deleted
    assert dc.pending(tmp_path) is None and dc.last_recovery(tmp_path)["ok"]


def test_restore_over_a_damaged_file(tmp_path):
    db = tmp_path / dc.DB_NAME
    make_db(db)
    name = dc.backup_now(tmp_path, "manual")["name"]
    damage(db)
    dc.schedule(tmp_path, "restore", name)
    r = dc.apply_pending(tmp_path)
    assert r["ok"] and r["safety_backup"] is None and Path(r["moved_to"]).parent.name == "damaged"
    assert dc.check_database(db) is None


def test_bad_backup_cant_be_restored(tmp_path):
    make_db(tmp_path / dc.DB_NAME)
    name = dc.backup_now(tmp_path, "manual")["name"]
    damage(tmp_path / "backups" / name / dc.DB_NAME)
    try:
        dc.schedule(tmp_path, "restore", name)
        raise AssertionError("damaged backup accepted")
    except ValueError as e:
        assert "can't be restored" in str(e) and "Damaged" in str(e)


def test_incomplete_missing_and_damaged_backups_are_detected(tmp_path):
    make_db(tmp_path / dc.DB_NAME)
    (tmp_path / "visual_profiles.json").write_text('{"a": 1}')
    good = dc.backup_now(tmp_path, "manual", datetime(2026, 11, 1, 9, 0))
    assert good["made"] and good["verified"]
    b = tmp_path / "backups"
    inc = b / "2026-11-02 090000 manual"                       # the app closed while a backup was being made
    inc.mkdir()
    (inc / ".in-progress").write_text("x")
    dc._copy_db(tmp_path / dc.DB_NAME, inc / dc.DB_NAME)
    miss = dc.backup_now(tmp_path, "manual", datetime(2026, 11, 3, 9, 0))
    (b / miss["name"] / "visual_profiles.json").unlink()
    bad = dc.backup_now(tmp_path, "manual", datetime(2026, 11, 4, 9, 0))
    (b / bad["name"] / "visual_profiles.json").write_text('{"a": 2}')      # same size, different bytes
    st = {x["name"]: x["status"] for x in dc.verify_all(tmp_path)}
    assert st[good["name"]] == dc.USABLE and st[inc.name] == dc.INCOMPLETE
    assert st[miss["name"]] == dc.MISSING and st[bad["name"]] == dc.DAMAGED
    s = dc.backup_summary(tmp_path)
    assert s["last_good"]["name"] == good["name"] and not s["newest_ok"] and s["warning"] is None


def test_no_usable_backup_warns(tmp_path):
    make_db(tmp_path / dc.DB_NAME)
    assert "no usable backup" in dc.backup_summary(tmp_path)["warning"]


def test_pruning_never_removes_the_last_usable_backup(tmp_path):
    make_db(tmp_path / dc.DB_NAME)
    t = datetime(2026, 11, 1, 9, 0)
    only = dc.backup_now(tmp_path, "daily", t, include_files=False)["name"]
    for i in range(1, 10):                                     # nine newer daily backups that all turn out damaged
        n = dc.backup_now(tmp_path, "daily", t + timedelta(days=i), include_files=False)["name"]
        damage(tmp_path / "backups" / n / dc.DB_NAME)
        dc._remember_check(tmp_path, n, dc.verify_backup(tmp_path / "backups" / n))
    dc.prune(tmp_path)
    names = [x["name"] for x in dc.list_backups(tmp_path)]
    assert only in names and dc.backup_summary(tmp_path)["last_good"]["name"] == only
    assert len(names) == 3                                     # the usable one + the newest 2 damaged ones to look at


def test_failed_restore_rolls_back_to_exactly_what_you_had(tmp_path):
    db = tmp_path / dc.DB_NAME
    make_db(db, trades=2)
    name = dc.backup_now(tmp_path, "manual", datetime(2026, 11, 12, 18, 0))["name"]
    con = sqlite3.connect(db)
    con.execute("insert into journal_trades (note) values ('newer')")
    con.commit()
    con.close()
    before = db.read_bytes()
    dc.schedule(tmp_path, "restore", name)
    r = dc.apply_pending(tmp_path, datetime(2026, 11, 13, 9, 0), _fail_after_move=True)
    assert not r["ok"] and r["rolled_back"] and "put back exactly" in r["detail"]
    assert db.read_bytes() == before and not (tmp_path / "incoming-data.tmp").exists()


def test_backup_damaged_after_it_was_picked_changes_nothing(tmp_path):
    db = tmp_path / dc.DB_NAME
    make_db(db, trades=2)
    name = dc.backup_now(tmp_path, "manual")["name"]
    dc.schedule(tmp_path, "restore", name)
    damage(tmp_path / "backups" / name / dc.DB_NAME)           # damaged between choosing it and the restart
    before = db.read_bytes()
    r = dc.apply_pending(tmp_path)
    assert not r["ok"] and "didn't pass its check" in r["detail"] and db.read_bytes() == before


def test_rescue_saves_the_readable_parts(tmp_path):
    db = tmp_path / dc.DB_NAME
    con = sqlite3.connect(db)
    con.execute("pragma page_size=4096")
    con.execute("create table journal_trades (id integer primary key, note text)")
    con.execute("insert into journal_trades (note) values ('keep me')")
    con.execute("create table bars (id integer primary key, blob text)")
    con.executemany("insert into bars (blob) values (?)", [("x" * 3000,) for _ in range(60)])
    con.commit()
    con.close()
    with open(db, "r+b") as f:                                 # wreck pages that belong to the big table
        f.seek(4096 * 20)
        f.write(os.urandom(4096 * 6))
    assert dc.check_database(db) is not None
    dc.schedule(tmp_path, "rescue")
    r = dc.apply_pending(tmp_path)
    assert r["ok"] and r["rescued"]["saved"].get("journal_trades") == 1 and "bars" in r["rescued"]["lost"]
    assert sqlite3.connect(db).execute("select note from journal_trades").fetchone()[0] == "keep me"
    assert (Path(r["moved_to"]) / dc.DB_NAME).exists()


def test_fresh_start_keeps_the_old_file(tmp_path):
    make_db(tmp_path / dc.DB_NAME)
    damage(tmp_path / dc.DB_NAME)
    dc.schedule(tmp_path, "fresh")
    r = dc.apply_pending(tmp_path)
    assert r["ok"] and not (tmp_path / dc.DB_NAME).exists() and (Path(r["moved_to"]) / dc.DB_NAME).exists()


def test_help_file_has_what_is_needed_and_no_secrets(tmp_path):
    make_db(tmp_path / dc.DB_NAME)
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "study_terminal.log").write_text("started; key=supersecretvalue123\n")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=supersecretvalue123")
    (tmp_path / "chart_checks").mkdir()
    (tmp_path / "chart_checks" / "results.jsonl").write_text('{"step": "price"}\n')
    (tmp_path / "chart_checks" / "0123456789ab.jpg").write_bytes(b"\xff\xd8jpeg")
    out = tmp_path / "out"
    p = dc.make_help_file(tmp_path, ["supersecretvalue123"], {"version": "x"}, dest_dir=out)
    z = zipfile.ZipFile(p)
    names = set(z.namelist())
    assert {"about.json", "logs/study_terminal.log", "chart_checks/results.jsonl", "chart_checks/0123456789ab.jpg"} <= names
    assert ".env" not in names and dc.DB_NAME not in names
    assert all(b"supersecretvalue123" not in z.read(n) for n in names)
    assert json.loads(z.read("about.json"))["database_check"] == "ok"
    p2 = dc.make_help_file(tmp_path, [], include_database=True, dest_dir=out, now=datetime(2026, 1, 1))
    assert dc.DB_NAME in zipfile.ZipFile(p2).namelist()


async def _start(settings):
    settings.anthropic_api_key = None
    app = create_app(settings, provider=FutProvider(), clock=always_open_clock(), start_loops=False)
    app.state.help_dir = settings.data_dir / "downloads"
    return app


async def test_damaged_file_opens_recovery_mode_and_restore_works_through_the_app(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app = await _start(settings)
    async with app.router.lifespan_context(app):                # first start creates real data
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"X-Study-Terminal": "1"}) as c:
            assert (await c.put("/api/settings", json={"risk.max_per_trade_pct": 0.37})).status_code == 200
            assert not (settings.data_dir / "backups").exists()  # a brand-new folder isn't backed up
            b = (await c.post("/api/data/backup")).json()
            assert b["made"]
    damage(settings.data_dir / dc.DB_NAME)
    app = await _start(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"X-Study-Terminal": "1"}) as c:
            h = (await c.get("/api/health")).json()
            assert h["recovery"]["kind"] == "database" and h["database_ok"] is False
            assert (await c.get("/api/settings")).status_code == 503           # nothing else runs on a damaged file
            st = (await c.get("/api/data/status")).json()
            assert st["recovery"] and st["last_backup"]["name"] == b["name"]
            assert (await c.post("/api/data/backup")).status_code == 409        # a damaged file isn't backed up
            assert (await c.post("/api/data/schedule", json={"action": "restore", "backup": b["name"]})).status_code == 400
            r = await c.post("/api/data/schedule", json={"action": "restore", "backup": b["name"], "confirm": True})
            assert r.json()["restart_requested"] and (await c.get("/api/data/status")).json()["restart_requested"]
            hf = (await c.post("/api/data/help-file", json={})).json()          # works in Recovery mode too
            assert Path(hf["path"]).exists()
    app = await _start(settings)                                # the restart: restore happens before the data is opened
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"X-Study-Terminal": "1"}) as c:
            assert "recovery" not in (await c.get("/api/health")).json()
            assert (await c.get("/api/settings")).json()["values"]["risk.max_per_trade_pct"] == 0.37
            st = (await c.get("/api/data/status")).json()
            assert st["recovery"] is None and st["last_recovery"]["ok"] and not st["restart_requested"]
            assert any((settings.data_dir / "damaged").iterdir())                # the damaged file was kept
            await c.post("/api/data/dismiss-last")
            assert (await c.get("/api/data/status")).json()["last_recovery"] is None


async def test_unwritable_folder_opens_recovery_mode(settings, monkeypatch):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(dc, "check_disk", lambda d, write_test=True: {"writable": False, "free_mb": 12, "low_space": True,
                                                                       "error": "PermissionError: denied"})
    app = await _start(settings)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"X-Study-Terminal": "1"}) as c:
            rec = (await c.get("/api/health")).json()["recovery"]
            assert rec["kind"] == "disk" and "denied" in rec["problem"]


def test_launcher_moves_to_a_free_port_when_ours_is_taken(tmp_path):
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    root = Path(__file__).resolve().parents[2]
    code = ("import sys; sys.path[:0] = [r'%s', r'%s']; import launcher; p = launcher.choose_port(); "
            "print(p, launcher.S.port, launcher.API)") % (root / "desktop", root / "backend")
    env = {**os.environ, "STUDY_TERMINAL_DATA_DIR": str(tmp_path), "STUDY_TERMINAL_NO_ENV_FILE": "1", "PORT": str(port)}
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=120)
    blocker.close()
    new, s_port, api = out.stdout.split()
    assert int(new) != port and int(s_port) == int(new) and api.endswith(f":{new}/api"), out.stderr[-500:]
