"""Evaluation practice (status, trading days, winning days, profiles) and replay (no look-ahead, persistence, automation, review)."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.futures import contracts as fc
from app.futures.paper import FuturesPaperConfig, FuturesPaperEngine
from app.futures.risk import PersonalRisk, PropRules, load_presets
from app.futures.sessions import FuturesClock

from .test_futures_api import FutProvider

ES = FuturesClock(fc.get("ES"))
OFF = PersonalRisk(max_risk_per_trade_usd=None, max_daily_loss_usd=None, min_reward_risk=None, max_consecutive_losses=None,
                   event_block_minutes=None, max_data_age_seconds=None)


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def test_evaluation_status_target_consistency_and_days():
    r = PropRules.from_preset("topstep_tc_50k")
    r.min_trading_days = 2
    e = FuturesPaperEngine(r, OFF, FuturesPaperConfig(), load_presets()["fees"]["round_turn"])
    e.balance = 53100
    e.daily = {"2026-11-05": 2000.0, "2026-11-06": 1100.0}
    e.entries_today = {"2026-11-05": 2}
    st = e.risk_status(utc("2026-11-10T15:00:00Z"), ES)["official"]
    assert st["days_traded"] == 1 and "consistency" in st["evaluation_status"] and "1 of 2 trading days" in st["evaluation_status"]
    e.entries_today["2026-11-06"] = 1
    e.daily = {"2026-11-05": 1400.0, "2026-11-06": 1300.0, "2026-11-07": 400.0}
    assert e.risk_status(utc("2026-11-10T15:00:00Z"), ES)["official"]["evaluation_status"] == "target reached"
    e.locks["mll_breached"] = "x"
    assert e.risk_status(utc("2026-11-10T15:00:00Z"), ES)["official"]["evaluation_status"].startswith("failed")


def test_xfa_winning_days_progress():
    r = PropRules.from_preset("topstep_xfa_50k")
    assert r.winning_day_usd == 150 and r.winning_days_required == 5
    e = FuturesPaperEngine(r, OFF, FuturesPaperConfig(), {})
    e.daily = {"a": 200.0, "b": 149.0, "c": 400.0}
    st = e.risk_status(utc("2026-11-10T15:00:00Z"), ES)["official"]
    assert st["winning_days"] == 2 and st["evaluation_status"] == "2 of 5 winning days ($150+)"


def test_profiles_save_load_delete(settings, db):
    from app.futures.service import FuturesService
    from app.settings.store import SettingsStore

    svc = FuturesService(settings, db, SettingsStore(db), provider=None)
    svc.use_preset("topstep_tc_100k")
    svc.save_profile("Combine 100K")
    svc.use_preset("topstep_xfa_50k")
    svc.save_profile("XFA 50K")
    assert set(svc.profiles()["profiles"]) == {"Combine 100K", "XFA 50K"}
    svc.load_profile("Combine 100K")
    assert svc.rules().max_loss_limit == 3000 and svc.engine.balance == 100000
    with pytest.raises(KeyError):
        svc.load_profile("nope")
    assert set(svc.delete_profile("XFA 50K")["profiles"]) == {"Combine 100K"}


@pytest.fixture
def rsvc(settings, db):
    from app.futures.replay import Replayer
    from app.futures.service import FuturesService
    from app.settings.store import SettingsStore

    class Data:
        def __init__(self):
            self.yahoo = FutProvider()
    svc = FuturesService(settings, db, SettingsStore(db), provider=None)
    svc.data = Data()
    svc.replayer = Replayer(svc, now=lambda: utc("2026-11-08T12:00:00Z"))
    return svc


async def test_replay_never_uses_future_bars(rsvc):
    st = await rsvc.replay_start("MESZ26", "2026-11-05", "5Min")
    assert st["progress"]["i"] == 0 and st["timeframe"] == "5Min"
    for _ in range(3):
        st = await rsvc.replay_step(40)
        last_chart = max(b["t"] for b in st["chart"])
        bar_t = int(datetime.fromisoformat(st["bar_time"]).timestamp())
        assert last_chart <= bar_t                                         # nothing after the current bar is visible
        if st["signal"].get("market_data_time"):
            assert st["signal"]["market_data_time"] <= st["bar_time"]
    assert st["signal"]["data"]["status"] == "replay"


async def test_replay_order_persists_across_restart_and_review(rsvc, settings, db):
    from app.futures.replay import Replayer
    st = await rsvc.replay_start("MESZ26", "2026-11-05", "5Min")
    st = await rsvc.replay_step(60)
    last = st["last"]
    r = rsvc.replay_order({"contract": "MESZ26", "side": 1, "qty": 1, "type": "market", "confirm": True,
                           "bracket": {"stop": fc.round_to_tick(last - 30, fc.get("MES")), "targets": []}})
    assert r["order"], r["preview"]
    await rsvc.replay_step(2)
    assert rsvc.replayer.rp["engine"].positions["MESZ26"].qty == 1
    rep2 = Replayer(rsvc, now=rsvc.replayer._now)
    rep2.restore(rsvc._load(2))                                            # restart
    assert rep2.rp["engine"].positions["MESZ26"].qty == 1 and rep2.rp["i"] == rsvc.replayer.rp["i"]
    rsvc.replayer = rep2
    rsvc.replay_flatten()
    review = rsvc.replayer.review()
    assert review["summary"]["trades"] == 1 and review["manual"]["trades"] == 1 and review["automated"]["trades"] == 0
    assert rsvc.all_fills("practice") == []                                # replay trades never touch the practice account


async def test_replay_one_minute_only_for_recent_dates(rsvc):
    with pytest.raises(ValueError, match="1-minute"):
        await rsvc.replay_start("MESZ26", "2026-10-27", "1Min")


async def test_replay_automation_only_acts_on_approved_or_opted_in_experimental(rsvc, monkeypatch):
    from app.futures import replay as rmod

    calls = {"n": 0}
    real = rmod.Replayer._signal

    def fake_signal(self, clk):
        sig, seen, five, F, now = real(self, clk)
        calls["n"] += 1
        plan = {"setup": "sweep_reversal", "direction": "long", "entry": seen[-1]["close"], "stop": seen[-1]["close"] - 5,
                "target": seen[-1]["close"] + 10, "suggested_contracts": 1}
        steps = [{"n": i, "passed": i != 7} for i in range(1, 14)]
        sig["decision"] = {"id": f"d{calls['n']}", "outcome": "WATCH_ONLY", "plan": plan, "steps": steps}
        return sig, seen, five, F, now
    monkeypatch.setattr(rmod.Replayer, "_signal", fake_signal)
    await rsvc.replay_start("MESZ26", "2026-11-05", "5Min", auto=True, auto_experimental=False)
    await rsvc.replay_step(5)
    assert not rsvc.replayer.rp["engine"].orders                           # experimental not allowed
    await rsvc.replay_start("MESZ26", "2026-11-05", "5Min", auto=True, auto_experimental=True)
    eng = rsvc.replayer.rp["engine"]
    for _ in range(12):
        await rsvc.replay_step(1)
        working = [o for o in eng.orders.values() if o.role == "entry" and o.active]
        pos = eng.positions.get("MESZ26")
        assert len(working) + (1 if pos and pos.qty else 0) <= 1            # never two entries or an entry on top of a position
    entries = [o for o in eng.orders.values() if o.role == "entry"]
    assert entries and all(o.origin == "replay-auto" for o in entries)
    assert len({o.signal_id for o in entries}) == len(entries)              # one order per decision
    assert rsvc.replayer.rp["auto_log"][0]["experimental"] is True
