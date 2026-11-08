"""Automation engine: modes, duplicate prevention, restart safety, sandbox, trade management, emergency stop, live lock."""
from datetime import datetime, timedelta, timezone

import pytest

from app.futures import contracts as fc
from app.futures.automation import AutomationEngine, AutomationState
from app.futures.risk import PersonalRisk
from app.futures.service import FuturesService
from app.settings.store import SettingsStore

T = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)      # Tue 09:00 CT
MES = fc.front_contract("MES", T.date())
OFF = PersonalRisk(max_risk_per_trade_usd=500, max_daily_loss_usd=None, min_reward_risk=None, max_consecutive_losses=None,
                   event_block_minutes=None, max_data_age_seconds=None)


def decision(outcome="APPROVED", bar="2026-11-10T14:55:00+00:00", fail_step=None, did="d1", qty=4):
    steps = [{"n": i, "step": f"s{i}", "passed": (False if i == fail_step else True), "detail": ""} for i in range(1, 14)]
    plan = {"setup": "sweep_reversal", "direction": "long", "entry": 6000.0, "stop": 5996.0, "target": 6008.0, "suggested_contracts": qty}
    return {"id": did, "contract": MES.code, "outcome": outcome, "reason": "test", "bar_time": bar, "plan": plan, "steps": steps,
            "action": "LONG" if outcome == "APPROVED" else "WATCH ONLY"}


def sig(dec, action=None, data_time="2026-11-10T14:55:00+00:00"):
    return {"decision": dec, "action": action or dec["action"], "reasons": ["r"], "data": {"status": "polling", "data_time": data_time},
            "regime": {"label": "x", "atr": 2.0}}


@pytest.fixture
def svc(settings, db):
    store = SettingsStore(db)
    store.update({"futures.personal": OFF.to_dict(), "futures.paper": {"slippage_ticks_market": 0, "slippage_ticks_stop": 0}})
    s = FuturesService(settings, db, store, provider=None)
    s.engine.on_bar(MES.code, T - timedelta(minutes=1), 6000, 6000, 6000, 6000, None, "polling", s.clock("MES"))
    return s


def engine(svc, sigs, mode="paper_auto", now=T):
    it = iter(sigs)
    last = {}

    async def ev(contract, m):
        last["s"] = next(it, last.get("s"))
        return last["s"]
    a = AutomationEngine(svc, AutomationState(mode=mode, roots=["MES"]), evaluate=ev, now=lambda: now)
    svc.automation = a
    return a


async def test_assisted_mode_never_enters(svc):
    a = engine(svc, [sig(decision())], mode="assisted")
    acts = await a.cycle()
    assert acts == [] and not svc.engine.orders
    assert a.state.per_contract[MES.code]["outcome"] == "APPROVED"


async def test_paper_auto_enters_once_with_bracket_and_partial(svc):
    a = engine(svc, [sig(decision())] * 3)
    acts = await a.cycle()
    assert acts[0]["action"] == "entered" and acts[0]["qty"] == 4
    o = svc.engine.orders[acts[0]["order_id"]]
    assert o.signal_id == "d1" and o.origin == "automation" and o.type == "limit" and o.limit_price == 6000.0
    assert o.bracket["stop"] == 5996.0 and [t["qty"] for t in o.bracket["targets"]] == [2, 2]
    assert [t["price"] for t in o.bracket["targets"]] == [6004.0, 6008.0]      # +1R partial, +2R target
    assert await a.cycle() == [] and len([x for x in svc.engine.orders.values() if x.role == "entry"]) == 1
    from app.db.models import FuturesDecisionRecord
    svc.record_decision({**decision(), "evaluated_at": T.isoformat(), "mode": "paper_auto"})
    svc.mark_acted("d1", o.id)
    with svc.db.session() as s:
        assert s.get(FuturesDecisionRecord, "d1").acted == o.id


async def test_restart_does_not_repeat_an_entry(svc, settings, db):
    a = engine(svc, [sig(decision())])
    await a.cycle()
    svc.save()
    svc2 = FuturesService(settings, db, svc.store, provider=None)       # restart: state from the database
    a2 = engine(svc2, [sig(decision())])
    await a2.cycle()
    assert len([x for x in svc2.engine.orders.values() if x.role == "entry"]) == 1


async def test_old_decision_is_not_acted_on(svc):
    a = engine(svc, [sig(decision(bar="2026-11-10T14:40:00+00:00"), data_time="2026-11-10T14:55:00+00:00")])
    assert await a.cycle() == [] and not svc.engine.orders


async def test_no_entry_while_position_open(svc):
    a = engine(svc, [sig(decision(did="d1")), sig(decision(did="d2", bar="2026-11-10T15:00:00+00:00"), data_time="2026-11-10T15:00:00+00:00")])
    await a.cycle()
    svc.engine.on_bar(MES.code, T + timedelta(minutes=1), 6000, 6001, 5999.0, 6000, None, "polling", svc.clock("MES"))   # entry fills
    assert svc.engine.positions[MES.code].qty == 4
    assert await a.cycle() == []


async def test_watch_only_goes_to_sandbox_only_when_only_evidence_failed(svc):
    svc.automation = None
    a = engine(svc, [sig(decision("WATCH_ONLY", fail_step=7))])
    a.state.sandbox_enabled = True
    acts = await a.cycle()
    assert [x["account"] for x in acts] == ["sandbox"] and not svc.engine.orders
    so = next(iter(svc.sandbox.orders.values()))
    assert so.origin == "sandbox" and so.signal_id == "sbx-d1" and so.qty == 1
    a2 = engine(svc, [sig(decision("WATCH_ONLY", fail_step=6, did="d9"))])
    a2.state.sandbox_enabled = True
    assert await a2.cycle() == []                                        # other failures never reach the sandbox


async def test_breakeven_and_trailing_are_recorded(svc):
    a = engine(svc, [sig(decision(qty=1))] * 4)
    await a.cycle()
    clk = svc.clock("MES")
    svc.engine.on_bar(MES.code, T + timedelta(minutes=1), 6000, 6001, 5999.0, 6000, None, "polling", clk)
    svc.engine.on_bar(MES.code, T + timedelta(minutes=2), 6004, 6004.25, 6003.5, 6004.25, None, "polling", clk)   # +1.06R
    acts = await a.cycle()
    assert any(x["action"] == "breakeven" and x["to"] == 6000.25 for x in acts)
    stop = next(o for o in svc.engine.orders.values() if o.role == "stop_loss" and o.active)
    assert stop.stop_price == 6000.25 and "break-even" in stop.note
    svc.engine.on_bar(MES.code, T + timedelta(minutes=3), 6007, 6007.5, 6006.5, 6007.5, None, "polling", clk)     # +1.9R
    acts = await a.cycle()
    tr = [x for x in acts if x["action"] == "trail"]
    assert tr and tr[0]["to"] == 6004.5                                   # 7.5 - 1.5 x ATR(2.0)
    assert any("stop moved" in e["text"] for e in svc.engine.events)


async def test_emergency_stop_flattens_and_requires_clearing(svc):
    a = engine(svc, [sig(decision(qty=1))])
    await a.cycle()
    svc.engine.on_bar(MES.code, T + timedelta(minutes=1), 6000, 6001, 5999.0, 6000.5, None, "polling", svc.clock("MES"))
    st = await a.emergency_stop("test")
    assert st["status"] == "emergency_stopped" and svc.engine.positions[MES.code].qty == 0
    assert st["emergency"]["positions_flattened"] == 1
    with pytest.raises(PermissionError):
        await a.start()
    with pytest.raises(ValueError):
        a.clear_emergency("ok")
    assert a.clear_emergency("Checked the fills; resuming tomorrow.")["status"] == "stopped"


async def test_live_mode_is_locked(svc):
    a = engine(svc, [])
    with pytest.raises(PermissionError):
        a.set_mode("live")
    st = a.status()
    assert st["live"]["locked"] is True and any(c["status"] != "done" for c in st["live"]["checklist"])


async def test_risk_engine_refusal_is_logged_not_bypassed(svc):
    svc.engine.locks["reset_required"] = "rules changed"
    a = engine(svc, [sig(decision())])
    acts = await a.cycle()
    assert acts[0]["action"] == "entry_refused" and not svc.engine.orders
    assert any("refused by the risk engine" in x["text"] for x in a.state.log)


async def test_unfilled_entry_expires(svc):
    a = engine(svc, [sig(decision())], now=T)
    await a.cycle()
    a._now = lambda: T + timedelta(minutes=11)
    await a.cycle()
    entry = next(o for o in svc.engine.orders.values() if o.role == "entry")
    assert entry.status == "canceled" and "validity" in entry.reason and MES.code not in a.state.managed


async def test_controls_and_api(settings, db):
    import httpx

    from app.main import create_app

    from .test_futures_api import FutProvider
    app = create_app(settings, provider=FutProvider(), start_loops=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"X-Study-Terminal": "1"}) as c:
            st = (await c.get("/api/futures/automation")).json()
            assert st["live"]["locked"] and st["roots"] == ["NQ", "MNQ", "ES", "MES"]
            assert (await c.post("/api/futures/automation/mode", json={"mode": "live"})).status_code == 403
            assert (await c.post("/api/futures/automation/mode", json={"mode": "paper_auto"})).json()["mode"] == "paper_auto"
            assert (await c.post("/api/futures/automation/start")).json()["status"] == "running"
            assert (await c.post("/api/futures/automation/pause")).json()["status"] == "paused"
            assert (await c.post("/api/futures/automation/resume")).json()["status"] == "running"
            r = (await c.post("/api/futures/automation/emergency-stop", json={"reason": "drill"})).json()
            assert r["status"] == "emergency_stopped"
            assert (await c.post("/api/futures/automation/start")).status_code == 403
            assert (await c.post("/api/futures/automation/stop")).status_code == 200
