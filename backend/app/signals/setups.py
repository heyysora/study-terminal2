"""Setup detectors. Vectorized over the causal feature frame: a setup on row i only uses rows <= i.
The live signal engine and the backtester call the same `detect` function.

Each detected row yields a trade idea that is NOT yet a trade:
  trigger       price that must trade to enter (a stop order: confirmation by price action)
  stop          where the idea is wrong (protective stop)
  invalidation  level that kills the setup before entry
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import warnings

import numpy as np
import pandas as pd

TICK = 0.01


@dataclass
class SetupParams:
    rvol_min: float = 1.2           # relative volume needed for momentum setups
    vol_ratio_min: float = 1.3      # signal-bar volume vs its 20-bar average
    stop_buffer_atr: float = 0.10   # stop goes this many ATRs beyond the structure level
    target_r: float = 2.0           # main target in multiples of risk (R)
    entry_window_atr: float = 0.25  # above the trigger, entries are allowed up to this many ATRs (anti-chase)
    expiry_bars: int = 6            # an untriggered setup expires after this many bars
    first_minute: int = 585         # no intraday signals before 09:45 ET (opening noise)
    last_minute: int = 930          # ... or after 15:30 ET
    orb_last_minute: int = 690      # opening-range breakouts only until 11:30 ET

    def to_dict(self) -> dict:
        return asdict(self)


SETUPS = {
    "vwap_reclaim": ("long", "VWAP reclaim"),
    "vwap_rejection": ("short", "VWAP rejection"),
    "orb_long": ("long", "Opening range breakout"),
    "orb_short": ("short", "Opening range breakdown"),
    "level_breakout": ("long", "Resistance breakout"),
    "level_breakdown": ("short", "Support breakdown"),
    "trend_pullback_long": ("long", "Trend pullback (long)"),
    "trend_pullback_short": ("short", "Trend pullback (short)"),
    "failed_breakdown": ("long", "Failed breakdown (liquidity sweep reclaim)"),
    "failed_breakout": ("short", "Failed breakout (liquidity sweep rejection)"),
}


def detect(df: pd.DataFrame, p: SetupParams, intraday: bool = True) -> pd.DataFrame:
    """Rows = bars with at least one setup. Columns: setup, direction, trigger, stop, invalidation, level."""
    if df.empty or len(df) < 30:
        return pd.DataFrame(columns=["setup", "direction", "trigger", "stop", "invalidation", "level"])
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    atr = df["atr"]
    buf = p.stop_buffer_atr * atr
    pc = c.shift(1)
    green, red = c > o, c < o
    rng = (h - l).replace(0, np.nan)
    body_frac = (c - o).abs() / rng
    vol_ok = df["vol_ratio"] >= p.vol_ratio_min
    rvol_ok = df["rvol"].fillna(0) >= p.rvol_min if intraday else df["rvol"].fillna(0) >= 1.0
    minute = df["minute"]
    in_time = (minute >= p.first_minute) & (minute <= p.last_minute) if intraday else pd.Series(True, index=df.index)
    ok = in_time & atr.notna()

    out = []

    def emit(name, cond, trigger, stop, inval, level=None):
        cond = cond.fillna(False) & ok
        if not cond.any():
            return
        idx = cond[cond].index
        out.append(pd.DataFrame({"setup": name, "direction": SETUPS[name][0], "trigger": trigger.loc[idx],
                                 "stop": stop.loc[idx], "invalidation": inval.loc[idx],
                                 "level": (level.loc[idx] if level is not None else np.nan)}, index=idx))

    if intraday:
        vw, pvw = df["vwap"], df["vwap"].shift(1)
        emit("vwap_reclaim", (pc < pvw) & (c > vw) & green & (df["ema9"] > df["ema9"].shift(1)) & rvol_ok,
             h + TICK, np.minimum(l, vw) - buf, vw - buf, vw)
        emit("vwap_rejection", (pc > pvw) & (c < vw) & red & (df["ema9"] < df["ema9"].shift(1)) & rvol_ok,
             l - TICK, np.maximum(h, vw) + buf, vw + buf, vw)

        orh, orl = df["or_high"], df["or_low"]
        orng = orh - orl
        early = minute <= p.orb_last_minute
        or_stop_long = np.where(orng > 1.5 * atr, (orh + orl) / 2, orl) - buf
        or_stop_short = np.where(orng > 1.5 * atr, (orh + orl) / 2, orh) + buf
        emit("orb_long", df["or_complete"] & early & (pc <= orh) & (c > orh) & green & vol_ok,
             h + TICK, pd.Series(or_stop_long, index=df.index), orh - buf, orh)
        emit("orb_short", df["or_complete"] & early & (pc >= orl) & (c < orl) & red & vol_ok,
             l - TICK, pd.Series(or_stop_short, index=df.index), orl + buf, orl)

    # breakouts through the nearest overhead level (prev day high, premarket high, last swing high)
    res = pd.concat([df["pdh"], df["pm_high"], df["last_swing_high"].shift(1)], axis=1)
    sup = pd.concat([df["pdl"], df["pm_low"], df["last_swing_low"].shift(1)], axis=1)
    pcv, cv = pc.to_numpy().reshape(-1, 1), c.to_numpy().reshape(-1, 1)
    crossed_up = np.where((pcv <= res.to_numpy()) & (cv > res.to_numpy()), res.to_numpy(), np.nan)
    crossed_dn = np.where((pcv >= sup.to_numpy()) & (cv < sup.to_numpy()), sup.to_numpy(), np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # rows with no level crossed are all-NaN
        lvl_up = pd.Series(np.nanmax(crossed_up, axis=1), index=df.index)
        lvl_dn = pd.Series(np.nanmin(crossed_dn, axis=1), index=df.index)
    strong_up = green & (body_frac >= 0.5) & vol_ok
    strong_dn = red & (body_frac >= 0.5) & vol_ok
    emit("level_breakout", lvl_up.notna() & strong_up, h + TICK, np.minimum(l, lvl_up - buf), lvl_up - buf, lvl_up)
    emit("level_breakdown", lvl_dn.notna() & strong_dn, l - TICK, np.maximum(h, lvl_dn + buf), lvl_dn + buf, lvl_dn)

    e9, e21, e50 = df["ema9"], df["ema21"], df["ema50"]
    up_stack, dn_stack = (e9 > e21) & (e21 > e50), (e9 < e21) & (e21 < e50)
    bull_candle = green & ((df["clv"] > 0.3) | df["cdl_hammer"] | df["cdl_bullish_engulfing"] | df["cdl_bullish_pin_bar"])
    bear_candle = red & ((df["clv"] < -0.3) | df["cdl_shooting_star"] | df["cdl_bearish_engulfing"] | df["cdl_bearish_pin_bar"])
    emit("trend_pullback_long", up_stack & (df["structure"] == "uptrend") & (l <= e21 + 0.1 * atr) & (c > e21) & bull_candle,
         h + TICK, l - buf, e50, e21)
    emit("trend_pullback_short", dn_stack & (df["structure"] == "downtrend") & (h >= e21 - 0.1 * atr) & (c < e21) & bear_candle,
         l - TICK, h + buf, e50, e21)

    swept_vol = df["vol_ratio"] >= 1.0
    emit("failed_breakdown", df["bull_sweep"] & green & swept_vol, h + TICK, l - buf, l - TICK)
    emit("failed_breakout", df["bear_sweep"] & red & swept_vol, l - TICK, h + buf, h + TICK)

    if not out:
        return pd.DataFrame(columns=["setup", "direction", "trigger", "stop", "invalidation", "level"])
    res_df = pd.concat(out).sort_index(kind="stable")
    # sanity: stop must be on the correct side of the trigger with real risk
    risk = np.where(res_df["direction"] == "long", res_df["trigger"] - res_df["stop"], res_df["stop"] - res_df["trigger"])
    return res_df[risk > 0.01]
