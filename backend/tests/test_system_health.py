"""System health page, restart, the on-this-computer recovery check, backup checks, startup history, recent errors and the Chrome
extension's connection status. Temp folders only."""
from datetime import datetime, timedelta

import httpx

from app import datacare as dc
from app.main import create_app

from .test_datacare import damage
from .test_futures_api import FutProvider, always_open_clock

H = {"X-Study-Terminal": "1"}


def _app(settings):
    settings.anthropic_api_key = None
    app = create_app(settings, provider=FutProvider(), clock=always_open_clock(), start_loops=False)
    app.state.help_dir = settings.data_dir / "downloads"
    return app


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers=H, timeout=120)


async def test_health_page_normal_then_recovery(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app = _app(settings)
    async with app.router.lifespan_context(app), _client(app) as c:
        h = (await c.get("/api/system/health")).json()
        assert h["app"]["mode"] == "normal" and h["app"]["practice_only"] and h["data_file"]["ok"]
        assert h["backups"]["warning"] and "backups" in h["problems"]            # data but no usable backup yet
        assert h["startups"]["last_ok"]["version"] and h["extension"]["word"] == "Off"
        assert (await c.post("/api/data/backup")).json()["verified"]
        h = (await c.get("/api/system/health")).json()
        assert h["backups"]["warning"] is None and h["backups"]["newest_ok"] and not h["restart_recommended"]
        assert (await c.post("/api/system/restart", json={})).status_code == 400
        assert (await c.post("/api/system/restart", json={"confirm": True})).json()["restart_requested"]
        assert (await c.get("/api/data/status")).json()["restart_requested"]
    damage(settings.data_dir / dc.DB_NAME)
    app = _app(settings)
    async with app.router.lifespan_context(app), _client(app) as c:
        h = (await c.get("/api/system/health")).json()
        assert h["overall"] == "Problem" and h["app"]["mode"] == "recovery" and h["restart_recommended"]
        assert not h["data_file"]["ok"] and h["backups"]["last_good"]                # the backup is still there to use
        assert dc.startup_history(settings.data_dir)["starts"][0]["mode"] == "recovery"


async def test_self_check_and_backup_check_through_the_app(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app = _app(settings)
    async with app.router.lifespan_context(app), _client(app) as c:
        before = (settings.data_dir / dc.DB_NAME).stat().st_mtime_ns
        r = (await c.post("/api/system/self-check")).json()
        assert r["passed"] and len(r["steps"]) == 7 and "Your real data file was only read" in r["note"]
        assert (settings.data_dir / dc.DB_NAME).stat().st_mtime_ns == before
        assert not (settings.data_dir / "selfcheck-scratch").exists()
        assert (await c.get("/api/system/health")).json()["self_check"]["passed"]
        assert not [e for e in (await c.get("/api/system/health")).json()["recent_errors"] if "simulated" in e["text"]]
        b = (await c.post("/api/data/backup")).json()
        damage(settings.data_dir / "backups" / b["name"] / dc.DB_NAME)
        r = (await c.post("/api/system/check-backups")).json()
        assert r["backups"][0]["status"] == dc.DAMAGED and r["summary"]["warning"]


def test_recent_errors_and_startup_history(tmp_path):
    (tmp_path / "logs").mkdir()
    now = datetime.now()
    old = (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
    new = now.strftime("%Y-%m-%d %H:%M:%S")
    (tmp_path / "logs" / "study_terminal.log").write_text(
        f"{old},1 ERROR   app.x: too old\n{new},2 INFO    app.x: fine\n{new},3 ERROR   app.y: broke with key=sekritvalue99\n"
        "Traceback (most recent call last):\n")
    errs = dc.recent_errors(tmp_path, secrets=["sekritvalue99"])
    assert len(errs) == 1 and "broke" in errs[0]["text"] and "sekritvalue99" not in errs[0]["text"]
    dc.record_start(tmp_path, "normal", "1", now - timedelta(hours=1))
    dc.record_start(tmp_path, "recovery", "1", now)
    h = dc.startup_history(tmp_path)
    assert h["starts"][0]["mode"] == "recovery" and h["last_ok"]["at"] < h["starts"][0]["at"]


async def test_extension_hello_and_connection_status(settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    app = _app(settings)
    async with app.router.lifespan_context(app), _client(app) as c:
        assert (await c.get("/api/extension/hello")).json()["app"] == "Study Terminal"         # no token needed, no secrets in it
        assert "token" not in (await c.get("/api/extension/hello")).text
        await c.put("/api/settings", json={"extension.enabled": True})
        tok = (await c.get("/api/extension/pairing")).json()["token"]
        assert (await c.get("/api/extension/connection")).json()["word"] == "Waiting for the extension"
        await c.get("/api/extension/status", headers={"X-Study-Token": "wrong"})
        conn = (await c.get("/api/extension/connection")).json()
        assert conn["level"] == "bad" and "pairing code" in conn["do"].lower()
        await c.get("/api/extension/status", headers={"X-Study-Token": tok, "X-Study-Extension": "0.13.5"})
        conn = (await c.get("/api/extension/connection")).json()
        assert conn["word"] == "Connected" and conn["extension_version"] == "0.13.5"
