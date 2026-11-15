"""P10: mobile companion API security and behaviour, and the data the Automation Center reads."""
import httpx
import pytest

from app.api import routes_mobile
from app.main import create_app

from .test_futures_api import FutProvider
from .fakes import always_open_clock


@pytest.fixture
async def mclient(settings):
    settings.anthropic_api_key = None
    settings.mobile_allowed_hosts = "phone.tailnet.example"
    routes_mobile._FAILS.clear()
    app = create_app(settings, provider=FutProvider(), clock=always_open_clock(), start_loops=False)
    async with app.router.lifespan_context(app):
        tr = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60, headers={"X-Study-Terminal": "1"}) as desk, \
                httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as phone:
            yield desk, phone, app


async def _enable(desk) -> str:
    r = (await desk.post("/api/mobile-access", json={"enabled": True})).json()
    assert r["enabled"] and r["token"] and "shown once" in r["token_note"]
    return r["token"]


async def test_off_by_default_and_token_required(mclient):
    desk, phone, app = mclient
    assert (await desk.get("/api/mobile-access")).json()["enabled"] is False
    assert (await phone.get("/api/mobile/status")).status_code == 401                         # no Authorization header
    assert (await phone.get("/api/mobile/status", headers={"Authorization": "Bearer x"})).status_code == 403   # turned off
    tok = await _enable(desk)
    assert (await phone.get("/api/mobile/status", headers={"Authorization": "Bearer wrong"})).status_code == 401
    r = await phone.get("/api/mobile/status", headers={"Authorization": f"Bearer {tok}"})
    j = r.json()
    assert r.status_code == 200 and j["simulated"] and j["automation"]["mode"] == "paper_auto" and "can't see or change" in j["note"]


async def test_token_stored_only_as_hash_and_hidden_from_settings(mclient):
    desk, phone, app = mclient
    tok = await _enable(desk)
    store = app.state.settings_store
    assert store.get("mobile.token_hash") != tok and len(store.get("mobile.token_hash")) == 64
    vals = (await desk.get("/api/settings")).json()["values"]
    assert "mobile.token_hash" not in vals and tok not in str(vals)
    assert (await desk.put("/api/settings", json={"mobile.token_hash": "x"})).status_code == 422          # can't be set by the generic route
    assert (await desk.put("/api/settings", json={"mobile.enabled": True})).status_code == 422


async def test_new_token_revokes_old_and_turning_off_revokes(mclient):
    desk, phone, app = mclient
    old = await _enable(desk)
    new = (await desk.post("/api/mobile-access", json={"enabled": True, "new_token": True})).json()["token"]
    assert new != old
    assert (await phone.get("/api/mobile/status", headers={"Authorization": f"Bearer {old}"})).status_code == 401
    assert (await phone.get("/api/mobile/status", headers={"Authorization": f"Bearer {new}"})).status_code == 200
    await desk.post("/api/mobile-access", json={"enabled": False})
    assert (await phone.get("/api/mobile/status", headers={"Authorization": f"Bearer {new}"})).status_code == 403


async def test_only_braking_controls_from_phone(mclient):
    desk, phone, app = mclient
    tok = await _enable(desk)
    h = {"Authorization": f"Bearer {tok}"}
    await desk.post("/api/futures/automation/start")
    assert (await phone.post("/api/mobile/automation/pause", headers=h)).json()["automation"]["status"] == "paused"
    assert (await phone.post("/api/mobile/automation/resume", headers=h)).json()["automation"]["status"] == "running"
    for bad in ("start", "clear-emergency", "mode", "cycle"):
        assert (await phone.post(f"/api/mobile/automation/{bad}", headers=h)).status_code == 404
    es = (await phone.post("/api/mobile/automation/emergency-stop", headers=h)).json()
    assert es["automation"]["status"] == "emergency_stopped" and "mobile" in es["automation"]["emergency"]["reason"]
    assert (await phone.post("/api/mobile/automation/resume", headers=h)).status_code == 409      # can't clear from the phone
    # the phone can't reach any other API, even with a valid token and no intent header
    assert (await phone.post("/api/futures/paper/order", headers=h, json={})).status_code == 403
    assert (await phone.post("/api/futures/automation/clear-emergency", headers=h, json={"note": "x" * 20})).status_code == 403
    await desk.post("/api/futures/automation/stop")


async def test_mobile_host_only_for_mobile_paths(mclient):
    desk, phone, app = mclient
    tok = await _enable(desk)
    h = {"Authorization": f"Bearer {tok}", "Host": "phone.tailnet.example"}
    assert (await phone.get("/api/mobile/status", headers=h)).status_code == 200
    assert (await phone.get("/api/futures/automation", headers=h)).status_code == 421              # rest of the API stays localhost-only
    assert (await phone.get("/api/mobile/status", headers={**h, "Host": "evil.example"})).status_code == 421


async def test_bad_token_lockout(mclient):
    desk, phone, app = mclient
    tok = await _enable(desk)
    for _ in range(10):
        assert (await phone.get("/api/mobile/status", headers={"Authorization": "Bearer nope"})).status_code == 401
    assert (await phone.get("/api/mobile/status", headers={"Authorization": f"Bearer {tok}"})).status_code == 429


async def test_mobile_alerts_and_automation_center_data(mclient):
    desk, phone, app = mclient
    tok = await _enable(desk)
    assert "alerts" in (await phone.get("/api/mobile/alerts", headers={"Authorization": f"Bearer {tok}"})).json()
    st = (await desk.get("/api/futures/automation")).json()
    assert st["live"]["locked"] and st["live"]["checklist"]
    assert (await desk.post("/api/futures/automation/mode", json={"mode": "live"})).status_code in (400, 403, 409)
    acct = (await desk.get("/api/futures/paper")).json()
    assert "trades_today" in acct["risk"]["metrics"] and "max_contracts_mini" in acct["risk"]["official"]
    j = (await desk.get("/api/futures/journal/practice")).json()
    assert {"automated", "manual", "comparison_note"} <= set(j)
