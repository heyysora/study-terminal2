"""Decision pipeline: each step's failure produces the documented outcome, on real ES bars (fixture)."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.futures import contracts as fc
from app.futures import features as ff
from app.futures.paper import FuturesPaperEngine
from app.futures.pipeline import STEPS, PipelineConfig, decision_id, run
from app.futures.risk import PersonalRisk, PropRules, RiskEngine
from app.futures.sessions import FuturesClock
from app.futures.setups import SetupParams, detect

from .test_futures_analysis import load_bars

ES = fc.get("ES")
CLK = FuturesClock(ES)
LIVE = {"status": "polling", "provider": "test", "age_seconds": 30, "validation": {"ok": True, "summary": "ok"}}


@pytest.fixture(scope="module")
def F():
    return ff.build(ff.bars_to_frame(load_bars(), CLK), ES, CLK)


@pytest.fixture(scope="module")
def setup_row(F):
    for i in range(len(F) - 1, 300, -1):
        found, _ = detect(F, i, ES, SetupParams(flat_by_min_from_rth=400))
        if found:
            G = F.iloc[:i + 1].copy()
            G.attrs.update(F.attrs)
            return G, found[0]
    raise AssertionError


def ctx(G, budget=1000, **kw):
    risk = RiskEngine(PropRules.from_preset("topstep_tc_150k"), PersonalRisk(max_risk_per_trade_usd=budget, max_daily_loss_usd=None,
                                                                             min_reward_risk=None, event_block_minutes=None))
    now = G["ts"].iloc[-1].to_pydatetime() + timedelta(minutes=5)
    snap = FuturesPaperEngine(risk.rules, risk.personal).snapshot(now, None)
    return dict(now=now, risk_engine=risk, snapshot=snap, round_turn=3.78, slippage_ticks=1, flat_by_min_from_rth=400, **kw)


ESZ = fc.Contract("ES", 2026, 12)


def key(s):
    return f"{s.name}|{'long' if s.direction > 0 else 'short'}"


def test_thirteen_steps_always_reported(setup_row):
    G, s = setup_row
    d = run(G, None, ESZ, LIVE, {}, **ctx(G))
    assert [x["step"] for x in d.steps] == STEPS and len(d.steps) == 13


@pytest.mark.parametrize("status,outcome", [("delayed", "NO_TRADE"), ("stale", "NO_TRADE"), ("cached", "NO_TRADE"), ("historical", "NO_TRADE")])
def test_step1_data_status(setup_row, status, outcome):
    G, s = setup_row
    d = run(G, None, ESZ, {**LIVE, "status": status}, {key(s): {"tier": "reliable"}}, **ctx(G))
    assert d.outcome == outcome and d.steps[0]["passed"] is False
    if status == "delayed":
        assert d.candidates                                       # study-only setups listed


def test_step1_old_data_and_failed_validation(setup_row):
    G, s = setup_row
    assert run(G, None, ESZ, {**LIVE, "age_seconds": 900}, {}, **ctx(G)).outcome == "NO_TRADE"
    assert run(G, None, ESZ, {**LIVE, "validation": {"ok": False, "summary": "2 impossible"}}, {}, **ctx(G)).outcome == "NO_TRADE"


def test_step2_expired_and_rolled_contracts(setup_row):
    G, s = setup_row
    assert run(G, None, fc.Contract("ES", 2025, 12), LIVE, {}, **ctx(G)).outcome == "REJECTED"
    late = ctx(G)
    late["now"] = datetime(2026, 12, 15, 15, 0, tzinfo=timezone.utc)
    d = run(G, None, ESZ, LIVE, {}, **late)
    assert d.outcome == "REJECTED" and "roll" in d.reason


def test_step4_extreme_volatility(setup_row):
    G, s = setup_row
    H = G.copy()
    H.attrs.update(G.attrs)
    H.loc[H.index[-1], "atr"] = H["atr"].max() * 10
    d = run(H, None, ESZ, LIVE, {}, **ctx(H))
    assert d.outcome == "REJECTED" and d.regime["volatility"] == "extreme"


def test_step6_higher_timeframe_against(setup_row):
    G, s = setup_row
    F15 = pd.DataFrame({"trend": [-s.direction], "ts": [G["ts"].iloc[-1]]})
    d = run(G, F15, ESZ, LIVE, {key(s): {"tier": "reliable", "trades": 150}}, **ctx(G))
    assert d.outcome == "WATCH_ONLY" and d.steps[5]["passed"] is False


def test_step7_unvalidated_strategies_are_watch_only(setup_row):
    G, s = setup_row
    assert run(G, None, ESZ, LIVE, {}, **ctx(G)).outcome == "WATCH_ONLY"
    d = run(G, None, ESZ, LIVE, {key(s): {"tier": "reliable"}}, validated=set(), **ctx(G))
    assert d.outcome == "WATCH_ONLY"                              # reliable tier but not in the validated registry


def test_step8_extended_and_invalidated(setup_row):
    G, s = setup_row
    ev = {key(s): {"tier": "reliable"}}
    atr = float(G["atr"].iloc[-1])
    d = run(G, None, ESZ, LIVE, ev, current_price=s.entry + s.direction * atr, **ctx(G))
    assert d.outcome == "REJECTED" and d.development == "extended"
    d = run(G, None, ESZ, LIVE, ev, current_price=s.stop - s.direction * 0.25, **ctx(G))
    assert d.outcome == "INVALIDATED"


def test_step10_and_12_size_and_costs(setup_row):
    G, s = setup_row
    ev = {key(s): {"tier": "reliable"}}
    assert run(G, None, ESZ, LIVE, ev, **ctx(G, budget=10)).outcome == "REJECTED"
    d = run(G, None, ESZ, LIVE, ev, cfg=PipelineConfig(max_cost_fraction=0.001), **ctx(G))
    assert d.outcome == "REJECTED" and d.steps[11]["passed"] is False


def test_all_steps_pass_gives_approved(setup_row):
    G, s = setup_row
    d = run(G, None, ESZ, LIVE, {key(s): {"tier": "reliable", "trades": 150}}, **ctx(G))
    assert d.outcome == "APPROVED" and d.action in ("LONG", "SHORT")
    assert all(x["passed"] in (True, None) for x in d.steps[:12]) and d.steps[12]["passed"] is True
    assert d.plan["suggested_contracts"] >= 1 and d.plan["risk_check"]["ok"]
    assert d.id == decision_id("ESZ26", s.name, "long" if s.direction > 0 else "short", d.bar_time)


def test_prior_plan_invalidated_when_price_crosses_its_stop(F):
    for i in range(len(F) - 1, 300, -1):
        if F.iloc[i]["rth"] and 60 <= F.iloc[i]["min_from_rth"] <= 300 and not detect(F, i, ES, SetupParams(flat_by_min_from_rth=400))[0]:
            G = F.iloc[:i + 1].copy()
            G.attrs.update(F.attrs)
            break
    last = float(G["c"].iloc[-1])
    prev = {"setup": "sweep_reversal", "direction": "long", "stop": last + 1.0}
    d = run(G, None, ESZ, LIVE, {}, prev_plan=prev, **ctx(G))
    assert d.outcome == "INVALIDATED" and d.development == "invalidated"


def test_decisions_are_stored_once_per_bar(settings, db, setup_row):
    from app.futures.service import FuturesService
    from app.settings.store import SettingsStore

    svc = FuturesService(settings, db, SettingsStore(db), provider=None)
    G, s = setup_row
    d = run(G, None, ESZ, LIVE, {}, **ctx(G)).to_dict()
    svc.record_decision(d)
    svc.record_decision({**d, "evaluated_at": (datetime.now(timezone.utc)).isoformat()})
    rows = svc.decisions("ESZ26")
    assert len(rows) == 1 and rows[0]["outcome"] == "WATCH_ONLY" and rows[0]["steps"]
