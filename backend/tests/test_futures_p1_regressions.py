"""Regression tests for the 0.7.0 audit's Critical and High findings (docs/AUDIT_0.7.md)."""
from datetime import datetime, timedelta

import pytest

from app.futures import contracts as fc
from app.futures.paper import FuturesPaperConfig, FuturesPaperEngine
from app.futures.risk import PersonalRisk, PropRules, load_presets
from app.futures.sessions import FuturesClock

FEES = load_presets()["fees"]["round_turn"]
ES = FuturesClock(fc.get("ES"))
OFF = dict(max_risk_per_trade_usd=None, max_daily_loss_usd=None, min_reward_risk=None, max_consecutive_losses=None, event_block_minutes=None)


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def eng(preset="topstep_tc_50k", personal=None, **cfg):
    return FuturesPaperEngine(PropRules.from_preset(preset), PersonalRisk(**{**OFF, **(personal or {})}), FuturesPaperConfig(**cfg), FEES)


def long_es(e, t, stop=5990.0, status="polling"):
    e.on_bar("ESZ26", t, 6000, 6000, 6000, 6000, None, status, ES)
    o, pv = e.submit("ESZ26", 1, 1, "market", ref_price=6000, now=t, clock=ES, data_status=status, bracket={"stop": stop, "targets": []})
    assert o, pv
    e.on_bar("ESZ26", t + timedelta(minutes=1), 6000, 6000, 6000, 6000, None, status, ES)


class _Svc:
    """Just enough of FuturesService to call its _feed."""
    def __init__(self, e):
        from app.futures.service import FuturesService
        self.engine = e
        self._feed = FuturesService._feed.__get__(self)


def test_c1_restart_applies_stop_hit_while_offline():
    e = eng(slippage_ticks_market=0, slippage_ticks_stop=0)
    t = utc("2026-11-10T15:00:00Z")
    long_es(e, t)
    state = e.to_state()
    e2 = eng(slippage_ticks_market=0, slippage_ticks_stop=0)
    e2.load_state(state)                                   # "restart"
    bars = [{"ts": t + timedelta(minutes=30 + i), "open": 6000, "high": 6000, "low": 5980 if i == 3 else 5999, "close": 6000, "volume": 100}
            for i in range(8)]
    _Svc(e2)._feed(fc.Contract("ES", 2026, 12), bars, {"status": "polling"}, ES)
    assert e2.positions["ESZ26"].qty == 0
    stop_fill = [f for f in e2.fills if f.role == "stop_loss"][0]
    assert stop_fill.price == 5990.0 and "downtime" in stop_fill.basis
    assert any("offline or asleep" in ev["text"] for ev in e2.events)


def test_c1_first_look_does_not_replay_history_into_new_contracts():
    e = eng()
    t = utc("2026-11-10T15:00:00Z")
    bars = [{"ts": t + timedelta(minutes=i), "open": 6000, "high": 6010, "low": 5990, "close": 6000, "volume": 100} for i in range(10)]
    _Svc(e)._feed(fc.Contract("ES", 2026, 12), bars, {"status": "polling"}, ES)
    assert e.last_bar_ts["ESZ26"] == (t + timedelta(minutes=8)).isoformat()


def test_c2_no_forced_fills_on_unfillable_data_then_flatten_on_next_fillable_bar():
    e = eng(allow_delayed_practice=True, slippage_ticks_market=0)
    long_es(e, utc("2026-11-10T20:00:00Z"), status="delayed")
    e.cfg.allow_delayed_practice = False
    f = e.on_bar("ESZ26", utc("2026-11-10T21:11:00Z"), 6001, 6001, 6001, 6001, None, "delayed", ES)
    assert f == [] and e.positions["ESZ26"].qty == 1           # nothing filled on delayed prices
    # the session ends with the position open: flagged, then flattened at the first fillable price
    e.on_bar("ESZ26", utc("2026-11-10T23:05:00Z"), 6003, 6003, 6003, 6003, None, "delayed", ES)
    assert e.locks.get("flat_violation") == "2026-11-10" and "ESZ26" in e.pending_flatten
    f = e.on_bar("ESZ26", utc("2026-11-10T23:10:00Z"), 6004, 6005, 6003, 6004, None, "polling", ES)
    assert f and f[0].role == "flatten" and f[0].price == 6004 and e.positions["ESZ26"].qty == 0


def test_c2_mll_not_evaluated_on_unfillable_marks():
    e = eng(allow_delayed_practice=True, slippage_ticks_market=0)
    long_es(e, utc("2026-11-10T15:00:00Z"), stop=5965.0, status="delayed")
    e.cfg.allow_delayed_practice = False
    e.on_bar("ESZ26", utc("2026-11-10T15:05:00Z"), 5950, 5950, 5950, 5950, None, "delayed", ES)
    assert not e.locks.get("mll_breached") and e.positions["ESZ26"].qty == 1


def test_c3_holiday_early_close_pulls_flat_time_earlier():
    e = eng(slippage_ticks_market=0)
    long_es(e, utc("2026-11-26T16:00:00Z"))                   # Thanksgiving, 10:00 CT
    st = e.risk_status(utc("2026-11-26T17:40:00Z"), ES)        # 11:40 CT
    assert st["official"]["minutes_to_flat"] == pytest.approx(18.0)
    assert "early close" in st["official"]["flat_reason"]
    assert any(w["code"] == "flat_soon" for w in st["warnings"])
    assert any(b["code"] == "flat_window" for b in e.risk_status(utc("2026-11-26T17:56:30Z"), ES)["blocks"])
    f = e.on_bar("ESZ26", utc("2026-11-26T17:58:00Z"), 6002, 6002, 6002, 6002, None, "polling", ES)   # 11:58 CT
    assert f and f[0].role == "flatten" and e.positions["ESZ26"].qty == 0


def test_h1_eod_floor_uses_value_at_the_close():
    e = eng(slippage_ticks_market=0, auto_flatten=False)
    long_es(e, utc("2026-11-10T20:00:00Z"), stop=5965.0)
    e.on_bar("ESZ26", utc("2026-11-10T21:59:00Z"), 6040, 6040, 6040, 6040, None, "polling", ES)   # last bar before the close
    e.on_bar("ESZ26", utc("2026-11-10T23:10:00Z"), 5990, 5990, 5990, 5990, None, "polling", ES)   # reopen lower
    assert e.mll_floor == pytest.approx(min(50000.0, 50000 - 1.89 + 2000 - 2000))


def test_h2_rule_edit_drops_confirmation_and_resize_needs_reset(settings, db):
    from app.futures.service import FuturesService
    from app.settings.store import SettingsStore

    svc = FuturesService(settings, db, SettingsStore(db), provider=None)
    r = svc.set_prop({}, confirm=True)
    assert r["confirmed"]
    r = svc.set_prop({**r, "max_loss_limit": 2500})            # the UI sends the old confirmed flag back
    assert r["confirmed"] is False
    # fresh account: a different size just re-bases it
    svc.use_preset("topstep_tc_150k")
    assert svc.engine.balance == 150000 and svc.engine.mll_floor == 145500
    # account with history: a size change blocks entries until reset
    svc.engine.balance = 150400.0
    svc.use_preset("topstep_tc_50k")
    st = svc.engine.risk_status(utc("2026-11-10T15:00:00Z"), ES)
    assert any(b["code"] == "reset_required" for b in st["blocks"])
    svc.reset()
    assert svc.engine.balance == 50000 and "reset_required" not in svc.engine.locks


def test_h3_duplicate_signal_entry_refused():
    e = eng()
    t = utc("2026-11-10T15:00:00Z")
    e.on_bar("ESZ26", t, 6000, 6000, 6000, 6000, None, "polling", ES)
    a, _ = e.submit("ESZ26", 1, 1, "limit", limit_price=5995.0, now=t, clock=ES, data_status="polling",
                    bracket={"stop": 5990.0, "targets": []}, signal_id="sig-1")
    b, pv = e.submit("ESZ26", 1, 1, "limit", limit_price=5995.0, now=t, clock=ES, data_status="polling",
                     bracket={"stop": 5990.0, "targets": []}, signal_id="sig-1")
    assert a and b is None and pv["duplicate_of"] == a.id


def test_h4_fills_persist_beyond_state_blob(settings, db):
    from app.futures.service import FuturesService
    from app.settings.store import SettingsStore

    store = SettingsStore(db)
    store.update({"futures.personal": PersonalRisk(**OFF).to_dict()})
    svc = FuturesService(settings, db, store, provider=None)
    long_es(svc.engine, utc("2026-11-10T15:00:00Z"))
    svc.save()
    svc.engine.fills.clear()                                   # the blob keeps only recent fills
    assert len(svc.all_fills("practice")) == 1


def test_h6_event_window_blocks_entries():
    e = eng(personal={"event_block_minutes": 15})
    t = utc("2026-11-10T13:25:00Z")                            # 08:25 ET; CPI at 08:30 ET
    e.upcoming_events = [("Consumer Price Index (CPI)", utc("2026-11-10T13:30:00Z"))]
    e.on_bar("ESZ26", t, 6000, 6000, 6000, 6000, None, "polling", ES)
    o, pv = e.submit("ESZ26", 1, 1, "market", ref_price=6000, now=t, clock=ES, data_status="polling", bracket={"stop": 5990.0, "targets": []})
    assert o is None and any("CPI" in p for p in pv["problems"])


def test_max_trades_per_session_and_slippage_limits():
    e = eng(personal={"max_trades_per_session": 1, "max_slippage_ticks": 2}, slippage_ticks_market=0)
    t = utc("2026-11-10T15:00:00Z")
    long_es(e, t)
    e.flatten("ESZ26", t + timedelta(minutes=2), price=6000.0)
    o, pv = e.submit("ESZ26", 1, 1, "market", ref_price=6000, now=t + timedelta(minutes=3), clock=ES, data_status="polling",
                     bracket={"stop": 5990.0, "targets": []})
    assert o is None and any("entries already" in p for p in pv["problems"])
    e2 = eng(personal={"max_slippage_ticks": 2}, slippage_ticks_market=3)
    e2.on_bar("ESZ26", t, 6000, 6000, 6000, 6000, None, "polling", ES)
    o, pv = e2.submit("ESZ26", 1, 1, "market", ref_price=6000, now=t, clock=ES, data_status="polling", bracket={"stop": 5990.0, "targets": []})
    assert o is None and any("slippage" in p for p in pv["problems"])
