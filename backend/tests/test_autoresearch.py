"""Mode B as the default (practice trades placed automatically for validated strategies) and the weekly research schedule.

Everything here is simulated: fake research results and a fake clock. It proves the schedule, the records and the
switching-on and -off of strategies behave as written. It says nothing about whether any strategy makes money.
"""
from datetime import datetime, timedelta, timezone

import pytest


from app.futures.autoresearch import FORCE_AFTER, AutoResearch
from app.futures.automation import AutomationEngine, AutomationState
from app.futures.service import FuturesService
from app.settings.store import SettingsStore

from .test_futures_api import client  # noqa: F401  (fixture)
from .test_futures_automation import MES, OFF, decision, sig

T = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)      # Tue 09:00 CT, futures open
WEEKEND = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc)  # Sat, futures closed


@pytest.fixture
def svc(settings, db):
    store = SettingsStore(db)
    store.update({"futures.personal": OFF.to_dict(), "futures.paper": {"slippage_ticks_market": 0, "slippage_ticks_stop": 0}})
    s = FuturesService(settings, db, store, provider=None)
    s.engine.on_bar(MES.code, T - timedelta(minutes=1), 6000, 6000, 6000, 6000, None, "polling", s.clock("MES"))
    s.evidence = {}                     # the real app ships research results with it; these tests set their own
    return s


def research_result(root="MES", validated=("sweep_reversal|long",), at=T, trades=120, avg_r=0.3, tier="reliable"):
    return {"product": root, "method": "walk-forward + final holdout", "run_at": at.isoformat(), "validated": list(validated),
            "data": {"trade_dates": 40, "first": "2026-09-01", "last": "2026-11-10", "bars": 9000},
            "oos_metrics": {"trades": trades, "avg_r": avg_r, "profit_factor": 1.3, "total_r": avg_r * trades, "tier": tier,
                            "tier_text": f"{tier}: 95% interval above zero"},
            "holdout_metrics": {"trades": 40, "avg_r": 0.25, "profit_factor": 1.2, "total_r": 10.0},
            "run": {"at": at.isoformat()}}


def fake_research(svc, results, fail=None):
    """Replace the real research with a scripted one; it updates the evidence exactly as the real one does."""
    calls = []

    async def research(root, days=59):
        calls.append(root)
        if fail:
            raise fail
        res = results.pop(0) if results else research_result(root)
        svc.evidence[root] = res
        return res
    svc.research = research
    return calls


# ---------------------------------------------------------------- mode B
def test_automated_practice_trading_is_the_default_and_your_choice_is_kept():
    assert AutomationState().mode == "paper_auto" and AutomationState().mode_chosen is False
    old = AutomationState(mode="assisted").to_dict()                     # saved by 0.17 or earlier, no mode ever picked
    del old["mode_chosen"]
    assert AutomationState.from_dict(old).mode == "paper_auto"
    chosen = AutomationState(mode="assisted", mode_chosen=True).to_dict()
    assert AutomationState.from_dict(chosen).mode == "assisted"          # you turned it off: it stays off
    assert AutomationState.from_dict({"mode": "paper_auto"}).mode == "paper_auto"


async def test_turning_it_off_sticks_and_says_what_changed(svc):
    a = AutomationEngine(svc, AutomationState(), now=lambda: T)
    assert a.state.mode == "paper_auto"
    a.set_mode("assisted")
    assert a.state.mode == "assisted" and a.state.mode_chosen
    assert "no longer placed automatically" in a.state.log[-1]["text"]
    assert AutomationState.from_dict(a.state.to_dict()).mode == "assisted"
    with pytest.raises(PermissionError):
        a.set_mode("live")                                               # live is still locked


async def test_a_validated_strategy_is_traded_in_practice_without_being_asked(svc):
    it = iter([sig(decision())])
    last = {}

    async def ev(contract, m):
        last["s"] = next(it, last.get("s"))
        return last["s"]
    a = AutomationEngine(svc, AutomationState(roots=["MES"]), evaluate=ev, now=lambda: T)   # defaults, nothing configured
    svc.automation = a
    acts = await a.cycle()
    assert acts and acts[0]["action"] == "entered" and svc.engine.orders                      # pretend money, practice account
    assert all(getattr(o, "account", "practice") == "practice" for o in svc.engine.orders.values())


# ---------------------------------------------------------------- the weekly schedule
def test_when_each_product_is_due(svc):
    ar = AutoResearch(svc, svc.store, now=lambda: T)
    ar.roots = lambda: ["MES"]
    d = ar.due()[0]
    assert d["due"] and d["ready"] and d["why"] == "never researched"                       # never researched: run now
    assert AutoResearch(FuturesService(svc.settings, svc.db, svc.store, provider=None), svc.store,
                        now=lambda: T).due()[0]["why"].endswith("day(s) ago")                # a fresh install starts from the shipped results
    svc.evidence["MES"] = research_result(at=T - timedelta(days=2))
    d = ar.due()[0]
    assert not d["due"] and not d["ready"] and "2 day(s) ago" in d["why"]
    svc.evidence["MES"] = research_result(at=T - timedelta(days=8))                         # due, but the market is open
    d = ar.due()[0]
    assert d["due"] and not d["ready"] and not d["market_closed"] and "waiting for the market to close" in d["why"]
    ar2 = AutoResearch(svc, svc.store, now=lambda: WEEKEND)
    ar2.roots = lambda: ["MES"]
    assert ar2.due()[0]["ready"] and ar2.due()[0]["market_closed"]                          # weekend: go
    svc.evidence["MES"] = research_result(at=T - FORCE_AFTER - timedelta(days=1))           # far overdue: go anyway
    assert ar.due()[0]["ready"]


async def test_one_product_per_tick_oldest_first(svc):
    ar = AutoResearch(svc, svc.store, now=lambda: WEEKEND)
    ar.roots = lambda: ["NQ", "MES"]
    svc.evidence["NQ"] = research_result("NQ", at=WEEKEND - timedelta(days=9))
    svc.evidence["MES"] = research_result("MES", at=WEEKEND - timedelta(days=30))
    calls = fake_research(svc, [research_result("MES", at=WEEKEND), research_result("NQ", at=WEEKEND)])
    assert (await ar.tick())["product"] == "MES" and calls == ["MES"]                       # the one waiting longest
    assert (await ar.tick())["product"] == "NQ" and calls == ["MES", "NQ"]
    assert await ar.tick() is None                                                          # both fresh: nothing to do


async def test_results_are_kept_for_good_and_a_later_run_cannot_hide_a_bad_one(svc):
    ar = AutoResearch(svc, svc.store, now=lambda: WEEKEND)
    ar.roots = lambda: ["MES"]
    fake_research(svc, [research_result(avg_r=-0.4, tier="losing", validated=()),
                        research_result(avg_r=0.5, tier="reliable", validated=("sweep_reversal|long",))])
    bad = await ar.run_root("MES")
    good = await ar.run_root("MES")
    assert bad["oos"]["avg_r"] == -0.4 and good["oos"]["avg_r"] == 0.5
    assert [h["oos"]["avg_r"] for h in ar.history] == [-0.4, 0.5]                           # the poor run is still there
    assert ar.history[0]["validated"] == [] and ar.history[1]["validated"] == ["sweep_reversal|long"]
    again = AutoResearch(svc, svc.store, now=lambda: WEEKEND)                               # and it survives a restart
    assert [h["oos"]["avg_r"] for h in again.history] == [-0.4, 0.5]
    assert "never changes a strategy" in again.status()["note"]


async def test_a_strategy_that_stops_meeting_the_bar_stops_trading_and_says_so(svc):
    ar = AutoResearch(svc, svc.store, now=lambda: WEEKEND)
    ar.roots = lambda: ["MES"]
    sent = []
    svc.alerts = type("A", (), {"emit": lambda self, *a, **k: sent.append((a, k))})()
    fake_research(svc, [research_result(validated=("sweep_reversal|long",)), research_result(validated=())])
    await ar.run_root("MES")
    assert svc.validated_strategies("MES") == {"sweep_reversal|long"}
    rec = await ar.run_root("MES")
    assert svc.validated_strategies("MES") == set() and rec["changed"] == ["sweep_reversal|long"]
    assert any("no longer validated and will not trade" in x["text"] for x in svc.automation.state.log)
    assert sent and "Stopped: sweep_reversal|long" in sent[-1][0][3]


async def test_a_failed_run_is_reported_not_silent(svc):
    ar = AutoResearch(svc, svc.store, now=lambda: WEEKEND)
    ar.roots = lambda: ["MES"]
    fake_research(svc, [], fail=RuntimeError("Yahoo is rate-limiting requests"))
    assert await ar.tick() is None
    assert "rate-limiting" in ar.last_error and ar.history == []
    assert any("couldn't run" in x["text"] for x in svc.automation.state.log)
    assert ar.due()[0]["ready"]                                                             # still due: it tries again


async def test_it_can_be_switched_off_and_never_runs_two_at_once(svc):
    ar = AutoResearch(svc, svc.store, now=lambda: WEEKEND)
    ar.roots = lambda: ["MES"]
    fake_research(svc, [])
    svc.store.update({"research.weekly": False})
    assert not ar.enabled and await ar.tick() is None
    svc.store.update({"research.weekly": True})
    svc._bt_running.add("MES")                                                              # a test you started is running
    assert await ar.tick() is None
    svc._bt_running.discard("MES")
    assert (await ar.tick()) is not None


async def test_the_schedule_is_visible_over_the_api(client):  # noqa: F811
        c, _app = client
        r = (await c.get("/api/futures/research/schedule")).json()
        assert r["enabled"] and r["every_days"] == 7 and r["products"] and "validated_now" in r
        assert (await c.get("/api/futures/automation")).json()["mode"] == "paper_auto"
        assert (await c.post("/api/futures/research/run-now?root=NOPE")).status_code == 409
