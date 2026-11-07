from datetime import date, datetime, time, timezone

import numpy as np
import pandas as pd
import pytest

from app.analysis import candles
from app.analysis import indicators as ind
from app.analysis.engine import key_levels, mtf_summary, snapshot
from app.analysis.features import bars_to_df, build
from app.core.market_clock import ET
from app.market_data.types import Timeframe

from .synth import daily, intraday


def test_rsi_matches_hand_computed_wilder():
    close = pd.Series([44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61,
                       46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 45.64])
    r = ind.rsi(close, 14)
    d = close.diff()
    g, lo = d.clip(lower=0), (-d).clip(lower=0)
    ag, al = g.iloc[1:15].mean(), lo.iloc[1:15].mean()
    assert r.iloc[14] == pytest.approx(100 - 100 / (1 + ag / al), rel=1e-9)
    ag, al = (ag * 13 + g.iloc[15]) / 14, (al * 13 + lo.iloc[15]) / 14
    assert r.iloc[15] == pytest.approx(100 - 100 / (1 + ag / al), rel=1e-9)
    assert r.iloc[:14].isna().all()


def test_atr_ema_bollinger_basics():
    df = bars_to_df(daily(n=60))
    a = ind.atr(df["high"], df["low"], df["close"], 14)
    tr = ind.true_range(df["high"], df["low"], df["close"])
    assert a.iloc[13] == pytest.approx(tr.iloc[0:14].mean())  # like TradingView: first TR = high-low, seed = SMA of 14
    e = ind.ema(df["close"], 9)
    assert e.iloc[:8].isna().all() and e.notna().iloc[8:].all()
    bb = ind.bollinger(df["close"])
    v = bb.dropna()
    assert len(v) == 41 and (v["bb_upper"] >= v["bb_lower"]).all()


def test_session_vwap_resets_and_matches_formula():
    ff = build(intraday(days=2), Timeframe.M5)
    df = ff.df
    day2 = df[df["session"] == df["session"].iloc[-1]]
    tp = (day2["high"] + day2["low"] + day2["close"]) / 3
    expected = (tp * day2["volume"]).cumsum() / day2["volume"].cumsum()
    assert np.allclose(day2["vwap"], expected)


def test_session_levels():
    bars = intraday(days=3)
    ff = build(bars, Timeframe.M5)
    df = ff.df
    s1, s2 = sorted(df["session"].unique())[:2]
    d1 = df[df["session"] == s1]
    d2 = df[df["session"] == s2]
    assert d2["pdh"].iloc[0] == pytest.approx(d1["high"].max()) and d2["pdc"].iloc[0] == pytest.approx(d1["close"].iloc[-1])
    first15 = d2.iloc[:3]
    assert d2["or_high"].iloc[5] == pytest.approx(first15["high"].max())
    assert not d2["or_complete"].iloc[1] and d2["or_complete"].iloc[2]
    pm = [b for b in bars if b.ts.astimezone(ET).date() == s2 and b.ts.astimezone(ET).time() < time(9, 30)]
    assert d2["pm_high"].iloc[0] == pytest.approx(max(b.high for b in pm))
    assert df.index.tz_convert(ET).map(lambda t: t.time() >= time(9, 30)).all()  # regular session only


def test_rvol_time_of_day():
    ff = build(intraday(days=6), Timeframe.M5)
    df = ff.df
    assert df[df["session"] == df["session"].iloc[0]]["rvol"].isna().all()  # no history yet
    assert df["rvol"].iloc[-1] == pytest.approx(1.0, abs=0.35)  # random volumes -> about normal


def test_features_are_causal():
    """Computing on truncated history must give identical rows: no look-ahead anywhere."""
    bars = intraday(days=5, seed=7)
    full = build(bars, Timeframe.M5).df
    for cut in (150, 260, len(full) - 7):
        cutoff_ts = full.index[cut - 1]
        part = build([b for b in bars if b.ts <= cutoff_ts], Timeframe.M5).df
        cols = [c for c in part.columns if c != "session"]
        a, b = part[cols].iloc[-1], full[cols].iloc[cut - 1]
        for col in cols:
            x, y = a[col], b[col]
            if isinstance(x, (float, np.floating)) and isinstance(y, (float, np.floating)):
                assert (np.isnan(x) and np.isnan(y)) or x == pytest.approx(y, rel=1e-9, abs=1e-9), col
            else:
                assert x == y, col


def test_structure_swings_confirm_late():
    closes = [100 + i * 0.2 for i in range(20)] + [104 - i * 0.3 for i in range(10)] + [101 + i * 0.25 for i in range(20)]
    bars = intraday(days=4, path=closes, vol=0.0005)
    df = build(bars, Timeframe.M5).df
    today = df[df["session"] == df["session"].iloc[-1]]
    peak_idx = int(np.argmax(today["high"].iloc[:30].values))
    row_confirm = today.iloc[peak_idx + 3]
    assert row_confirm["swing_high_new"] == pytest.approx(today["high"].iloc[peak_idx])
    assert pd.isna(today["swing_high_new"].iloc[peak_idx])  # not known on the pivot bar itself


def test_candle_patterns():
    df = pd.DataFrame({"open": [10, 10.5, 9.4, 10, 10], "high": [10.6, 10.6, 10.8, 10.05, 11.5],
                       "low": [9.9, 9.5, 9.3, 9.0, 9.95], "close": [10.5, 9.6, 10.7, 9.98, 10.02]})
    f = candles.detect(df, pd.Series([0.5] * 5))
    assert f["bullish_engulfing"].iloc[2] and not f["bullish_engulfing"].iloc[1]
    assert f["bearish_pin_bar"].iloc[4] and f["doji"].iloc[4]
    assert f["bullish_pin_bar"].iloc[3] is not None


def test_snapshot_and_levels_on_daily():
    ff = build(daily(n=260), Timeframe.D1)
    snap = snapshot(ff)
    assert snap["available"] and snap["timeframe"] == "1Day" and snap["session"]["vwap"] is None
    assert snap["moving_averages"]["sma200"] is not None
    assert snap["bias"]["label"] in ("bullish", "bearish", "mixed")
    lv = key_levels(ff.df, len(ff.df) - 1)
    assert any(l["kind"] == "pdh" for l in lv) and all("side" in l for l in lv)


def test_mtf_alignment():
    s = lambda b: {"available": True, "bias": {"label": b, "score": 60}, "structure": {"state": "uptrend"}}  # noqa: E731
    assert mtf_summary({"5Min": s("bullish"), "1Hour": s("bullish")})["aligned"]
    assert not mtf_summary({"5Min": s("bullish"), "1Hour": s("bearish")})["aligned"]


def test_volume_profile():
    vp = ind.volume_profile(pd.Series([10, 10, 10, 11, 12, 10, 10]), pd.Series([100, 100, 100, 1, 1, 100, 100]), bins=4)
    assert vp["poc"] < 10.5 and vp["val"] <= 10 <= vp["vah"]
