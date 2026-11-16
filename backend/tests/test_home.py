"""Home (five plain answers), Stop everything, Simple/Advanced. Display only: none of it may change limits, decisions or permissions."""
import httpx
import re
import pytest

from app import home
from app.main import create_app

from .fakes import FakeProvider, always_open_clock

ACCOUNT = {"risk": {"metrics": {"balance": 50000.0, "day_pnl": -120.0, "open_risk_usd": 75.0, "trades_today": 2},
                    "official": {"label": "Topstep 50K", "confirmed": True, "enabled": True, "mll_remaining": 1800.0, "dll_remaining": 900.0},
                    "personal": {"daily_loss_remaining": 380.0}, "warnings": [], "blocks": [], "blocked": False}}


def rec(action="WAIT", **kw):
    base = {"action": action, "reason": "Against the 15-minute structure.", "contract": "MNQZ26", "timeframe": "5Min", "observed_price": 24974.5,
            "data_confidence": 0.86, "captured_at": "2026-11-10T15:00:05+00:00", "potential": None,
            "analysis": {"bias": {"label": "bullish"}, "vwap": {"position": "above"}, "structure": "uptrend"}}
    return base | kw


def chart(status="screen_capture", reason="", recommendation=None):
    return {"state": "running", "charts": {"p1": {"profile": {"name": "My MNQ 5m"}, "status": status, "reason": reason, "recommendation": recommendation}}}


def build(**kw):
    args = dict(trades="futures", db_ok=True, monitor={"healthy": True, "monitoring_enabled": True}, visual=chart(recommendation=rec()),
                automation={"status": "running"}, profiles=1, futures_account=ACCOUNT, stock_account={}, decisions=[], signals={}, backup=None,
                trades_chosen=True, chart_seen=True, setup_dismissed=False, ui_mode="simple", point_value_of=lambda c: 2.0)
    return home.build(**(args | kw))


def test_working_chart_and_a_wait_explained_in_plain_words():
    h = build()
    assert h["mode"] == h["mode"] | {"practice": True, "live_locked": True, "label": "PRACTICE MODE"}
    assert h["health"]["level"] == "ok" and h["health"]["word"] == "Working" and "My MNQ 5m" in h["health"]["sentence"]
    assert h["market"]["sentence"] == "MNQZ26 is leaning up." and "above today's average price" in h["market"]["details"][0]
    assert "not an official exchange feed" in h["market"]["source"]
    d = h["decision"]
    assert d["word"] == "WAIT" and d["headline"] == "The bigger chart points the other way." and d["do"] and d["plan"] is None
    assert d["original"] == "Against the 15-minute structure."                      # the technical reason is kept
    assert "not the chance of winning" in d["confidence_note"] and d["confidence"] == "High"
    assert h["next"]["title"] == "Keep watching" and h["setup"]["done"] and not h["setup"]["show"]


@pytest.mark.parametrize("status,reason,head", [
    ("stale", "Chart frozen: nothing on it has changed for 90 s", "Your chart has stopped moving."),
    ("disconnected", "The TopstepX window is minimized; minimized windows can't be captured.", "The TopstepX window is minimized, so I can't see it."),
    ("unreadable", "Recognition confidence fell to 0.41: axis", "I can't read your chart right now."),
])
def test_chart_problems_turn_the_light_red_and_suspend_suggestions(status, reason, head):
    h = build(visual=chart(status, reason, rec("LONG", entry=100, stop=98, direction="long")))
    assert h["health"]["level"] == "bad" and h["health"]["word"] == "Not working" and h["health"]["sentence"] == head and h["health"]["do"]
    assert h["market"]["known"] is False
    assert h["decision"]["tone"] == "wait" and h["decision"]["plan"] is None       # a stale recommendation is never shown as an idea
    assert h["decision"]["headline"] == f"{head} So I'm not suggesting anything."  # and the reason is the chart, not something else
    assert h["next"]["kind"] == "fix" and head in h["next"]["text"]


def test_an_idea_shows_what_it_could_lose_and_stays_practice_only():
    r = rec("LONG", reason="ORB long passed every check, including the risk engine.", direction="long", entry=25000.0, stop=24980.0,
            target_1=25020.0, target_2=25040.0, reward_risk=2.0, suggested_contracts=2, invalidation="a close below 24980")
    h = build(visual=chart(recommendation=r))
    d = h["decision"]
    assert d["word"] == "PRACTICE IDEA: UP" and d["tone"] == "idea" and "Practice only" in d["note"]
    assert d["plan"] == d["plan"] | {"direction": "up", "could_lose_usd": 80.0, "could_gain_usd": 160.0, "contracts": 2, "exit_if_wrong": 24980.0}
    assert h["next"]["title"] == "Look at the practice plan"


def test_an_untested_idea_is_a_wait_with_the_idea_shown_for_watching():
    r = rec("WAIT", potential="LONG", reason="Potential LONG setup (ORB). It passes the risk engine, but it isn't a validated strategy.",
            direction="long", entry=25000.0, stop=24980.0, target_2=25040.0)
    d = build(visual=chart(recommendation=r))["decision"]
    assert d["word"] == "WAIT" and d["watch_only"] and "hasn't passed testing" in d["headline"] and d["plan"]["could_lose_usd"] == 40.0


def test_without_a_live_chart_a_stored_decision_is_never_an_idea():
    stored = [{"outcome": "APPROVED", "reason": "ORB long passed every check.", "contract": "MNQZ26", "evaluated_at": "2026-11-10T15:00:00+00:00"}]
    h = build(visual={"state": "stopped", "charts": {}}, decisions=stored)
    assert h["decision"]["word"] == "WAIT" and h["decision"]["plan"] is None and h["health"]["level"] == "off"
    delayed = [{"outcome": "NO_TRADE", "reason": "No decisions on delayed data.", "contract": "MNQZ26", "evaluated_at": "x"}]
    d = build(visual={"state": "stopped", "charts": {}}, decisions=delayed)["decision"]
    assert d["word"] == "WAIT" and "old (delayed) prices" in d["headline"]


def test_how_much_could_i_lose_uses_the_tightest_limit():
    r = build()["risk"]
    assert r["can_lose_today"] == 380.0 and r["can_lose_today_from"] == "your own daily limit" and r["at_risk_now"] == 75.0
    assert r["left_before_account_fails"] == 1800.0 and r["new_trades"] == "allowed" and r["limits_confirmed"]
    acct = {"risk": ACCOUNT["risk"] | {"blocked": True, "blocks": [{"text": "The stop loss ($300.00) is bigger than what's left of your own daily limit ($20.00)."}],
                                       "personal": {"daily_loss_remaining": 20.0}}}
    h = build(futures_account=acct)
    assert h["risk"]["new_trades"] == "stopped" and h["risk"]["stopped_why"][0]["kind"] == "risk"
    assert h["next"]["title"] == "Stop for now"


def test_next_step_follows_real_setup_state():
    h = build(profiles=0, chart_seen=False, visual={"state": "stopped", "charts": {}})
    assert h["setup"]["show"] and h["setup"]["current"] == "connect" and h["next"]["title"] == "Connect your chart" and h["next"]["link"] == "#/visual/setup"
    h = build(chart_seen=False, visual={"state": "stopped", "charts": {}})
    assert h["setup"]["current"] == "watch"
    unconfirmed = {"risk": ACCOUNT["risk"] | {"official": ACCOUNT["risk"]["official"] | {"confirmed": False}}}
    h = build(futures_account=unconfirmed)
    assert h["setup"]["current"] == "limits" and h["next"]["title"] == "Confirm your loss limits"
    assert build(futures_account=unconfirmed, setup_dismissed=True)["setup"]["show"] is False


def test_stopped_state_suggests_nothing():
    h = build(automation={"status": "emergency_stopped", "emergency": {"at": "2026-11-10T15:00:00+00:00", "reason": "Stop everything pressed"}},
              visual=chart(recommendation=rec("LONG", entry=1, stop=0, direction="long")))
    assert h["stopped"] and h["decision"]["word"] == "STOPPED" and h["decision"]["plan"] is None
    assert h["health"]["level"] == "attention" and h["health"]["sentence"] == "Everything is stopped." and h["next"]["kind"] == "restart"


def test_stocks_view():
    h = build(trades="stocks", stock_account={"equity": 25000.0, "day_pnl": -100.0, "daily_loss_limit": 500.0, "daily_loss_limit_hit": False, "open_positions": 1},
              signals={"market": {"bias": "bearish", "spy_change_pct": -0.42}, "summary": []})
    assert h["market"]["sentence"] == "The stock market is down 0.42% today." and h["risk"]["can_lose_today"] == 400.0
    up_but_lean_down = build(trades="stocks", stock_account={}, signals={"market": {"bias": "bearish", "spy_change_pct": 0.31}, "summary": []})
    assert up_but_lean_down["market"]["sentence"] == "The stock market is up 0.31% today."            # never contradicts the number
    assert "leaning down" in up_but_lean_down["market"]["details"][1]
    assert h["decision"]["word"] == "WAIT" and h["health"]["sentence"] == "Stock prices are arriving."
    bad = build(trades="stocks", monitor={"healthy": False, "monitoring_enabled": True, "health_reason": "socket closed"}, stock_account={})
    assert bad["health"]["level"] == "bad" and bad["health"]["sentence"] == "Stock prices aren't arriving."


# ---------------------------------------------------------------- through the real app

@pytest.fixture
async def client(settings):
    settings.anthropic_api_key = None
    app = create_app(settings, provider=FakeProvider(), clock=always_open_clock(), start_loops=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=60, headers={"X-Study-Terminal": "1"}) as c:
            yield c, app


async def test_fresh_install_home(client):
    c, _ = client
    h = (await c.get("/api/home")).json()
    assert h["mode"]["practice"] is True and h["mode"]["live_locked"] is True and h["ui_mode"] == "simple"
    assert h["setup"]["show"] and h["next"]["title"] == "Choose what you want to practice"
    assert (await c.post("/api/home", json={})).status_code == 405                # Home is read-only
    await c.put("/api/settings", json={"app.market_mode": "futures", "ui.trades_chosen": True})
    h = (await c.get("/api/home")).json()
    assert h["trades"] == "futures" and h["health"]["word"] == "Not watching" and h["next"]["title"] == "Connect your chart"
    assert h["risk"]["limits_confirmed"] is False and h["risk"]["practice_money"] == 50000.0


async def test_simple_and_advanced_show_the_same_limits_and_decisions(client):
    c, _ = client
    await c.put("/api/settings", json={"app.market_mode": "futures"})
    await c.put("/api/futures/risk/personal", json={"max_daily_loss_usd": 400, "max_risk_per_trade_usd": 150})

    def steady(x):
        """Same payload, minus the clock. "closes_at" is now + minutes-to-close, so within an hour of the daily break two
        calls a moment apart differ in the microseconds -- which says nothing about Simple and Advanced agreeing."""
        if isinstance(x, dict):
            return {k: steady(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [steady(v) for v in x]
        if isinstance(x, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?([+-]\d\d:\d\d|Z)?", x):
            return x[:16]                                          # to the minute
        return x

    async def snapshot():
        sett = (await c.get("/api/settings")).json()["values"]
        return steady(({k: v for k, v in sett.items() if not k.startswith("ui.")}, (await c.get("/api/futures/risk")).json(),
                       (await c.get("/api/futures/info")).json()["personal"],
                       (await c.get("/api/futures/automation")).json()["live"],
                       {k: v for k, v in (await c.get("/api/home")).json().items() if k != "ui_mode"}))
    simple = await snapshot()
    assert (await c.put("/api/settings", json={"ui.mode": "advanced"})).status_code == 200
    assert (await c.get("/api/home")).json()["ui_mode"] == "advanced"
    advanced = await snapshot()
    assert simple == advanced and advanced[3]["locked"] is True
    assert (await c.put("/api/settings", json={"ui.mode": "expert"})).status_code == 422


async def test_stop_everything(client):
    c, app = client
    assert (await c.post("/api/stop-everything", json={})).status_code == 400      # needs confirmation
    assert app.state.futures.automation.state.status != "emergency_stopped"
    # a practice trade the user placed by hand must be left alone
    from datetime import datetime, timezone

    from app.futures import contracts as fc
    from app.futures.sessions import FuturesClock
    eng = app.state.futures.engine
    clk, t0 = FuturesClock(fc.get("ES")), datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)
    eng.on_bar("MESZ26", t0, 6000, 6000, 6000, 6000, None, "polling", clk)
    o, _ = eng.submit("MESZ26", +1, 1, "market", ref_price=6000, now=t0, clock=clk, data_status="polling", bracket={"stop": 5995.0, "targets": []})
    eng.on_bar("MESZ26", datetime(2026, 11, 10, 15, 1, tzinfo=timezone.utc), 6000, 6001, 5999, 6000, None, "polling", clk)
    assert o and eng.positions["MESZ26"].qty == 1
    r = (await c.post("/api/stop-everything", json={"confirm": True})).json()
    assert r["ok"] and len(r["done"]) == 3 and not r["failed"] and "real TopstepX account is not affected" in r["real_account"]
    assert app.state.futures.automation.state.status == "emergency_stopped" and app.state.visual.state == "stopped" and app.state.screen.state == "off"
    assert eng.positions["MESZ26"].qty == 1                                        # manual practice trade untouched
    h = (await c.get("/api/home")).json()
    assert h["stopped"] and h["decision"]["word"] == "STOPPED" and h["next"]["title"] == "Everything is stopped"
    assert (await c.post("/api/futures/automation/start")).status_code >= 400       # can't just be switched back on
    assert app.state.futures.automation.state.status == "emergency_stopped"
    assert (await c.post("/api/start-again", json={"note": "too short"})).status_code == 422
    r = (await c.post("/api/start-again", json={"note": "I pressed stop to test that it works."})).json()
    assert r == {"ok": True, "status": "stopped"}                                  # cleared, but nothing starts by itself
    assert (await c.get("/api/futures/automation")).json()["live"]["locked"] is True


async def test_home_survives_a_failing_part(client):
    c, app = client

    def boom():
        raise RuntimeError("visual status exploded")
    app.state.visual.status = boom
    r = await c.get("/api/home")
    assert r.status_code == 200
    h = r.json()
    assert h["health"]["level"] == "bad" and h["next"]["title"] == "Restart Study Terminal"


async def test_plain_endpoints(client):
    c, _ = client
    w = (await c.get("/api/plain")).json()
    assert w["actions"]["WATCH_ONLY"]["word"] == "WAIT" and "terms" in w
    e = (await c.post("/api/plain/explain", json={"reason": "Outside RTH.", "action": "NO_TRADE"})).json()
    assert e["headline"] == "It's outside the main trading hours." and e["action"]["word"] == "WAIT"
