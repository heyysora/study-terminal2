"""Upgrade check: seed a data folder with one Study Terminal version, start another version on it, compare what you would see.
Usage (cwd = that version's backend/, PYTHONPATH=.): python upgrade_check.py seed|verify <data_dir> <out.json>
Used by .github/workflows/build-windows.yml (Windows reliability job). SYNTHETIC seed data, created through the app's own API."""
import asyncio
import hashlib
import io
import json
import sqlite3
import sys
from pathlib import Path

import httpx

phase, D, OUT = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])   # compare: D = seed.json, OUT = verify.json
SKIP_FILES = {"study_terminal.db", "study_terminal.db-wal", "study_terminal.db-shm"}
CACHE_TABLES = {"bars"}  # market-data cache


def file_hashes():
    out = {}
    for p in sorted(D.rglob("*")):
        if p.is_file() and p.name not in SKIP_FILES and "logs" not in p.parts:
            out[str(p.relative_to(D))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def db_dump():
    con = sqlite3.connect(D / "study_terminal.db")
    out = {}
    for (t,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'"):
        if t in CACHE_TABLES:
            continue
        rows = con.execute(f'select * from "{t}"').fetchall()
        out[t] = sorted(json.dumps(r, default=str) for r in rows)
    con.close()
    return out


async def with_app(fn):
    from app.config import Settings
    from app.main import create_app
    from tests.fakes import FakeProvider, always_open_clock
    s = Settings(_env_file=None, app_env="test", STUDY_TERMINAL_DATA_DIR=D, poll_interval_seconds=3600, news_enabled=False,
                 paper_slippage_bps=0, paper_slippage_min=0)
    s.anthropic_api_key = None
    prov = FakeProvider()
    app = create_app(s, provider=prov, clock=always_open_clock())
    app.state.test_provider = prov
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=120,
                                     headers={"X-Study-Terminal": "1"}) as c:
            return await fn(c, app)


async def api_view(c):
    """What the user sees for the data we care about."""
    j = (await c.get("/api/futures/journal")).json()
    info = (await c.get("/api/futures/info")).json()
    sett = (await c.get("/api/settings")).json()
    prof = (await c.get("/api/visual/profiles")).json()
    cal = (await c.get("/api/screen/calibration")).json()
    paper = (await c.get("/api/paper/account")).json()
    jt = (await c.get("/api/journal/trades")).json()
    return {
        "futures_trades": [{k: t.get(k) for k in ("contract", "direction", "qty", "net", "r", "stop", "opened", "closed")} for t in j.get("trades", [])],
        "futures_summary": j.get("summary"),
        "prop": {k: info["prop"].get(k) for k in ("preset_id", "daily_loss_limit", "max_loss_limit", "confirmed", "confirmed_at")},
        "personal": info.get("personal"),
        "settings": {k: v for k, v in sett.get("values", {}).items() if k in ("futures.default_root", "ui.level", "market.mode")},
        "profiles": prof["profiles"],
        "calibration_samples": cal.get("samples", cal.get("summary")),
        "paper_cash": paper.get("cash"), "paper_equity_positions": paper.get("positions_value"),
        "journal_trades": jt,
    }


async def seed(c, app):
    log = []
    r = await c.post("/api/futures/risk/preset", json={"preset_id": "topstep_tc_50k"}); log.append(("preset", r.status_code))
    r = await c.put("/api/futures/risk/prop", json={"values": {"daily_loss_limit": 1000}, "confirm": True}); log.append(("prop", r.status_code))
    r = await c.put("/api/futures/risk/personal", json={"max_daily_loss_usd": 400, "max_risk_per_trade_usd": 150}); log.append(("personal", r.status_code))
    r = await c.put("/api/settings", json={"futures.default_root": "MNQ"}); log.append(("settings", r.status_code, r.text[:120]))
    r = await c.post("/api/visual/profiles", json={"name": "My MNQ 5m", "window_title_contains": "TopstepX", "root": "MNQ", "timeframe": "5Min"})
    log.append(("profile", r.status_code, r.text[:120]))
    pid = r.json().get("id")
    fx = Path("tests/fixtures/visual")
    for i, name in enumerate(["mnq_5m_basic", "mnq_1m_zoomed_out"]):
        truth = json.loads((fx / f"{name}.json").read_text())
        data = {"ticker": truth.get("ticker", "MNQZ6"), "timeframe": truth.get("timeframe", "5m"), "price": str(truth.get("price", "")),
                "platform": "auto", "synthetic": "true" if i == 0 else "false", "keep_image": "true"}
        if pid:
            data["profile"] = pid
        r = await c.post("/api/screen/calibration/sample", files={"file": (f"{name}.png", io.BytesIO((fx / f"{name}.png").read_bytes()), "image/png")},
                         data=data)
        log.append(("calibration", r.status_code, r.text[:100]))
    # a completed practice futures trade, filled on (simulated) live-polling data
    from app.futures import contracts as fc
    from app.futures.sessions import FuturesClock
    from datetime import datetime
    fut = app.state.futures
    e = fut.engine
    ES = FuturesClock(fc.get("ES"))
    t = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))  # noqa: E731
    e.on_bar("MESZ26", t("2026-11-10T15:00:00Z"), 6000, 6000, 6000, 6000, None, "polling", ES)
    o, pv = e.submit("MESZ26", +1, 1, "market", ref_price=6000, now=t("2026-11-10T15:00:00Z"), clock=ES, data_status="polling",
                     bracket={"stop": 5995.0, "targets": [{"price": 6012.0, "qty": 1}]})
    log.append(("futures order", bool(o), pv.get("problems")))
    e.on_bar("MESZ26", t("2026-11-10T15:01:00Z"), 6000, 6001, 5999, 6000, None, "polling", ES)
    e.on_bar("MESZ26", t("2026-11-10T15:02:00Z"), 6000, 6013, 6000, 6012, None, "polling", ES)
    fut.save()
    # stock paper trade + a journal note
    await asyncio.sleep(0.05)
    prov = app.state.test_provider
    prov.stream.push("SPY", 600.0, bid=599.98, ask=600.02)
    r = await c.post("/api/paper/orders", json={"symbol": "SPY", "side": "buy", "qty": 10, "type": "market", "stop_loss": 597.0,
                                                 "take_profit": 606.0, "confirm": True})
    log.append(("stock order", r.status_code, r.text[:120]))
    prov.stream.push("SPY", 606.5)
    await asyncio.sleep(0.05)
    jt = (await c.get("/api/journal/trades")).json()
    items = jt if isinstance(jt, list) else jt.get("trades", [])
    if items:
        key = items[0].get("key") or items[0].get("id")
        r = await c.post(f"/api/journal/trades/{key}/notes", json={"text": "Waited for the retest. Keep doing this."})
        log.append(("note", r.status_code, r.text[:80]))
    else:
        log.append(("note", "no stock trade to attach a note to"))
    return log


async def main():
    if phase == "seed":
        log = await with_app(seed)
        view = await with_app(lambda c, a: api_view(c))
        OUT.write_text(json.dumps({"log": log, "view": view, "files": file_hashes(), "db": db_dump()}, default=str, indent=1))
    elif phase == "verify":
        before = {"files": file_hashes(), "db": db_dump()}

        async def go(c, a):
            return {"view": await api_view(c), "trust": (await c.get("/api/trust")).json()}
        res = await with_app(go)
        after = {"files": file_hashes(), "db": db_dump()}
        OUT.write_text(json.dumps({"before": before, "after": after, **res}, default=str, indent=1))


def compare(seed_path: Path, verify_path: Path, backup_dir: str | None = None) -> dict:
    """What survived the upgrade. Rows that change on every start (monitoring heartbeat, re-evaluated decisions) are reported, not failed."""
    s, v = json.loads(seed_path.read_text()), json.loads(verify_path.read_text())
    b, a = v["before"], v["after"]
    files_same = {f: a["files"].get(f) == h for f, h in s["files"].items()}
    views_same = {k: s["view"][k] == v["view"][k] for k in s["view"]}
    changed = {t: len(set(rows) - set(a["db"].get(t, []))) for t, rows in s["db"].items() if set(rows) - set(a["db"].get(t, []))}
    volatile = {"futures_state", "futures_decisions", "app_events"}
    out = {"files_unchanged": all(files_same.values()), "files": files_same, "views_same": views_same,
           "all_views_same": all(views_same.values()), "rows_changed": changed,
           "unexpected_row_changes": {t: n for t, n in changed.items() if t not in volatile}}
    if backup_dir:
        import sqlite3
        con = sqlite3.connect(Path(backup_dir) / "study_terminal.db")
        bk = {}
        for (t,) in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'"):
            if t not in CACHE_TABLES:
                bk[t] = sorted(json.dumps(r, default=str) for r in con.execute(f'select * from "{t}"').fetchall())
        con.close()
        out["backup_equals_pre_upgrade"] = bk == s["db"]
    out["pass"] = out["files_unchanged"] and out["all_views_same"] and not out["unexpected_row_changes"] \
        and out.get("backup_equals_pre_upgrade", True)
    return out


if phase == "compare":
    res = compare(D, OUT, sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None)
    Path(sys.argv[5] if len(sys.argv) > 5 else "compare.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("pass", "files_unchanged", "all_views_same", "unexpected_row_changes")
                      + (("backup_equals_pre_upgrade",) if "backup_equals_pre_upgrade" in res else ())}))
    sys.exit(0 if res["pass"] else 1)
asyncio.run(main())
