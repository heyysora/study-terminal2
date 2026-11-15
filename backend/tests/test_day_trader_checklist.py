"""Ideas taken from the day-trader skill pack: an odds check for one plan (past days + simulated sessions), trades-per-day and
late-entry rules for stock practice (warnings unless you set a limit), and a reminder before the close. Synthetic bars here:
these tests check the rules, not any market."""
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pytest

from app.backtest.odds import data_symbol, default_start, odds_check
from app.signals.engine import close_reminder

from .test_paper_engine import LIVE, T0, at, buy, engine, ref

ET = ZoneInfo("America/New_York")


def walk(days=45, drift=0.0, vol=0.0015, seed=1):
    """5-minute bars 9:30-16:00 ET on weekdays, a random walk (optionally drifting)."""
    rng = np.random.default_rng(seed)
    out, d, price = [], datetime(2026, 9, 1).date(), 100.0
    while len([1 for b in out if b.ts.astimezone(ET).time() == time(9, 30)]) < days:
        if d.weekday() < 5:
            t = datetime.combine(d, time(9, 30), tzinfo=ET)
            for _ in range(78):
                r = rng.normal(drift, vol, 3)
                o = price
                c = o * np.exp(r[0])
                hi, lo = max(o, c) * np.exp(abs(r[1]) / 2), min(o, c) * np.exp(-abs(r[2]) / 2)
                out.append(NS(ts=t.astimezone(timezone.utc), open=o, high=hi, low=lo, close=c))
                price, t = c, t + timedelta(minutes=5)
        d += timedelta(days=1)
    return out


def test_odds_check_basic_and_honest():
    r = odds_check(walk(), "long", 100, 99, 101, "10:00", "15:55", sims=4000)
    s, p = r["simulation"], r["past_days"]
    assert abs(s["target_first_pct"] + s["stop_first_pct"] + s["neither_pct"] - 100) < 0.2
    assert p["target"] + p["stop"] + p["neither"] == p["days"] == 45
    assert s["breakeven_win_pct"] == 50.0 and r["plan"]["reward_risk"] == 1.0         # 1:1 needs more than half
    assert any("not a prediction" in n for n in r["notes"])


def test_drift_shows_up_and_direction_matters():
    up = walk(drift=0.0004, seed=3)
    assert odds_check(up, "long", 100, 99, 101, "10:00", "15:55", sims=4000)["tone"] == "good"
    assert odds_check(up, "short", 100, 101, 99, "10:00", "15:55", sims=4000)["tone"] == "bad"


def test_not_enough_time_and_bad_plans():
    r = odds_check(walk(), "long", 100, 95, 105, "15:40", "15:55", sims=2000)
    assert r["verdict"].startswith("Probably won't finish")
    for args, msg in [((100, 101, 102), "opposite sides"), ((100, 99, 101, "16:00"), "flat time")]:
        with pytest.raises(ValueError, match=msg):
            odds_check(walk(days=20), "long", *args[:3], args[3] if len(args) > 3 else "10:00", "15:55")
    with pytest.raises(ValueError, match="at least 15"):
        odds_check(walk(days=10), "long", 100, 99, 101, "10:00", "15:55")


def test_same_bar_stop_and_target_counts_as_stop():
    bars = []
    for i in range(20):
        d = datetime(2026, 10, 1, tzinfo=ET) + timedelta(days=i)
        for j, (o, h, lo, c) in enumerate([(100, 100, 100, 100), (100, 102, 98, 100), (100, 100, 100, 100)]):
            bars.append(NS(ts=(d.replace(hour=9, minute=55) + timedelta(minutes=5 * j)).astimezone(timezone.utc), open=o, high=h, low=lo, close=c))
    r = odds_check(bars, "long", 100, 99, 101, "10:00", "15:55", sims=500)
    assert r["past_days"]["stop"] == 20 and r["simulation"]["stop_first_pct"] == 100.0


def test_futures_contracts_use_the_free_continuous_symbol():
    assert [data_symbol(s) for s in ("MNQZ26", "MESH27", "NQZ6", "NQ=F", "SPY", "TSLA")] == ["NQ=F", "ES=F", "NQ=F", "NQ=F", "SPY", "TSLA"]


def test_default_start():
    assert default_start(datetime(2026, 11, 17, 10, 7, tzinfo=ET), "09:30", "15:55") == ("10:05", None)
    hhmm, note = default_start(datetime(2026, 11, 14, 13, 0, tzinfo=ET), "09:30", "15:55")
    assert hhmm == "10:00" and "isn't open" in note


def test_trades_per_day_warns_then_blocks_only_if_set():
    e = engine()
    for k in range(3):                                                  # three round trips today
        e.submit(buy(10, stop=99, tp=103), ref(100, k * 10), at(k * 10))
        e.on_price("TSLA", 103.2, at(k * 10 + 1), LIVE)          # winners, so the losses-in-a-row pause isn't what stops it
    assert e.trades_started_today(at(40)) == 3
    pv = e.preview(buy(10, stop=99, tp=103), ref(100, 40), at(40))
    assert pv.ok and any("trade #4 today" in w for w in pv.warnings)
    e.risk.max_trades_per_day = 3
    pv = e.preview(buy(10, stop=99, tp=103), ref(100, 40), at(40))
    assert not pv.ok and any("limit is 3" in x for x in pv.errors)


def test_late_entries_warn_then_block_only_if_set():
    e = engine()
    late = T0.astimezone(ET).replace(hour=15, minute=40).astimezone(timezone.utc)
    pv = e.preview(buy(10, stop=99, tp=103), ref(100), late)
    assert pv.ok and any("little time" in w for w in pv.warnings)
    assert not any("little time" in w for w in e.preview(buy(10, stop=99, tp=103), ref(100), at(0)).warnings)
    e.risk.no_new_entries_after = "15:30"
    pv = e.preview(buy(10, stop=99, tp=103), ref(100), late)
    assert not pv.ok and any("No new trades after 15:30" in x for x in pv.errors)


def test_close_reminder_window():
    day = datetime(2026, 11, 17, tzinfo=ET)
    assert close_reminder(["AAPL"], day.replace(hour=15, minute=40)) is None
    r = close_reminder(["AAPL", "TSLA"], day.replace(hour=15, minute=47))
    assert r and "2 practice trade" in r["title"] and "3:55 PM" in r["body"] and r["key"] == "close|2026-11-17"
    assert close_reminder([], day.replace(hour=15, minute=47)) is None
    assert close_reminder(["AAPL"], day.replace(hour=15, minute=47), regular_session=False) is None
    assert close_reminder(["AAPL"], day.replace(hour=16, minute=1)) is None


async def test_odds_endpoint(settings):
    from app.main import create_app

    from .test_futures_api import FutProvider, always_open_clock
    app = create_app(settings, provider=FutProvider(), clock=always_open_clock(), start_loops=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"X-Study-Terminal": "1"}) as c:
            import time as _t
            app.state.odds_bars = {"TSLA": (_t.monotonic(), walk())}
            r = await c.post("/api/odds", json={"symbol": "TSLA", "direction": "long", "entry": 100, "stop": 99, "target": 101, "start": "10:00"})
            assert r.status_code == 200 and r.json()["simulation"]["sessions"] == 10000 and "Yahoo" in r.json()["data"]["source"]
            assert (await c.post("/api/odds", json={"symbol": "BTC-USD", "direction": "long", "entry": 1, "stop": 0.9, "target": 1.1})).status_code == 400
            bad = await c.post("/api/odds", json={"symbol": "TSLA", "direction": "long", "entry": 100, "stop": 101, "target": 102, "start": "10:00"})
            assert bad.status_code == 400 and "opposite sides" in bad.json()["detail"]
