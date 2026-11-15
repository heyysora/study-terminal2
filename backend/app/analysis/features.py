"""Causal feature frame: one row per bar, every value computed only from that bar and earlier.

This one frame feeds live analysis, the signal engine, the scanner and the backtester, so
live behaviour and backtests can't drift apart. `tests/test_analysis.py` checks causality by
recomputing on truncated data and comparing.

Intraday frames contain regular-session rows only (09:30-16:00 ET). Extended-hours bars are
used solely for premarket high/low, because Yahoo reports their volume as 0.
"""
from __future__ import annotations

from datetime import datetime

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..core.market_clock import ET, regular_close_minute
from ..market_data.types import Bar, Timeframe
from . import candles, indicators as ind

SWING_K = 3          # bars on each side that define a swing high/low (confirmed K bars later)
OR_MINUTES = 15      # opening range length
RVOL_DAYS = 10       # sessions used for time-of-day relative volume


@dataclass
class FeatureFrame:
    df: pd.DataFrame
    timeframe: Timeframe
    intraday: bool
    notes: list[str]
    quality: dict | None = None          # validation report (market_data/validation.py)
    provider: str | None = None
    source: str | None = None
    fetched_at: datetime | None = None   # wall-clock time the bars were fetched
    served_from_cache: bool = False      # True when a refresh failed and an older copy is being shown
    refresh_error: str | None = None


def bars_to_df(bars: list[Bar]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame([{"ts": b.ts, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
                       for b in bars]).drop_duplicates("ts").set_index("ts").sort_index()
    df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
    return df


def _swings(high: pd.Series, low: pd.Series, k: int) -> tuple[pd.Series, pd.Series]:
    """Pivot values placed on the row where they become *known* (k bars after the pivot)."""
    win = 2 * k + 1
    ph = high.where(high == high.rolling(win, center=True, min_periods=win).max())
    pl = low.where(low == low.rolling(win, center=True, min_periods=win).min())
    return ph.shift(k), pl.shift(k)


def _last_two(confirmed: pd.Series) -> tuple[pd.Series, pd.Series]:
    vals = confirmed.dropna()
    last = confirmed.ffill()
    prev = pd.Series(vals.shift(1).values, index=vals.index).reindex(confirmed.index).ffill()
    return last, prev


def build(bars: list[Bar] | pd.DataFrame, timeframe: Timeframe, all_hours: bool = False) -> FeatureFrame:
    """all_hours: keep every bar (crypto trades 24/7); otherwise intraday frames keep the regular stock session only."""
    raw = bars if isinstance(bars, pd.DataFrame) else bars_to_df(bars)
    notes: list[str] = []
    intraday = timeframe != Timeframe.D1
    if raw.empty:
        return FeatureFrame(raw, timeframe, intraday, ["no bars"])

    et = raw.index.tz_convert(ET)
    minute = et.hour * 60 + et.minute
    date = pd.Series(et.date, index=raw.index)

    if intraday:
        # regular session per the exchange calendar: on early-close days (e.g. the day after Thanksgiving) bars after
        # 13:00 are after-hours, not part of the session
        closes = {d: regular_close_minute(d) for d in set(et.date)}
        close_min = np.array([closes[d] for d in et.date])
        regular = np.ones(len(raw), dtype=bool) if all_hours else (minute >= 570) & (minute < close_min)
        pm = raw[(minute >= 240) & (minute < 570)]
        pm_by_date = pm.groupby(pd.Series(pm.index.tz_convert(ET).date, index=pm.index)).agg(pm_high=("high", "max"), pm_low=("low", "min"))
        df = raw[regular].copy()
        df["session"] = date[regular].values
        df["minute"] = minute[regular]
        if df.empty:
            return FeatureFrame(df, timeframe, intraday, ["no regular-session bars"])
    else:
        df = raw.copy()
        df["session"] = date.values
        df["minute"] = 570
        pm_by_date = pd.DataFrame(columns=["pm_high", "pm_low"])

    o, h, l, c, v = (df[k].astype(float) for k in ("open", "high", "low", "close", "volume"))
    bar_min = timeframe.seconds // 60

    # ---- trend / momentum ----
    for n in (9, 21, 50, 200):
        df[f"ema{n}"] = ind.ema(c, n)
    for n in (20, 50, 200):
        df[f"sma{n}"] = ind.sma(c, n)
    df["rsi"] = ind.rsi(c, 14)
    df = df.join(ind.macd(c)).join(ind.stochastic(h, l, c))
    df["roc"] = ind.roc(c, 10)
    df["atr"] = ind.atr(h, l, c, 14)
    df["atr_pct"] = 100 * df["atr"] / c
    df["atr_pct_med"] = df["atr_pct"].rolling(200, min_periods=20).median()  # volatility regime baseline (causal)
    df = df.join(ind.bollinger(c))
    periods_per_year = 252 if not intraday else 252 * (390 / bar_min)
    df["hv"] = ind.historical_volatility(c, 20, periods_per_year)

    # ---- volume ----
    df["obv"] = ind.obv(c, v)
    df["obv_slope"] = df["obv"].diff(5)
    df["vol_sma20"] = v.rolling(20, min_periods=5).mean()
    df["vol_ratio"] = v / df["vol_sma20"].shift(1)
    df["vol_spike"] = df["vol_ratio"] >= 2.0
    clv = ind.close_location(h, l, c)
    df["clv"] = clv
    df["pressure"] = (clv * v).rolling(10, min_periods=3).sum() / v.rolling(10, min_periods=3).sum().replace(0, np.nan)

    # ---- session levels ----
    sess = df["session"]
    daily = df.groupby("session").agg(d_high=("high", "max"), d_low=("low", "min"), d_close=("close", "last"))
    prev = daily.shift(1)
    df["pdh"] = sess.map(prev["d_high"])
    df["pdl"] = sess.map(prev["d_low"])
    df["pdc"] = sess.map(prev["d_close"])
    if intraday:
        df["vwap"] = ind.session_vwap(h, l, c, v, sess)
        df["pm_high"] = sess.map(pm_by_date["pm_high"]) if len(pm_by_date) else np.nan
        df["pm_low"] = sess.map(pm_by_date["pm_low"]) if len(pm_by_date) else np.nan
        since_open = df["minute"] - 570
        in_or = since_open < OR_MINUTES
        df["or_high"] = h.where(in_or).groupby(sess).cummax().groupby(sess).ffill()
        df["or_low"] = l.where(in_or).groupby(sess).cummin().groupby(sess).ffill()
        df["or_complete"] = since_open + bar_min >= OR_MINUTES
        df["day_high"] = h.groupby(sess).cummax()
        df["day_low"] = l.groupby(sess).cummin()
        # time-of-day relative volume: today's cumulative volume vs the same point on prior sessions
        cum = v.groupby(sess).cumsum()
        table = pd.DataFrame({"session": sess, "minute": df["minute"], "cum": cum}).pivot_table(
            index="session", columns="minute", values="cum", aggfunc="last").sort_index()
        baseline = table.shift(1).rolling(RVOL_DAYS, min_periods=3).mean()
        base_vals = baseline.stack().rename("base")
        keys = pd.MultiIndex.from_arrays([sess.values, df["minute"].values])
        df["rvol"] = (cum.values / base_vals.reindex(keys).values)
        df.loc[~np.isfinite(df["rvol"]), "rvol"] = np.nan
        if df["rvol"].isna().all():
            notes.append("Relative volume needs at least 3 prior sessions of intraday bars.")
    else:
        df["vwap"] = np.nan
        df["pm_high"] = df["pm_low"] = np.nan
        df["or_high"] = df["or_low"] = np.nan
        df["or_complete"] = True
        df["day_high"], df["day_low"] = h, l
        df["rvol"] = v / v.shift(1).rolling(20, min_periods=5).mean()

    # ---- structure ----
    sh, sl = _swings(h, l, SWING_K)
    df["swing_high_new"], df["swing_low_new"] = sh, sl
    df["last_swing_high"], df["prev_swing_high"] = _last_two(sh)
    df["last_swing_low"], df["prev_swing_low"] = _last_two(sl)
    hh = df["last_swing_high"] > df["prev_swing_high"]
    hl = df["last_swing_low"] > df["prev_swing_low"]
    lh = df["last_swing_high"] < df["prev_swing_high"]
    ll = df["last_swing_low"] < df["prev_swing_low"]
    df["structure"] = np.select([hh & hl, lh & ll], ["uptrend", "downtrend"], default="range")
    df.loc[df["prev_swing_low"].isna() | df["prev_swing_high"].isna(), "structure"] = "unknown"

    # RSI divergence at newly confirmed swings (pivot RSI read k bars back, causal)
    rsi_at_pivot = df["rsi"].shift(SWING_K)
    lows_rsi = rsi_at_pivot.where(sl.notna())
    highs_rsi = rsi_at_pivot.where(sh.notna())
    prev_low_rsi = lows_rsi.dropna().shift(1).reindex(df.index)
    prev_high_rsi = highs_rsi.dropna().shift(1).reindex(df.index)
    df["bull_divergence"] = sl.notna() & (sl < df["prev_swing_low"]) & (lows_rsi > prev_low_rsi)
    df["bear_divergence"] = sh.notna() & (sh > df["prev_swing_high"]) & (highs_rsi < prev_high_rsi)

    # liquidity sweeps: trade through a known low/high, then close back on the other side
    # Only meaningful levels: the day's low/high so far, yesterday's low/high, the premarket low/high.
    prior_day_low = df["day_low"].groupby(sess).shift(1) if intraday else l.rolling(20, min_periods=5).min().shift(1)
    prior_day_high = df["day_high"].groupby(sess).shift(1) if intraday else h.rolling(20, min_periods=5).max().shift(1)
    ref_low = pd.concat([prior_day_low, df["pdl"], df["pm_low"]], axis=1)
    ref_high = pd.concat([prior_day_high, df["pdh"], df["pm_high"]], axis=1)
    df["bull_sweep"] = ((l.values.reshape(-1, 1) < ref_low.values) & (c.values.reshape(-1, 1) > ref_low.values)).any(axis=1) & (clv > 0.3)
    df["bear_sweep"] = ((h.values.reshape(-1, 1) > ref_high.values) & (c.values.reshape(-1, 1) < ref_high.values)).any(axis=1) & (clv < -0.3)

    # consolidation: last 12 bars fit inside 2.5 ATR
    rh, rl = h.rolling(12, min_periods=12).max(), l.rolling(12, min_periods=12).min()
    df["range_high"], df["range_low"] = rh, rl
    df["consolidating"] = (rh - rl) <= 2.5 * df["atr"]

    df["ext_from_ema9_atr"] = (c - df["ema9"]) / df["atr"]
    flags = candles.detect(df, df["atr"])
    for col in flags:
        df[f"cdl_{col}"] = flags[col]
    return FeatureFrame(df, timeframe, intraday, notes)
