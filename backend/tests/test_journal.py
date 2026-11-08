"""Stage 11: journal trades, plan checks, mistake detection, performance math, and the API end to end."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.journal.analysis import build_trade, detect_mistakes, mistake_summary, performance, plan_checks
from app.main import create_app
from app.paper.trades import RoundTrip

from .fakes import FakeProvider, always_open_clock
from .test_api import client_for

T0 = datetime(2026, 11, 24, 15, 0, tzinfo=timezone.utc)  # 10:00 ET


def rt(direction="long", entry=100.0, exit_=None, qty=10, opened=T0, minutes=30, roles=("stop_loss",), comm=0.0, first="o1"):
    t = RoundTrip(symbol="AAPL", direction=direction, opened_at=opened, max_qty=qty, entry_qty=qty, entry_value=entry * qty,
                  commissions=comm, fill_ids=[f"f-{opened.isoformat()}"], entry_order_ids=[first], first_entry_order=first)
    if exit_ is not None:
        sgn = 1 if direction == "long" else -1
        t.exit_qty, t.exit_value = qty, exit_ * qty
        t.gross_pnl = (exit_ - entry) * qty * sgn
        t.closed_at = opened + timedelta(minutes=minutes)
        t.exit_roles = list(roles)
    return t


def order(stop=99.0, target=102.0, ctx=None):
    return {"o1": {"id": "o1", "bracket_stop": stop, "bracket_target": target, "context": ctx or {}, "role": "entry"}}


SIG = {"id": "AAPL|vwap_reclaim|5Min", "setup": "vwap_reclaim", "setup_name": "VWAP reclaim", "entry_range": [99.9, 100.2],
       "stop": 99.0, "state": "confirmed", "tradeable": False, "evidence_tier": "inconclusive"}


def test_trade_math_r_multiple_and_costs():
    t = build_trade(rt(exit_=102.0, roles=("take_profit",), comm=2.0), order())
    assert t["realized_pnl"] == 18.0                      # 20 gross - 2 commission
    assert t["risk_dollars"] == 10.0 and t["r_multiple"] == 1.8
    assert t["planned_r"] == 2.0 and t["exit_type"] == "target"
    short = build_trade(rt("short", entry=100, exit_=101, roles=("stop_loss",)), order(stop=101, target=98))
    assert short["realized_pnl"] == -10.0 and short["r_multiple"] == -1.0


def test_open_trade_uses_mark_for_unrealized():
    t = build_trade(rt(exit_=None), order(), mark=100.5)
    assert t["open"] and t["unrealized_pnl"] == 5.0 and t["r_multiple"] == 0.5


def test_plan_checks():
    good = build_trade(rt(entry=100.0, exit_=99.0), order(ctx={"signal": SIG, "max_risk_dollars": 125}))
    assert good["followed_plan_auto"], good["plan_checks"]
    late = build_trade(rt(entry=100.6, exit_=99.0), order(ctx={"signal": SIG, "max_risk_dollars": 125}))
    assert not late["followed_plan_auto"]
    assert next(c for c in late["plan_checks"] if c["check"].startswith("Entry inside"))["passed"] is False
    nostop = build_trade(rt(exit_=98.0, roles=("exit",)), order(stop=None, target=None))
    assert nostop["plan_checks"][0]["passed"] is False and nostop["r_multiple"] is None
    manual = plan_checks({**good, "exit_type": "manual"})
    assert next(c for c in manual if c["check"].startswith("Exited"))["passed"] is False


def _with_mistakes(trades, **kw):
    detect_mistakes(trades, **kw)
    return {m["code"] for t in trades for m in t["mistakes"]}


def test_each_mistake_detector():
    ctx = {"signal": {**SIG, "state": "extended", "state_reason": "ran past"}, "ext_from_ema9_atr": 2.6,
           "market": {"high_risk": True, "reasons": ["SPY down 2%"]}, "data_label": {"status": "stale"}, "max_risk_dollars": 125}
    t1 = build_trade(rt(entry=100.6, exit_=100.9, roles=("exit",)), order(ctx=ctx))         # late, chasing, early exit, bad conditions
    t1["context"]["trend_alignment"] = "against trend"
    codes = _with_mistakes([t1])
    assert {"late_entry", "chasing", "early_exit", "bad_conditions"} <= codes
    t2 = build_trade(rt(exit_=97.5, roles=("exit",)), order(stop=None, target=None))         # no stop
    t3 = build_trade(rt(exit_=98.5, roles=("exit",)), order())                                # -1.5R: held loser
    assert {"ignored_stop"} <= _with_mistakes([t2]) and "held_loser" in _with_mistakes([t3])


def test_overtrading_revenge_and_poor_setup():
    trades = []
    for k in range(5):
        o = T0 + timedelta(minutes=40 * k)
        ctx = {"signal": {**SIG, "evidence_tier": "negative"}}
        t = build_trade(rt(entry=100, exit_=99, opened=o, minutes=30, first=f"o{k}"),
                        {f"o{k}": {"id": f"o{k}", "bracket_stop": 99, "bracket_target": 102, "context": ctx}})
        trades.append(t)
    detect_mistakes(trades, max_trades_per_day=3)
    assert any(m["code"] == "overtrading" and "#4" in m["evidence"] for m in trades[3]["mistakes"])
    assert any(m["code"] == "overtrading" and "after closing a loss" in m["evidence"] for m in trades[1]["mistakes"])
    assert all(any(m["code"] == "poor_setup" for m in t["mistakes"]) for t in trades)


def test_performance_numbers():
    trades = [build_trade(rt(entry=100, exit_=x, opened=T0 + timedelta(days=k), roles=("take_profit" if x > 100 else "stop_loss",),
                             first="o1"), order())
              for k, x in enumerate([102, 99, 99, 102, 99])]
    for t in trades:
        t["followed_plan"] = True
    detect_mistakes(trades)
    p = performance(trades)
    assert p["closed_trades"] == 5 and p["net_pnl"] == 10.0     # +20 -10 -10 +20 -10
    assert p["win_rate"] == 40.0 and p["avg_winner"] == 20.0 and p["avg_loser"] == -10.0
    assert p["profit_factor"] == round(40 / 30, 2) and p["expectancy"] == 2.0
    assert p["total_r"] == 1.0 and p["avg_r"] == 0.2
    assert p["max_drawdown"] == -20.0                            # +20 -> 0 after two losses
    assert p["by_symbol"][0]["bucket"] == "AAPL" and "sample_warning" in p
    assert mistake_summary(trades) == []


async def test_journal_end_to_end(settings):
    prov = FakeProvider()
    app = create_app(settings, provider=prov, clock=always_open_clock())
    async with app.router.lifespan_context(app), client_for(app) as c:
        await asyncio.sleep(0.05)
        prov.stream.push("AAPL", 200.0, bid=199.99, ask=200.01)
        o = {"symbol": "AAPL", "side": "buy", "qty": 20, "type": "market", "stop_loss": 197.0, "take_profit": 206.0, "confirm": True}
        r = await c.post("/api/paper/orders", json=o)
        assert r.status_code == 201, r.text
        open_tr = (await c.get("/api/journal/trades", params={"status": "open"})).json()
        assert len(open_tr) == 1 and open_tr[0]["context"]["max_risk_dollars"] == 125.0
        key = open_tr[0]["key"]
        prov.stream.push("AAPL", 206.5)                     # target fills
        await asyncio.sleep(0.05)
        closed = (await c.get("/api/journal/trades", params={"status": "closed"})).json()
        assert len(closed) == 1 and closed[0]["exit_type"] == "target" and closed[0]["r_multiple"] == pytest.approx(5.99 / 3.01, abs=0.005)  # bought at the 200.01 ask
        n = await c.post(f"/api/journal/trades/{key}/notes", json={"text": "Waited for the reclaim, good patience."})
        assert n.status_code == 201
        t = (await c.patch(f"/api/journal/trades/{key}", json={"tags": ["A+", "patience"], "followed_plan": False})).json()
        assert t["notes"][0]["text"].startswith("Waited") and t["tags"] == ["A+", "patience"] and t["followed_plan"] is False
        t = (await c.patch(f"/api/journal/trades/{key}", json={"clear_followed_plan": True})).json()
        assert t["followed_plan"] == t["followed_plan_auto"]
        perf = (await c.get("/api/journal/performance")).json()
        assert perf["closed_trades"] == 1 and perf["net_pnl"] == pytest.approx(120.0, abs=0.5)
        # survives a paper reset
        assert (await c.post("/api/paper/reset", json={"confirm": True})).status_code in (200, 201)
        assert len((await c.get("/api/journal/trades")).json()) == 1
        assert (await c.post("/api/journal/trades/nope/notes", json={"text": "x"})).status_code == 404


async def test_signal_log_dedupes(settings, db):
    from app.journal.service import JournalService

    class P:
        class engine:
            orders = {}
    j = JournalService(db, P, {})
    sig = {"id": "X|orb_breakout|5Min", "symbol": "X", "setup": "orb_breakout", "direction": "long", "timeframe": "5Min",
           "action": "POTENTIAL BUY", "state": "developing", "tradeable": False, "evidence_tier": "none", "confidence": {}}
    assert j.log_signals({"signals": [sig]}) == 1
    assert j.log_signals({"signals": [sig]}) == 0                      # unchanged -> not logged again
    assert j.log_signals({"signals": [{**sig, "state": "invalidated", "action": "NO TRADE"}]}) == 1
    rows = j.signals(symbol="X")
    assert [r["state"] for r in rows] == ["invalidated", "developing"]
