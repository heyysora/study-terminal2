import pandas as pd
import pytest

from app.analysis.features import build
from app.market_data.types import Timeframe
from app.signals.engine import MarketContext, build_plan, evaluate, lifecycle, manage_position
from app.signals.setups import SetupParams, detect

from .synth import intraday

LOOSE = SetupParams(rvol_min=0, vol_ratio_min=0)


def reclaim_frame():
    # last session: slide below VWAP for 25 bars, then rally back above it
    path = [100 - 0.08 * k for k in range(25)] + [98 + 0.12 * k for k in range(1, 30)]
    return build(intraday(days=4, path=path, vol=0.0005, seed=3), Timeframe.M5)


def test_detects_vwap_reclaim_on_scripted_path():
    ff = reclaim_frame()
    d = detect(ff.df, LOOSE, True)
    today = ff.df["session"].iloc[-1]
    rec = d[(d["setup"] == "vwap_reclaim") & (ff.df.loc[d.index, "session"] == today)]
    assert len(rec) >= 1
    first = rec.iloc[0]
    i = ff.df.index.get_loc(rec.index[0])
    assert ff.df["close"].iloc[i] > ff.df["vwap"].iloc[i] and ff.df["close"].iloc[i - 1] < ff.df["vwap"].iloc[i - 1]
    assert first["trigger"] > first["stop"]


def test_detect_is_causal():
    ff = reclaim_frame()
    full = detect(ff.df, LOOSE, True)
    cut = len(ff.df) - 15
    part = detect(ff.df.iloc[:cut], LOOSE, True)
    pd.testing.assert_frame_equal(part, full[full.index <= ff.df.index[cut - 1]])


def test_plan_math_and_lifecycle():
    ff = reclaim_frame()
    df = ff.df
    d = detect(df, LOOSE, True)
    ts = d[d["setup"] == "vwap_reclaim"].index[0]
    i = df.index.get_loc(ts)
    cand = d.loc[ts] if isinstance(d.loc[ts], pd.Series) else d.loc[ts].iloc[0]
    p = SetupParams(target_r=2.0)
    plan = build_plan(df, i, cand, p)
    r = plan["entry"] - plan["stop"]
    assert plan["t1"] == pytest.approx(plan["entry"] + r) and plan["t2"] == pytest.approx(plan["entry"] + 2 * r)
    assert plan["entry_high"] == pytest.approx(plan["entry"] + 0.25 * plan["atr"])
    sub = df.iloc[: i + 1]  # evaluate right at the signal bar
    atr = plan["atr"]
    assert lifecycle(sub, i, plan, "long", plan["entry"] - 1.0 * atr, p)[0] == "developing"
    assert lifecycle(sub, i, plan, "long", plan["entry"] - 0.1 * atr, p)[0] == "approaching"
    assert lifecycle(sub, i, plan, "long", plan["entry"] + 0.1 * atr, p)[0] == "confirmed"
    assert lifecycle(sub, i, plan, "long", plan["entry"] + 0.6 * atr, p)[0] == "extended"
    assert lifecycle(sub, i, plan, "long", plan["invalidation"] - 0.01, p)[0] == "invalidated"


def test_evaluate_produces_complete_signal():
    ff = reclaim_frame()
    df = ff.df
    d = detect(df, LOOSE, True)
    ts = d[d["setup"] == "vwap_reclaim"].index[0]
    i = df.index.get_loc(ts)
    sub = build(df.iloc[: i + 1][["open", "high", "low", "close", "volume"]], Timeframe.M5)
    trig = float(d.loc[ts]["trigger"] if isinstance(d.loc[ts], pd.Series) else d.loc[ts].iloc[0]["trigger"])
    res = evaluate("TEST", sub, live_price=trig + 0.01, params=LOOSE, market=MarketContext(bias="bullish"))
    sig = next(s for s in res["signals"] if s["setup"] == "vwap_reclaim")
    for key in ("symbol", "price", "direction", "entry_range", "stop", "targets", "reward_risk", "position_size", "invalidation",
                "supporting_indicators", "structure", "volume", "market", "timeframe", "confidence", "risks", "confirmation", "education"):
        assert key in sig, key
    # untested setup: a confirmed trigger is still only a watch-only idea, and the overall answer is NO TRADE
    assert sig["state"] == "confirmed" and sig["action"] == "POTENTIAL BUY" and sig["tradeable"] is False
    assert res["action"] == "NO TRADE" and res["watch"]["setup"] == "vwap_reclaim" and "NO TRADE" in res["reasons"][0]
    assert sig["position_size"]["risk_dollars"] <= 125.01  # 0.5% of $25k
    assert "NOT a probability" in sig["confidence"]["setup_quality"]["note"]
    assert sig["confidence"]["historical"]["available"] is False and sig["evidence_tier"] == "none"
    assert "In dollars" in sig["education"]["money"]


def test_data_gate_and_min_rr():
    ff = reclaim_frame()
    res = evaluate("TEST", ff, params=LOOSE, data_gate=(False, "delayed: Yahoo marks this delayed", None))
    assert res["action"] == "NO TRADE" and "disabled" in res["reasons"][0]
    res = evaluate("TEST", ff, params=LOOSE, data_gate=(True, "polled", "5Min"))
    assert "signals" in res  # 5Min allowed on polled data
    ff1 = build(intraday(days=3, minutes=1, seed=4), Timeframe.M1)
    res = evaluate("TEST", ff1, params=LOOSE, data_gate=(True, "polled", "5Min"))
    assert res["action"] == "NO TRADE" and "not fast enough" in res["reasons"][0]
    res = evaluate("TEST", ff, params=SetupParams(rvol_min=0, vol_ratio_min=0, target_r=1.5), min_rr=2.0, lookback_bars=400)
    assert all(s["action"] == "NO TRADE" for s in res["signals"])


def test_manage_position_actions():
    ff = reclaim_frame()
    last = float(ff.df["close"].iloc[-1])
    pos = {"symbol": "TEST", "qty": 10, "avg_price": last - 2.0, "stop_loss": last - 3.0, "take_profit": last + 2}
    assert manage_position(pos, ff, last)["action"] == "TAKE PARTIAL PROFITS"  # +2R
    near_stop = manage_position({**pos, "avg_price": last + 0.5, "stop_loss": last - 0.1}, ff, last)
    assert any(a["type"] == "stop_approaching" for a in near_stop["alerts"])
    nostop = manage_position({**pos, "stop_loss": None}, ff, last)
    assert any(a["type"] == "no_stop" for a in nostop["alerts"])


def _confirmed_reclaim():
    ff = reclaim_frame()
    df = ff.df
    d = detect(df, LOOSE, True)
    ts = d[d["setup"] == "vwap_reclaim"].index[0]
    i = df.index.get_loc(ts)
    sub = build(df.iloc[: i + 1][["open", "high", "low", "close", "volume"]], Timeframe.M5)
    return sub, float(d.loc[[ts]].iloc[0]["trigger"])


def _sig(sub, trig, **kw):
    res = evaluate("T", sub, live_price=trig + 0.01, params=LOOSE, **kw)
    return res, next(s for s in res["signals"] if s["setup"] == "vwap_reclaim")


def _ev(tier, avg, n=150, by_regime=None):
    return {"vwap_reclaim|long|5Min": {"tier": tier, "available": True, "tradeable": tier == "reliable", "trades": n,
                                       "avg_r": avg, "expectancy_r": avg, "note": f"OOS {avg:+.2f}R", "by_regime": by_regime or {}}}


def test_evidence_tiers_gate_actions():
    sub, trig = _confirmed_reclaim()
    # clearly losing: NO TRADE (study only), even though the trigger confirmed
    res, s = _sig(sub, trig, calibration=_ev("negative", -0.3))
    assert s["action"] == "NO TRADE" and "Study only" in s["risks"][0] and res["action"] == "NO TRADE"
    # inconclusive / promising / losing: watch only
    for t in ("inconclusive", "promising", "losing", "insufficient"):
        res, s = _sig(sub, trig, calibration=_ev(t, 0.05))
        assert s["action"] == "POTENTIAL BUY" and not s["tradeable"] and res["action"] == "NO TRADE", t
    # reliable: BUY is allowed and becomes the overall action
    res, s = _sig(sub, trig, calibration=_ev("reliable", 0.25), market=MarketContext(bias="bullish"))
    assert s["action"] in ("BUY", "STRONG BUY") and s["tradeable"] and res["action"] == s["action"]


def test_strong_requires_regime_history_not_just_checklist(monkeypatch):
    import app.signals.engine as se
    real = se.quality
    monkeypatch.setattr(se, "quality", lambda *a, **k: (95, real(*a, **k)[1]))  # pretend the checklist is near-perfect
    sub, trig = _confirmed_reclaim()
    _, s = _sig(sub, trig, calibration=_ev("reliable", 0.25), market=MarketContext(bias="bullish"))
    assert s["action"] == "BUY"  # high checklist but no record in the current regime -> not STRONG
    reg = s["regime"]
    assert reg is not None
    _, s2 = _sig(sub, trig, calibration=_ev("reliable", 0.25, by_regime={reg: {"trades": 60, "avg_r": 0.3}}))
    assert s2["action"] == "STRONG BUY"
    _, s3 = _sig(sub, trig, calibration=_ev("reliable", 0.25, by_regime={reg: {"trades": 60, "avg_r": -0.2}}))
    assert s3["action"] == "BUY"   # losing in this regime
    _, s4 = _sig(sub, trig, calibration=_ev("promising", 0.25, by_regime={reg: {"trades": 60, "avg_r": 0.3}}))
    assert s4["action"] == "POTENTIAL BUY"  # a perfect checklist on unproven evidence is still watch-only


def test_legacy_calibration_never_counts_as_reliable():
    sub, trig = _confirmed_reclaim()
    good_old = {"vwap_reclaim|5Min": {"available": True, "trades": 400, "expectancy_r": 0.4, "note": "x"}}
    _, s = _sig(sub, trig, calibration=good_old)
    assert s["evidence_tier"] == "inconclusive" and s["action"] == "POTENTIAL BUY"
    bad_old = {"vwap_reclaim|5Min": {"available": True, "trades": 40, "expectancy_r": -0.3, "note": "OOS -0.30R"}}
    _, s = _sig(sub, trig, calibration=bad_old)
    assert s["evidence_tier"] == "losing" and s["action"] == "POTENTIAL BUY"
