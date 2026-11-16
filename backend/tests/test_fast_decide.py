"""A fresh price, between full chart reads, may end a trade. It may never start one.

The fast path reads the price box about twice a second; the whole chart is read every couple of seconds. A stop
being hit used to wait for the next full read, which for an exit is the one case where the delay matters most.

So the fast path now re-checks exits and invalidations. The tests that matter are the ones about what it must
REFUSE to do: a price box shows a number and nothing else -- no candles, no indicators, no structure, no session,
no risk engine -- so nothing it sees can justify entering a trade. If that line ever moves, these fail.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.screen.chart_profile import ChartProfile
from app.screen.visual_monitor import VisualMonitor


def _now() -> datetime:
    return datetime(2026, 11, 16, 15, 30, tzinfo=timezone.utc)


class _RT:
    """The bits of a chart runtime that _fast_decide touches."""

    def __init__(self, active=None, potential=None):
        self.profile = ChartProfile(id="c", name="TopstepX chart", root="NQ", timeframe="1Min")
        self.active = active
        self.potential = potential
        self.recommendation = {"action": "WAIT", "reason": "waiting", "contract": "NQZ26"}
        self.alerts: list[tuple] = []


@pytest.fixture
def mon(monkeypatch):
    m = VisualMonitor.__new__(VisualMonitor)
    fired: list[dict] = []
    pushed: list[int] = []
    m._alert = lambda rt, kind, level, title, body, fp: fired.append(
        {"kind": kind, "level": level, "title": title, "body": body, "fp": fp})
    m._alerts_for = lambda rt, rec, now: fired.append({"kind": "rec", "action": rec["action"], "rec": rec})
    m._push = lambda: pushed.append(1)
    m.fired, m.pushed = fired, pushed
    return m


def _long(stop=27_600.0, t2=27_800.0):
    return {"contract": "NQZ26", "direction": "long", "entry": 27_650.0, "stop": stop, "target_1": 27_700.0,
            "target_2": t2, "setup": "pullback", "decision_id": "d1", "issued_at": _now().isoformat()}


def test_a_stop_hit_between_full_reads_is_announced_at_once(mon):
    rt = _RT(active=_long())
    mon._fast_decide(rt, _now(), 27_599.75)                  # a quarter point through the stop
    assert rt.recommendation["action"] == "EXIT"
    assert rt.recommendation["exit_kind"] == "stop"
    assert rt.recommendation["observed_price"] == 27_599.75
    assert rt.active is None, "the trade is over; it must not be tracked on"
    assert any(f.get("action") == "EXIT" for f in mon.fired), "the user has to be told"


def test_the_final_target_is_treated_the_same_way(mon):
    rt = _RT(active=_long())
    mon._fast_decide(rt, _now(), 27_800.25)
    assert rt.recommendation["action"] == "EXIT" and rt.recommendation["exit_kind"] == "target"
    assert rt.active is None


def test_a_short_is_read_the_right_way_round(mon):
    short = {**_long(stop=27_700.0, t2=27_500.0), "direction": "short", "entry": 27_650.0}
    rt = _RT(active=short)
    mon._fast_decide(rt, _now(), 27_700.25)                  # above the stop, which for a short is a loss
    assert rt.recommendation["action"] == "EXIT" and rt.recommendation["exit_kind"] == "stop"

    rt2 = _RT(active={**short})
    mon._fast_decide(rt2, _now(), 27_499.75)                 # below the target, which for a short is a win
    assert rt2.recommendation["exit_kind"] == "target"


def test_a_price_inside_the_trade_changes_nothing(mon):
    rt = _RT(active=_long())
    mon._fast_decide(rt, _now(), 27_660.0)
    assert rt.recommendation["action"] == "WAIT"
    assert rt.active is not None
    assert not mon.fired, "nothing happened, so nothing should be said"


def test_it_can_never_open_a_trade(mon):
    """The point of the whole file. A price box shows a number: no candles, no indicators, no structure, no session,
    no risk engine. Nothing it can see is grounds for entering a trade, however far the price moves."""
    for price in (1.0, 27_000.0, 27_650.0, 28_000.0, 99_999.0):
        rt = _RT(active=None, potential=None)
        mon._fast_decide(rt, _now(), price)
        assert rt.recommendation["action"] == "WAIT", f"price {price} produced {rt.recommendation['action']}"
        assert not any(f.get("action") in ("LONG", "SHORT") for f in mon.fired)
    assert not mon.fired


def test_a_potential_setup_going_through_its_level_is_called_invalid(mon):
    rt = _RT(potential={"setup": "pullback", "direction": "long", "entry": 27_650.0, "stop": 27_600.0})
    mon._fast_decide(rt, _now(), 27_599.0)
    assert rt.potential is None
    assert mon.fired and mon.fired[0]["kind"] == "invalid"
    assert "27600" in mon.fired[0]["fp"].replace(".0", "") or "27650" in mon.fired[0]["fp"].replace(".0", "")


def test_a_potential_setup_still_on_side_is_left_alone(mon):
    rt = _RT(potential={"setup": "pullback", "direction": "long", "entry": 27_650.0, "stop": 27_600.0})
    mon._fast_decide(rt, _now(), 27_640.0)
    assert rt.potential is not None and not mon.fired


def test_an_expired_trade_is_dropped_not_exited(mon):
    """A trade that has run out of time is not an exit signal -- saying "stop hit" about something that expired
    hours ago would be a lie about when it happened."""
    old = {**_long(), "issued_at": (_now() - timedelta(hours=8)).isoformat()}
    rt = _RT(active=old)
    mon._fast_decide(rt, _now(), 27_599.0)
    assert rt.active is None
    assert not any(f.get("action") == "EXIT" for f in mon.fired)


def test_an_incomplete_trade_record_is_ignored(mon):
    """Half a plan is not something to act on."""
    rt = _RT(active={"contract": "NQZ26", "direction": "long", "entry": 27_650.0, "stop": None, "target_2": None})
    mon._fast_decide(rt, _now(), 1.0)
    assert not mon.fired


def test_the_exit_says_where_its_levels_came_from(mon):
    """The price is from the box; the level it was compared against is from the last full reading. A user reading
    the alert should be able to tell which is which."""
    rt = _RT(active=_long())
    mon._fast_decide(rt, _now(), 27_599.0)
    detail = " ".join(rt.recommendation["details"])
    assert "price box" in detail and "full chart read" in detail
    assert "last full reading" in detail


# ---------------------------------------------------------------- an alert that arrives after the move is not help

def _mon():
    m = VisualMonitor.__new__(VisualMonitor)
    m.fired = []
    m._alert = lambda rt, kind, sev, title, body, fp: m.fired.append({"kind": kind, "title": title, "body": body})
    m._now = _now
    return m


def _plan(direction="long", entry=27_650.0, stop=27_600.0, price=27_650.0):
    return {"action": "LONG" if direction == "long" else "SHORT", "direction": direction, "entry": entry,
            "stop": stop, "target_1": 27_700.0, "target_2": 27_750.0, "observed_price": price,
            "setup": "pullback", "contract": "NQZ26", "decision_id": "d9", "reward_risk": 2.0,
            "data_confidence": 0.9, "captured_at": _now().isoformat()}


def test_an_entry_at_the_planned_price_is_sent():
    m = _mon()
    assert m._too_late(_plan()) is None
    m._alerts_for(_RT(), _plan(), _now())
    assert any(f["kind"] == "entry" for f in m.fired)


def test_a_better_price_than_planned_is_not_late():
    """Price moving AGAINST the entry gives a better fill than the plan asked for. That is not a missed trade."""
    m = _mon()
    assert m._too_late(_plan(price=27_630.0)) is None          # long, price below entry: better
    assert m._too_late(_plan(direction="short", entry=27_650.0, stop=27_700.0, price=27_670.0)) is None


def test_an_entry_the_price_has_already_run_past_is_not_sent():
    """Risk here is 50 points. Thirty points past the entry is 60% of the way to the stop: taking it means a much
    bigger loss than the idea allowed and a worse reward for it. Not a trade, and not sent as one."""
    m = _mon()
    late = m._too_late(_plan(price=27_680.0))
    assert late and "Too late" in late and "60%" in late
    rec = _plan(price=27_680.0)
    m._alerts_for(_RT(), rec, _now())
    assert rec["action"] == "NO TRADE" and rec["late_entry"]
    assert not any(f["kind"] == "entry" for f in m.fired), "this must never go out as an entry"
    assert any(f["kind"] == "late" for f in m.fired), "but the miss is worth recording"


def test_the_same_rule_applies_to_a_short():
    m = _mon()
    assert m._too_late(_plan(direction="short", entry=27_650.0, stop=27_700.0, price=27_620.0))
    assert m._too_late(_plan(direction="short", entry=27_650.0, stop=27_700.0, price=27_645.0)) is None


def test_just_inside_the_line_is_still_sent():
    """A quarter of the way to the stop is the line. It has to be a line somewhere, and either side of it must
    behave predictably rather than drifting with rounding."""
    m = _mon()
    assert m._too_late(_plan(price=27_650.0 + 50 * 0.25)) is None
    assert m._too_late(_plan(price=27_650.0 + 50 * 0.26))


def test_a_plan_with_no_price_or_no_stop_is_left_alone():
    m = _mon()
    assert m._too_late({"entry": 1.0, "stop": None, "observed_price": 2.0, "direction": "long"}) is None
    assert m._too_late({"entry": 1.0, "stop": 1.0, "observed_price": 2.0, "direction": "long"}) is None, "no risk, no scale"
    assert m._too_late({"entry": None, "stop": 1.0, "observed_price": 2.0, "direction": "long"}) is None
