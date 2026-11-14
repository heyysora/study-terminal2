"""Recovery drill: drives a real Study Terminal (the installed app on Windows, or the launcher from source) through its own API,
exactly as the buttons do, and checks the results on disk. Standard library only.

    python recovery_drill.py <app command...> --data <seeded data folder> --work <scratch folder> --port 8831 --out <results.json>

Steps: backup + read-back check, restore with the automatic restart, a damaged data file (Recovery mode -> restore), a partly
damaged file (Recovery mode -> rescue), a restore that fails (backup damaged after it was picked) changing nothing, the app's own
recovery check, and your journal/settings/practice accounts compared table by table before and after.
Prints RESULT|<check>|pass/fail|<detail> lines and writes the same to --out.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

USER_TABLES = ["journal_trades", "journal_notes", "paper_state", "paper_orders", "paper_fills", "settings", "futures_fills",
               "watchlists", "watchlist_symbols", "learning_progress"]
DB = "study_terminal.db"


def args():
    a = sys.argv[1:]
    i = a.index("--data")
    cmd = a[:i]
    opts = dict(zip(a[i::2], a[i + 1::2], strict=False))
    return cmd, Path(opts["--data"]), Path(opts["--work"]), int(opts.get("--port", "8831")), Path(opts["--out"])


CMD, SEED, WORK, PORT, OUT = args()
API = f"http://127.0.0.1:{PORT}/api"
RESULTS: list[dict] = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append({"check": name, "outcome": "pass" if ok else "fail", "detail": detail})
    print(f"RESULT|{name}|{'pass' if ok else 'fail'}|{detail}", flush=True)


def http(method: str, path: str, body: dict | None = None, timeout: float = 120) -> tuple[int, dict]:
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Study-Terminal": "1", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


class App:
    def __init__(self, data: Path):
        self.data, self.stop_file, self.proc, self.starts = data, data.parent / f"stop-{data.name}", None, 0

    def start(self) -> bool:
        self.stop_file.unlink(missing_ok=True)
        env = {**os.environ, "STUDY_TERMINAL_DATA_DIR": str(self.data), "STUDY_TERMINAL_NO_ENV_FILE": "1", "PORT": str(PORT)}
        self.proc = subprocess.Popen(CMD + ["--headless", "--stop-file", str(self.stop_file)], env=env,
                                     stdout=open(self.data.parent / f"app-{self.data.name}.log", "a"), stderr=subprocess.STDOUT)
        log = self.data.parent / f"app-{self.data.name}.log"
        t0 = time.time()
        while time.time() - t0 < 150:                     # the app says which port it ended up on
            lines = [x for x in log.read_text(errors="replace").splitlines() if x.startswith("headless: listening on")] if log.exists() else []
            if len(lines) > self.starts:
                global API
                API = f"http://127.0.0.1:{int(lines[-1].split()[-1])}/api"
                self.starts = len(lines)
                return wait_up(60)
            if self.proc.poll() is not None:
                return False
            time.sleep(0.3)
        return False

    def stop(self) -> bool:
        self.stop_file.write_text("stop")
        try:
            self.proc.wait(90)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return False
        return self.proc.returncode == 0


def wait_up(timeout: float) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            code, _ = http("GET", "/health", timeout=3)
            if code == 200:
                return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.5)
    return False


def wait_restarted(after: str, timeout: float = 120) -> tuple[bool, float, dict]:
    """After a fix is chosen the app restarts itself; wait until it's back with a result newer than `after`."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            code, st = http("GET", "/data/status", timeout=3)
            last = st.get("last_recovery") or {}
            if code == 200 and not st.get("restart_requested") and not st.get("pending") and last.get("done_at", "") > after:
                return True, round(time.time() - t0, 1), st
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(0.5)
    return False, round(time.time() - t0, 1), {}


def snapshot(db: Path) -> dict:
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        out = {}
        for t in USER_TABLES:
            if t in names:
                rows = sorted(json.dumps(r, default=str) for r in con.execute(f'select * from "{t}"'))
                out[t] = {"rows": len(rows), "hash": hashlib.sha256("\n".join(rows).encode()).hexdigest()[:16]}
        return out
    finally:
        con.close()


def diff(a: dict, b: dict) -> str:
    bad = [t for t in a if a[t] != b.get(t)]
    return "identical" if not bad else "different: " + ", ".join(f"{t} ({a[t]['rows']} vs {b.get(t, {}).get('rows')} rows)" for t in bad)


def damage_header(db: Path) -> None:
    with open(db, "r+b") as f:
        f.write(b"X" * 100)


def damage_partly(db: Path) -> None:
    """Adds a big throw-away table, then wrecks the last pages of the file (which belong to it). Everything else stays readable."""
    con = sqlite3.connect(db)
    con.execute("pragma journal_mode=delete")
    con.execute("drop table if exists zz_filler")
    con.execute("create table zz_filler (id integer primary key, b text)")
    con.executemany("insert into zz_filler (b) values (?)", [("x" * 2500,)] * 200)
    con.commit()
    con.close()
    size = db.stat().st_size
    with open(db, "r+b") as f:
        f.seek(size - 4096 * 15)
        f.write(os.urandom(4096 * 12))


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    (WORK.parent / f"app-{WORK.name}.log").unlink(missing_ok=True)
    shutil.copytree(SEED, WORK)
    for p in WORK.glob(DB + "-*"):
        p.unlink()
    db = WORK / DB
    s0 = snapshot(db)
    record("Seed data present", s0.get("journal_trades", {}).get("rows", 0) > 0,
           ", ".join(f"{t} {v['rows']}" for t, v in s0.items()))
    app = App(WORK)

    # 1. backup creation and read-back
    ok = app.start()
    code, b = http("POST", "/data/backup")
    bname = b.get("name")
    code2, lst = http("GET", "/data/backups")
    newest = (lst.get("backups") or [{}])[0]
    opened = False
    if bname:
        con = sqlite3.connect(f"file:{(WORK / 'backups' / bname / DB).as_posix()}?mode=ro", uri=True)
        opened = con.execute("pragma quick_check").fetchone()[0] == "ok" and snapshot(WORK / "backups" / bname / DB) == s0
        con.close()
    record("Backup creation", ok and code == 200 and b.get("verified") is True and newest.get("name") == bname and newest.get("usable"),
           f"made {bname}; app's own check: {newest.get('status_text')}")
    record("New backup opens and holds your data", opened, "opened separately with SQLite; journal/settings/practice tables match")

    # 2. restore + automatic restart
    http("PUT", "/settings", {"risk.max_per_trade_pct": 0.41})
    t = now_iso()
    code, _ = http("POST", "/data/schedule", {"action": "restore", "backup": bname, "confirm": True})
    back, secs, st = wait_restarted(t)
    _, sv = http("GET", "/settings")
    reverted = (sv.get("values") or {}).get("risk.max_per_trade_pct") != 0.41
    safety = [x for x in http("GET", "/data/backups")[1].get("backups", []) if x["kind"] == "before restore" and x["usable"]]
    record("Backup restoration", code == 200 and back and (st.get("last_recovery") or {}).get("ok") and reverted,
           (st.get("last_recovery") or {}).get("detail", "no result"))
    record("Automatic restart after restoration", back and st.get("recovery") is None,
           f"back up by itself in {secs} s, no window or clicks")
    record("Current data backed up before the restore", bool(safety), f"{len(safety)} 'before a restore' backup(s), usable")
    app.stop()
    record("Journals, settings and practice accounts after the restore", snapshot(db) == s0, diff(s0, snapshot(db)))

    # 3. corrupted data file
    damage_header(db)
    bad_hash = hashlib.sha256(db.read_bytes()).hexdigest()
    app.start()
    _, h = http("GET", "/health")
    in_rec = (h.get("recovery") or {}).get("kind") == "database"
    untouched = hashlib.sha256(db.read_bytes()).hexdigest() == bad_hash
    t = now_iso()
    code, _ = http("POST", "/data/schedule", {"action": "restore", "backup": bname, "confirm": True})
    back, secs, st = wait_restarted(t)
    _, h2 = http("GET", "/health")
    kept = any(hashlib.sha256(p.read_bytes()).hexdigest() == bad_hash for p in (WORK / "damaged").rglob(DB))
    record("Recovery from corrupted data", in_rec and untouched and back and (st.get("last_recovery") or {}).get("ok") and kept,
           f"Recovery mode: {in_rec}; damaged file untouched until chosen: {untouched}; restored and restarted in {secs} s; "
           f"damaged file kept in damaged\\: {kept}")
    record("Application startup after recovery (restore)", back and "recovery" not in h2 and h2.get("database_ok") is not False,
           "normal start, data file opens")
    app.stop()
    record("Your data after recovering from a corrupted file", snapshot(db) == s0, diff(s0, snapshot(db)))

    # 4. partly damaged data file -> rescue
    damage_partly(db)
    app.start()
    _, h = http("GET", "/health")
    in_rec = bool(h.get("recovery"))
    t = now_iso()
    http("POST", "/data/schedule", {"action": "rescue", "confirm": True})
    back, secs, st = wait_restarted(t)
    last = st.get("last_recovery") or {}
    lost = (last.get("rescued") or {}).get("lost", [])
    saved = (last.get("rescued") or {}).get("saved", {})
    _, h2 = http("GET", "/health")
    record("Partial data recovery (rescue)", in_rec and back and last.get("ok") and "zz_filler" in lost and "journal_trades" in saved,
           f"{last.get('detail')} (restarted in {secs} s)")
    record("Application startup after recovery (rescue)", back and "recovery" not in h2, "normal start after the rescue")
    app.stop()
    record("Your data after rescuing a partly damaged file", snapshot(db) == s0, diff(s0, snapshot(db)))

    # 5. failed restoration: the backup is damaged after it was picked, before the restart
    (WORK / "pending_recovery.json").write_text(json.dumps({"action": "restore", "backup": bname, "asked_at": now_iso()}))
    damage_header(WORK / "backups" / bname / DB)
    app.start()
    _, st = http("GET", "/data/status")
    last = st.get("last_recovery") or {}
    _, h = http("GET", "/health")
    record("Failed restoration changes nothing", not last.get("ok") and "didn't pass its check" in last.get("detail", "")
           and "recovery" not in h, last.get("detail", "no result"))
    _, s = http("GET", "/data/backups")
    shown = next((x for x in s.get("backups", []) if x["name"] == bname), {})
    record("Damaged backup is flagged", shown.get("status") == "damaged", f"listed as: {shown.get('status_text')}")

    # 6. the app's own recovery check on this machine (includes a restore that fails halfway and rolls back)
    code, sc = http("POST", "/system/self-check", timeout=300)
    record("Recovery check built into the app", code == 200 and sc.get("passed"),
           "; ".join(f"{'ok' if x['ok'] else 'FAILED'}: {x['step']}" for x in sc.get("steps", [])))
    rb = next((x for x in sc.get("steps", []) if "failed restore" in x["step"].lower()), {})
    record("Failed restoration rolls back (failure after the old file was moved)", bool(rb.get("ok")), rb.get("detail", "not run"))
    _, hh = http("GET", "/system/health")
    record("System health page answers", hh.get("app", {}).get("version") is not None and "backups" in hh,
           f"overall: {hh.get('overall')}; backups usable: {hh.get('backups', {}).get('usable_count')}")
    stopped = app.stop()
    record("Your data at the end", snapshot(db) == s0, diff(s0, snapshot(db)))
    record("Clean shutdown at the end", stopped, "")
    OUT.write_text(json.dumps(RESULTS, indent=1))
    return 0 if all(r["outcome"] == "pass" for r in RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
