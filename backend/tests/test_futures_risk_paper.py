from datetime import datetime

import pytest

from app.futures import contracts as fc
from app.futures.paper import FuturesPaperConfig, FuturesPaperEngine
from app.futures.risk import PersonalRisk, PropRules, RiskEngine, load_presets, next_eod_floor, next_trade_day_start
from app.futures.sessions import FuturesClock

FEES = load_presets()["fees"]["round_turn"]


def utc(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def eng(preset="topstep_tc_50k", personal=None, **cfg):
    rules = PropRules.from_preset(preset)
    pers = PersonalRisk.from_dict(personal or {"max_risk_per_trade_usd": None, "max_daily_loss_usd": None, "min_reward_risk": None,
                                               "max_consecutive_losses": None})
    return FuturesPaperEngine(rules, pers, FuturesPaperConfig(**cfg), FEES)


ES = FuturesClock(fc.get("ES"))
T0 = utc("2026-11-10T15:00:00Z")   # Tue 09:00 CT, RTH


def bar(e, contract, ts, o, h, lo, c, v=None, status="polling"):
    return e.on_bar(contract, utc(ts) if isinstance(ts, str) else ts, o, h, lo, c, v, status, ES)


def test_presets_have_sources_and_start_unconfirmed():
    p = load_presets()
    assert p["topstep_sources"] and p["verified_on"]
    for pre in p["presets"]:
        r = PropRules.from_preset(pre["id"])
        assert r.confirmed is False
    tc = PropRules.from_preset("topstep_tc_50k")
    assert (tc.max_loss_limit, tc.profit_target, tc.max_minis, tc.daily_loss_limit) == (2000, 3000, 5, None)
    xfa = PropRules.from_preset("topstep_xfa_100k")
    assert xfa.starting_balance == 0 and xfa.initial_floor() == -3000 and xfa.mll_lock_balance == 0


def test_eod_trailing_floor_moves_up_only_and_locks():
    r = PropRules.from_preset("topstep_tc_50k")
    f = r.initial_floor()
    assert f == 48000
    f = next_eod_floor(r, f, 50500)
    assert f == 48500                        # follows best EOD balance
    assert next_eod_floor(r, f, 50000) == 48500   # never down
    f = next_eod_floor(r, f, 53000)
    assert f == 50000                        # locks at starting balance
    assert next_eod_floor(r, f, 60000) == 50000
    x = PropRules.from_preset("topstep_xfa_50k")
    assert next_eod_floor(x, -2000, 500) == -1500
    assert next_eod_floor(x, -1500, 2000) == 0     # XFA locks at $0 (help.topstep.com example)


def test_trade_day_reset_time():
    assert next_trade_day_start(utc("2026-11-10T16:00:00Z")).isoformat().startswith("2026-11-10T17:00:00-06:00")
    assert next_trade_day_start(utc("2026-11-13T21:30:00Z")).isoformat().startswith("2026-11-15T17:00:00-06:00")  # Fri -> Sun


def test_market_order_fills_with_slippage_and_fees_and_tick_pnl():
    e = eng()
    bar(e, "ESZ26", T0, 6000, 6000, 6000, 6000)           # sets trade date + mark
    o, pv = e.submit("ESZ26", +1, 2, "market", ref_price=6000, now=T0, clock=ES, data_status="polling",
                     bracket={"stop": 5990.0, "targets": []})
    assert o and pv["ok"], pv
    f = bar(e, "ESZ26", "2026-11-10T15:01:00Z", 6000.0, 6002, 5999, 6001)
    assert f[0].price == 6000.25 and f[0].qty == 2               # 1 tick adverse slippage
    assert f[0].fee == pytest.approx(3.78)                       # 2 contracts x $1.89 per side
    s = e.summary(T0)
    assert s["positions"][0]["unrealized"] == pytest.approx(2 * 3 * 12.5)   # 6000.25 -> 6001 = 3 ticks
    # stop protects the whole position
    stops = [x for x in e.orders.values() if x.role == "stop_loss" and x.active]
    assert len(stops) == 1 and stops[0].qty == 2 and stops[0].stop_price == 5990.0


def test_limit_needs_trade_through_and_gap_fills_better():
    e = eng(slippage_ticks_market=0)
    bar(e, "MESZ26", T0, 6000, 6000, 6000, 6000)
    o, _ = e.submit("MESZ26", +1, 1, "limit", limit_price=5995.0, now=T0, clock=ES, data_status="polling",
                    bracket={"stop": 5990.0, "targets": []}, )
    assert not bar(e, "MESZ26", "2026-11-10T15:01:00Z", 5998, 5999, 5995.0, 5996)   # touch only: no fill
    f = bar(e, "MESZ26", "2026-11-10T15:02:00Z", 5996, 5996, 5994.75, 5995.5)        # one tick through
    assert f and f[0].price == 5995.0
    e2 = eng()
    bar(e2, "MESZ26", T0, 6000, 6000, 6000, 6000)
    e2.submit("MESZ26", +1, 1, "limit", limit_price=5995.0, now=T0, clock=ES, data_status="polling", bracket={"stop": 5990.0, "targets": []})
    f = bar(e2, "MESZ26", "2026-11-10T15:01:00Z", 5993.0, 5994, 5992, 5993.5)       # gapped below
    assert f[0].price == 5993.0


def test_stop_and_target_same_bar_assumes_stop():
    e = eng(slippage_ticks_market=0, slippage_ticks_stop=0)
    bar(e, "ESZ26", T0, 6000, 6000, 6000, 6000)
    e.submit("ESZ26", +1, 1, "market", ref_price=6000, now=T0, clock=ES, data_status="polling",
             bracket={"stop": 5995.0, "targets": [{"price": 6010.0, "qty": 1}]})
    bar(e, "ESZ26", "2026-11-10T15:01:00Z", 6000, 6000, 6000, 6000)
    f = bar(e, "ESZ26", "2026-11-10T15:02:00Z", 6000, 6011, 5994, 6005)
    assert f[0].role == "stop_loss" and f[0].price == 5995.0
    assert not any(x.active for x in e.orders.values())          # target canceled with the position flat
    assert e.positions["ESZ26"].qty == 0


def test_partial_fills_by_volume_and_bracket_resizes():
    e = eng(participation=0.1, slippage_ticks_market=0)
    bar(e, "MNQZ26", T0, 21000, 21000, 21000, 21000)
    e.submit("MNQZ26", +1, 10, "market", ref_price=21000, now=T0, clock=ES, data_status="polling",
             bracket={"stop": 20990.0, "targets": [{"price": 21020.0, "qty": 10}]})
    f = bar(e, "MNQZ26", "2026-11-10T15:01:00Z", 21000, 21001, 20999, 21000, v=40)   # 10% of 40 = 4
    assert f[0].qty == 4
    entry = next(x for x in e.orders.values() if x.role == "entry")
    assert entry.status == "partial" and entry.remaining == 6
    stop = next(x for x in e.orders.values() if x.role == "stop_loss")
    assert stop.qty == 4                                           # covers only what's filled
    bar(e, "MNQZ26", "2026-11-10T15:02:00Z", 21000, 21001, 20999, 21000, v=1000)
    assert entry.status == "filled"
    assert stop.qty == 10


def test_short_pnl_and_round_trip_net_of_fees():
    e = eng(slippage_ticks_market=0)
    bar(e, "NQZ26", T0, 21000, 21000, 21000, 21000)
    e.submit("NQZ26", -1, 1, "market", ref_price=21000, now=T0, clock=ES, data_status="polling", bracket={"stop": 21010.0, "targets": []})
    bar(e, "NQZ26", "2026-11-10T15:01:00Z", 21000, 21000, 21000, 21000)
    e.flatten("NQZ26", utc("2026-11-10T15:05:00Z"), price=20990.0)
    assert e.balance == pytest.approx(50000 + 200 - 3.78)          # 10 points x $20 minus round-turn fees
    assert e.trades_today["2026-11-10"] == [pytest.approx(196.22)]


def test_unknown_fee_falls_back_to_commission_and_is_flagged():
    e = eng()
    fee, note = e.fee_per_side("YM")
    assert fee == 0.5 and "isn't set" in note
    assert e.fee_per_side("MYM")[0] == 0.25


def test_delayed_data_blocks_fills_unless_practice_mode():
    e = eng()
    bar(e, "ESZ26", T0, 6000, 6000, 6000, 6000, status="delayed")
    o, pv = e.submit("ESZ26", +1, 1, "market", ref_price=6000, now=T0, clock=ES, data_status="delayed", bracket={"stop": 5990.0, "targets": []})
    assert o is None and "delayed" in " ".join(pv["problems"])
    e2 = eng(allow_delayed_practice=True)
    bar(e2, "ESZ26", T0, 6000, 6000, 6000, 6000, status="delayed")
    o, pv = e2.submit("ESZ26", +1, 1, "market", ref_price=6000, now=T0, clock=ES, data_status="delayed", bracket={"stop": 5990.0, "targets": []})
    assert o and any("Practice" in w for w in pv["warnings"])
    f = bar(e2, "ESZ26", "2026-11-10T15:01:00Z", 6000, 6000, 6000, 6000, status="delayed")
    assert "DELAYED" in f[0].basis


def test_position_limit_counts_micros_ten_to_one():
    e = eng()
    bar(e, "MESZ26", T0, 6000, 6000, 6000, 6000)
    o, pv = e.submit("MESZ26", +1, 51, "market", ref_price=6000, now=T0, clock=ES, data_status="polling", bracket={"stop": 5999.0, "targets": []})
    assert o is None and any("limit is 5" in p for p in pv["problems"])
    o, pv = e.submit("MESZ26", +1, 50, "market", ref_price=6000, now=T0, clock=ES, data_status="polling", bracket={"stop": 5999.0, "targets": []})
    assert o is not None


def test_personal_limits_block_and_are_separate_from_firm_rules():
    e = eng(personal={"max_risk_per_trade_usd": 100, "max_daily_loss_usd": 300, "min_reward_risk": 2.0, "max_consecutive_losses": 2})
    bar(e, "ESZ26", T0, 6000, 6000, 6000, 6000)
    o, pv = e.submit("ESZ26", +1, 1, "market", ref_price=6000, now=T0, clock=ES, data_status="polling",
                     bracket={"stop": 5990.0, "targets": [{"price": 6030.0, "qty": 1}]})
    assert o is None and any("per-trade limit" in p for p in pv["problems"])     # 40 ticks x 12.5 = $500 + costs
    o, pv = e.submit("ESZ26", +1, 1, "market", ref_price=6000, now=T0, clock=ES, data_status="polling",
                     bracket={"stop": 5998.0, "targets": [{"price": 6001.0, "qty": 1}]})
    assert o is None and any("Reward-to-risk" in p for p in pv["problems"])


def test_consecutive_losses_lock_and_manual_review():
    e = eng(personal={"max_consecutive_losses": 2, "max_risk_per_trade_usd": None, "max_daily_loss_usd": None, "min_reward_risk": None},
            slippage_ticks_market=0)
    bar(e, "MESZ26", T0, 6000, 6000, 6000, 6000)
    t = T0
    for _ in range(2):
        e.submit("MESZ26", +1, 1, "market", ref_price=6000, now=t, clock=ES, data_status="polling", bracket={"stop": 5990.0, "targets": []})
        bar(e, "MESZ26", t, 6000, 6000, 6000, 6000)
        e.flatten("MESZ26", t, price=5999.0)
    st = e.risk_status(t, ES)
    assert st["blocked"] and any(b["code"] == "consecutive_losses" and b["needs_review"] for b in st["blocks"])
    with pytest.raises(ValueError):
        e.manual_review("ok", t)
    e.manual_review("Two chop losses at VWAP; waiting for a cleaner setup.", t)
    assert not any(b["code"] == "consecutive_losses" for b in e.risk_status(t, ES)["blocks"])


def test_mll_breach_liquidates_and_locks_until_reset():
    e = eng(slippage_ticks_market=0, slippage_ticks_stop=0)
    bar(e, "ESZ26", T0, 6000, 6000, 6000, 6000)
    e.submit("ESZ26", +1, 5, "market", ref_price=6000, now=T0, clock=ES, data_status="polling", bracket={"stop": 5995.0, "targets": []})
    bar(e, "ESZ26", "2026-11-10T15:01:00Z", 6000, 6000, 6000, 6000)
    e.cancel(next(x.id for x in e.orders.values() if x.role == "stop_loss"))   # remove the stop, then crash
    bar(e, "ESZ26", "2026-11-10T15:02:00Z", 6000, 6000, 5990, 5990)   # -$2,500 on 5 ES
    assert e.locks.get("mll_breached")
    assert e.positions["ESZ26"].qty == 0
    st = e.risk_status(utc("2026-11-10T15:03:00Z"), ES)
    assert any(b["code"] == "mll_breached" for b in st["blocks"])
    e.reset()
    assert e.balance == 50000 and not e.locks


def test_mll_check_includes_unrealized_and_trade_that_would_breach_is_blocked():
    e = eng()
    bar(e, "ESZ26", T0, 6000, 6000, 6000, 6000)
    o, pv = e.submit("ESZ26", +1, 5, "market", ref_price=6000, now=T0, clock=ES, data_status="polling", bracket={"stop": 5960.0, "targets": []})
    assert o is None and any("Maximum Loss Limit" in p for p in pv["problems"])   # 160 ticks x 12.5 x 5 = $10,000


def test_eod_rollover_records_day_and_trails_floor():
    e = eng(slippage_ticks_market=0)
    bar(e, "ESZ26", T0, 6000, 6000, 6000, 6000)
    e.submit("ESZ26", +1, 1, "market", ref_price=6000, now=T0, clock=ES, data_status="polling", bracket={"stop": 5990.0, "targets": []})
    bar(e, "ESZ26", "2026-11-10T15:01:00Z", 6000, 6000, 6000, 6000)
    e.flatten("ESZ26", utc("2026-11-10T16:00:00Z"), price=6010.0)          # +$500 - fees
    bar(e, "ESZ26", "2026-11-10T23:05:00Z", 6010, 6010, 6010, 6010)        # 17:05 CT -> trade date 11-11
    assert e.current_trade_date == "2026-11-11"
    assert e.daily["2026-11-10"] == pytest.approx(500 - 3.78)
    assert e.mll_floor == pytest.approx(48000 + 500 - 3.78)


def test_auto_flatten_at_flat_time():
    e = eng(slippage_ticks_market=0)
    t = utc("2026-11-10T20:00:00Z")   # 14:00 CT
    bar(e, "ESZ26", t, 6000, 6000, 6000, 6000)
    e.submit("ESZ26", +1, 1, "market", ref_price=6000, now=t, clock=ES, data_status="polling", bracket={"stop": 5990.0, "targets": []})
    bar(e, "ESZ26", t, 6000, 6000, 6000, 6000)
    f = bar(e, "ESZ26", "2026-11-10T21:11:00Z", 6002, 6002, 6002, 6002)     # 15:11 CT
    assert any(x.role == "flatten" for x in f) and e.positions["ESZ26"].qty == 0


def test_flat_window_blocks_new_entries_and_warns_before():
    e = eng()
    bar(e, "ESZ26", utc("2026-11-10T20:55:00Z"), 6000, 6000, 6000, 6000)     # 14:55 CT
    st = e.risk_status(utc("2026-11-10T20:55:00Z"), ES)
    assert any(w["code"] == "flat_soon" for w in st["warnings"])
    st = e.risk_status(utc("2026-11-10T21:09:00Z"), ES)                     # 15:09 CT
    assert any(b["code"] == "flat_window" for b in st["blocks"])


def test_daily_loss_limit_soft_lockout_when_enabled():
    rules = PropRules.from_preset("topstep_tc_50k")
    rules.daily_loss_limit = 1000
    eng_ = FuturesPaperEngine(rules, PersonalRisk.from_dict({"max_daily_loss_usd": None, "max_risk_per_trade_usd": None,
                                                              "max_consecutive_losses": None, "min_reward_risk": None}),
                              FuturesPaperConfig(slippage_ticks_market=0), FEES)
    bar(eng_, "ESZ26", T0, 6000, 6000, 6000, 6000)
    o, pv = eng_.submit("ESZ26", +1, 2, "market", ref_price=6000, now=T0, clock=ES, data_status="polling",
                        bracket={"stop": 5985.0, "targets": []})
    assert o is None and any("Daily Loss Limit" in p for p in pv["problems"])   # $1,500 stop > $1,000 DLL
    eng_.submit("ESZ26", +1, 2, "market", ref_price=6000, now=T0, clock=ES, data_status="polling", bracket={"stop": 5992.0, "targets": []})
    bar(eng_, "ESZ26", T0, 6000, 6000, 6000, 6000)
    eng_.flatten("ESZ26", T0, price=5990.0)      # -$1,000 - fees
    st = eng_.risk_status(T0, ES)
    b = next(b for b in st["blocks"] if b["code"] == "dll_hit")
    assert b["until"] and not b["needs_review"]
    assert "simulator only" in st["sim_only_note"]


def test_warnings_before_limits():
    rules = PropRules.from_preset("topstep_tc_50k")
    eng_ = FuturesPaperEngine(rules, PersonalRisk(), FuturesPaperConfig(slippage_ticks_market=0), FEES)
    bar(eng_, "ESZ26", T0, 6000, 6000, 6000, 6000)
    eng_.balance = 48400   # 80% of the MLL used
    st = eng_.risk_status(T0, ES)
    assert any(w["code"] == "mll_near" and w["level"] == "high" for w in st["warnings"])


def test_consistency_tracking():
    r = PropRules.from_preset("topstep_tc_50k")
    eng_ = FuturesPaperEngine(r, PersonalRisk(), FuturesPaperConfig(), FEES)
    eng_.daily = {"2026-11-05": 1800.0, "2026-11-06": 400.0}
    eng_.balance = 52200
    st = eng_.risk_status(T0, ES)
    assert st["official"]["best_day_pct"] == 60.0 and st["official"]["consistency_ok"] is False


def test_expired_contract_and_off_grid_prices_rejected():
    e = eng()
    bar(e, "ESZ26", T0, 6000, 6000, 6000, 6000)
    o, pv = e.submit("ESZ25", +1, 1, "market", ref_price=6000, now=T0, clock=ES, data_status="polling", bracket={"stop": 5990.0, "targets": []})
    assert o is None and any("expired" in p for p in pv["problems"])
    o, pv = e.submit("ESZ26", +1, 1, "limit", limit_price=5995.1, now=T0, clock=ES, data_status="polling", bracket={"stop": 5990.0, "targets": []})
    assert o is None and any("tick grid" in p for p in pv["problems"])


def test_state_round_trip():
    e = eng(slippage_ticks_market=0)
    bar(e, "ESZ26", T0, 6000, 6000, 6000, 6000)
    e.submit("ESZ26", +1, 1, "market", ref_price=6000, now=T0, clock=ES, data_status="polling", bracket={"stop": 5990.0, "targets": []})
    bar(e, "ESZ26", T0, 6000, 6000, 6000, 6000)
    st = e.to_state()
    e2 = eng()
    e2.load_state(st)
    assert e2.positions["ESZ26"].qty == 1 and e2.balance == e.balance and len(e2.orders) == len(e.orders)


def test_risk_engine_reports_sim_only():
    r = RiskEngine(PropRules(), PersonalRisk())
    assert "cannot enforce" in r.evaluate(eng().snapshot(T0, ES))["sim_only_note"]


def test_no_false_daily_lock_when_market_closed():
    """With no trade date (weekend), an absent lock must not match a missing trade date."""
    e = eng(personal={"max_daily_loss_usd": 500})
    st = e.risk_status(utc("2026-11-08T15:00:00Z"), ES)   # Sunday morning: no session
    assert not any(b["code"] in ("personal_daily_loss", "dll_hit") for b in st["blocks"])
