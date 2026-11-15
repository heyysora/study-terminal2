"""A structured read of the last CLOSED candle, for you and for any AI you want to ask.

Idea adapted from "AI Agent Lens" (github.com/roan-maverick/tradingview-indicator-for-ai-agents, MIT): turn a chart into
numbers an AI can reason about instead of colours. Differences here: it is built from Study Terminal's own free data (no paid
TradingView plan, no webhook, no public tunnel), it only ever uses closed candles (nothing repaints), it is labelled with how
fresh the data is, and the 0-100 "agreement" numbers are counts of checks that point the same way, NOT a chance of winning:
they have not been tested as an edge.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from .candles import detect

SCHEMA = "study-terminal-packet/v1"


def _f(x, nd: int = 4):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, nd)


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    """Wilder's ADX with +DI / -DI (trend strength, not direction)."""
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    up, down = h.diff(), -l.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    a = 1 / n
    atr = tr.ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=a, adjust=False).mean() / atr
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=a, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"adx": dx.ewm(alpha=a, adjust=False).mean(), "plus_di": pdi, "minus_di": mdi}, index=df.index)


def _candle(df: pd.DataFrame, flags: pd.DataFrame, i: int) -> dict:
    r = df.iloc[i]
    o, h, l, c = (float(r[k]) for k in ("open", "high", "low", "close"))
    rng = max(h - l, 1e-12)
    prev_c = float(df["close"].iloc[i - 1]) if i > 0 else None
    pats = [k for k in flags.columns if bool(flags.iloc[i].get(k, False))]
    return {"time": df.index[i].isoformat() if hasattr(df.index[i], "isoformat") else str(df.index[i]),
            "open": _f(o), "high": _f(h), "low": _f(l), "close": _f(c),
            "direction": "up" if c > o else "down" if c < o else "flat",
            "body_pct_of_range": _f(100 * abs(c - o) / rng, 1), "upper_wick_pct": _f(100 * (h - max(o, c)) / rng, 1),
            "lower_wick_pct": _f(100 * (min(o, c) - l) / rng, 1),
            "range_vs_atr": _f(rng / float(r["atr"]), 2) if r.get("atr") else None,
            "close_position": _f((c - l) / rng, 2),          # 0 = closed at the low, 1 = at the high
            "gap_pct": _f(100 * (o - prev_c) / prev_c, 3) if prev_c else None, "patterns": pats}


def _words(cd: dict) -> str:
    if cd["body_pct_of_range"] is None:
        return ""
    size = "big" if (cd["range_vs_atr"] or 0) >= 1.5 else "small" if (cd["range_vs_atr"] or 1) < 0.6 else "normal-sized"
    where = ("near its high" if cd["close_position"] >= 0.75 else "near its low" if cd["close_position"] <= 0.25
             else "in the middle of its range")
    kind = {"up": "green (up)", "down": "red (down)", "flat": "flat"}[cd["direction"]]
    return f"A {size} {kind} candle that closed {where}."


def build(symbol: str, timeframe: str, ff, htf_ff=None, label: dict | None = None, n_recent: int = 5) -> dict:
    """ff: FeatureFrame of closed bars. htf_ff: optional higher-timeframe frame for the bias."""
    df = ff.df.copy()
    if len(df) < 30:
        raise ValueError("Not enough candles yet.")
    df = df.join(adx(df))
    flags = detect(df, df["atr"])
    i = len(df) - 1
    r = df.iloc[i]
    c = float(r["close"])
    ema21, ema50, ema200 = (r.get(k) for k in ("ema21", "ema50", "ema200"))
    stack = ("up" if ema21 > ema50 > ema200 else "down" if ema21 < ema50 < ema200 else "mixed") if all(
        v == v and v is not None for v in (ema21, ema50, ema200)) else None
    e200 = df["ema200"].dropna()
    slope = _f(100 * (e200.iloc[-1] / e200.iloc[-11] - 1), 3) if len(e200) > 11 else None
    atrp = df["atr_pct"].dropna().tail(200)
    atr_pctile = _f(100 * (atrp < atrp.iloc[-1]).mean(), 0) if len(atrp) >= 20 else None
    hi_vol = bool(r.get("atr_pct") and r.get("atr_pct_med") and r["atr_pct"] > 1.8 * r["atr_pct_med"])
    structure = r.get("structure")
    adx_v = _f(r["adx"], 1)
    if hi_vol:
        regime = "HIGH_VOLATILITY"
    elif stack == "up" and (structure == "uptrend" or (adx_v or 0) >= 20):
        regime = "TREND_UP"
    elif stack == "down" and (structure == "downtrend" or (adx_v or 0) >= 20):
        regime = "TREND_DOWN"
    else:
        regime = "RANGE"
    htf = None
    if htf_ff is not None and len(htf_ff.df) > 0:
        hr = htf_ff.df.iloc[-1]
        hs = hr.get("structure")
        hstack = ("up" if hr.get("ema21", 0) > hr.get("ema50", 0) else "down") if hr.get("ema50") == hr.get("ema50") else None
        htf = {"timeframe": htf_ff.timeframe.value, "structure": hs, "ema21_vs_50": hstack,
               "bias": "up" if hs == "uptrend" or (hs != "downtrend" and hstack == "up") else
                       "down" if hs == "downtrend" or (hs != "uptrend" and hstack == "down") else "none"}
    rsi, mh = _f(r.get("rsi"), 1), _f(r.get("macd_hist"), 4)
    rvol = _f(r.get("rvol"), 2)
    pdi, mdi = _f(r["plus_di"], 1), _f(r["minus_di"], 1)

    cd = _candle(df, flags, i)

    def score(side: str) -> dict:
        up = side == "long"
        checks = {
            "trend": stack == ("up" if up else "down"),
            "momentum": (rsi is not None and mh is not None) and ((rsi > 50 and mh > 0) if up else (rsi < 50 and mh < 0)),
            "strength": (adx_v or 0) >= 20 and pdi is not None and mdi is not None and ((pdi > mdi) if up else (mdi > pdi)),
            "volume": (rvol or 0) >= 1.2 and cd["direction"] == ("up" if up else "down"),   # busy volume behind this candle's move
            "higher_timeframe": bool(htf and htf["bias"] == ("up" if up else "down")),
        }
        return {"score": 20 * sum(checks.values()), "checks": checks}

    atr = float(r["atr"]) if r.get("atr") else None
    risk_map = None
    if atr:
        risk_map = {"entry": _f(c), "long": {"stop": _f(c - 1.5 * atr), "target_1_5r": _f(c + 2.25 * atr), "target_3r": _f(c + 4.5 * atr)},
                    "short": {"stop": _f(c + 1.5 * atr), "target_1_5r": _f(c - 2.25 * atr), "target_3r": _f(c - 4.5 * atr)},
                    "rule": "stop 1.5 x ATR from the close; targets at 1.5R and 3R. A reference, not a setup."}
    sh, sl = r.get("prev_swing_high"), r.get("prev_swing_low")
    return {
        "schema": SCHEMA, "symbol": symbol, "timeframe": timeframe, "closed_candle_only": True,
        "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {"status": (label or {}).get("status"), "note": (label or {}).get("reason"), "source": ff.source or ff.provider,
                 "served_from_cache": ff.served_from_cache},
        "candle": cd, "candle_in_words": _words(cd),
        "recent_candles": [_candle(df, flags, j) for j in range(max(0, i - n_recent), i)][::-1],
        "regime": regime,
        "trend": {"ema21_50_200": stack, "ema200_slope_pct_10_bars": slope, "structure": structure, "higher_timeframe": htf},
        "momentum": {"rsi": rsi, "macd_hist": mh, "adx": adx_v, "plus_di": pdi, "minus_di": mdi},
        "volume_volatility": {"relative_volume": rvol, "atr": _f(atr), "atr_pct": _f(r.get("atr_pct"), 3), "atr_percentile_200": atr_pctile},
        "structure": {"last_swing_high": _f(sh), "last_swing_low": _f(sl),
                      "broke_above_swing_high": bool(sh == sh and sh is not None and c > sh),
                      "broke_below_swing_low": bool(sl == sl and sl is not None and c < sl)},
        "levels": {"prev_day_high": _f(r.get("pdh")), "prev_day_low": _f(r.get("pdl")), "prev_close": _f(r.get("pdc")),
                   "vwap": _f(r.get("vwap"))},
        "agreement": {"long": score("long"), "short": score("short"),
                      "meaning": "How many of five checks point each way (20 points each; volume counts for the side the candle moved). Not a chance of winning; not tested as an edge."},
        "risk_map": risk_map,
        "for_an_ai": ("Educational practice only: Study Terminal can't place orders. Reply with decision (long/short/wait), confidence, "
                      "entry, stop, target_1, target_2, invalidation and why_this_could_fail. Say 'wait' when the read is unclear. "
                      "Treat the data status above as part of the decision: delayed or cached data means no trade."),
    }
