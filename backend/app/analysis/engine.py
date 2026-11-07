"""Turns a FeatureFrame into a structured, explained snapshot. Indicators are judged together:
the output is a list of factors (each with direction, weight and plain-English reason), not a
verdict from any single indicator."""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from . import candles
from .features import SWING_K, FeatureFrame
from .indicators import volume_profile


def _f(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, 4)


def key_levels(df: pd.DataFrame, i: int, lookback: int = 300) -> list[dict]:
    """Support/resistance known at row i: clustered confirmed swing points plus named session levels."""
    row = df.iloc[i]
    atr = row.get("atr")
    tol = float(atr) * 0.5 if atr == atr and atr else float(row["close"]) * 0.003
    start = max(0, i - lookback)
    window = df.iloc[start:i + 1]
    pts = [(float(p), "swing_high") for p in window["swing_high_new"].dropna()] + \
          [(float(p), "swing_low") for p in window["swing_low_new"].dropna()]
    pts.sort()
    clusters: list[list[tuple[float, str]]] = []
    for p in pts:
        if clusters and p[0] - clusters[-1][-1][0] <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = [{"price": round(sum(x for x, _ in cl) / len(cl), 4), "kind": "structure", "touches": len(cl),
               "label": f"{'swing' if len(cl) == 1 else f'{len(cl)}-touch'} level"} for cl in clusters]
    named = {"pdh": "Previous day high", "pdl": "Previous day low", "pdc": "Previous close",
             "pm_high": "Premarket high", "pm_low": "Premarket low", "or_high": "Opening range high",
             "or_low": "Opening range low", "vwap": "VWAP"}
    for k, label in named.items():
        v = _f(row.get(k))
        if v is not None and (k not in ("or_high", "or_low") or bool(row.get("or_complete"))):
            levels.append({"price": v, "kind": k, "touches": None, "label": label})
    price = float(row["close"])
    for lv in levels:
        lv["side"] = "above" if lv["price"] > price else "below"
        lv["distance_pct"] = round(100 * (lv["price"] / price - 1), 3)
    return sorted(levels, key=lambda x: x["price"])


def factors(row: pd.Series, prev: pd.Series | None) -> list[dict]:
    """Bullish/bearish evidence with weights. Weights are judgment, not probabilities."""
    out: list[dict] = []

    def add(direction: str, weight: int, name: str, why: str):
        out.append({"direction": direction, "weight": weight, "factor": name, "why": why})

    c = row["close"]
    e9, e21, e50, e200 = (row.get(f"ema{n}") for n in (9, 21, 50, 200))
    if all(x == x and x is not None for x in (e9, e21, e50)):
        if e9 > e21 > e50:
            add("bullish", 2, "EMA stack up", "Fast averages above slow ones (9 > 21 > 50): recent prices keep beating older prices.")
        elif e9 < e21 < e50:
            add("bearish", 2, "EMA stack down", "Fast averages below slow ones (9 < 21 < 50): recent prices keep losing to older prices.")
    if e200 == e200 and e200 is not None:
        add("bullish" if c > e200 else "bearish", 1, "vs 200 EMA",
            f"Price is {'above' if c > e200 else 'below'} the 200 EMA, the long-term trend line on this timeframe.")
    vw = row.get("vwap")
    if vw == vw and vw is not None:
        above = c > vw
        add("bullish" if above else "bearish", 2, "VWAP side",
            f"Price is {'above' if above else 'below'} VWAP - the average price paid today, weighted by volume. "
            f"{'Today buyers are, on average, in profit.' if above else 'Today buyers are, on average, losing.'}")
    st = row.get("structure")
    if st == "uptrend":
        add("bullish", 2, "Higher highs & higher lows", "Each swing high and swing low is above the last one - the definition of an uptrend.")
    elif st == "downtrend":
        add("bearish", 2, "Lower highs & lower lows", "Each swing high and swing low is below the last one - the definition of a downtrend.")
    r = row.get("rsi")
    if r == r and r is not None:
        if r >= 70:
            add("bearish", 1, "RSI overbought", f"RSI {r:.0f}: the recent move up has been unusually strong; chasing here is risky (not a sell signal by itself).")
        elif r <= 30:
            add("bullish", 1, "RSI oversold", f"RSI {r:.0f}: the recent move down has been unusually strong (not a buy signal by itself).")
        elif r >= 55:
            add("bullish", 1, "RSI momentum", f"RSI {r:.0f}: momentum leans up.")
        elif r <= 45:
            add("bearish", 1, "RSI momentum", f"RSI {r:.0f}: momentum leans down.")
    mh = row.get("macd_hist")
    if mh == mh and mh is not None and prev is not None:
        pmh = prev.get("macd_hist")
        if pmh == pmh and pmh is not None:
            if mh > 0 and mh > pmh:
                add("bullish", 1, "MACD rising", "MACD histogram is positive and growing: upward momentum is accelerating.")
            elif mh < 0 and mh < pmh:
                add("bearish", 1, "MACD falling", "MACD histogram is negative and falling: downward momentum is accelerating.")
    rv = row.get("rvol")
    if rv == rv and rv is not None:
        if rv >= 1.5:
            add("neutral", 0, "High relative volume", f"Volume is {rv:.1f}x normal for this time of day: moves are more likely to be real.")
        elif rv < 0.7:
            add("neutral", 0, "Low relative volume", f"Volume is only {rv:.1f}x normal: moves are less trustworthy.")
    pr = row.get("pressure")
    if pr == pr and pr is not None and abs(pr) >= 0.3:
        add("bullish" if pr > 0 else "bearish", 1, "Close location",
            f"Recent candles closed near their {'highs' if pr > 0 else 'lows'} on volume: {'buyers' if pr > 0 else 'sellers'} finishing bars in control (an estimate from candle shape).")
    if bool(row.get("bull_divergence")):
        add("bullish", 1, "Bullish RSI divergence", "Price made a lower low but RSI made a higher low: selling momentum is fading.")
    if bool(row.get("bear_divergence")):
        add("bearish", 1, "Bearish RSI divergence", "Price made a higher high but RSI made a lower high: buying momentum is fading.")
    if bool(row.get("bull_sweep")):
        add("bullish", 1, "Liquidity sweep (low)", "Price dipped under a known low and closed back above it: stops were run, then buyers stepped in.")
    if bool(row.get("bear_sweep")):
        add("bearish", 1, "Liquidity sweep (high)", "Price poked above a known high and closed back below it: breakout buyers got trapped.")
    ext = row.get("ext_from_ema9_atr")
    if ext == ext and ext is not None and abs(ext) >= 2:
        add("neutral", 0, "Extended", f"Price is {abs(ext):.1f} ATRs {'above' if ext > 0 else 'below'} the 9 EMA - stretched; entries here often get a pullback first.")
    return out


def bias(fs: list[dict]) -> dict:
    b = sum(f["weight"] for f in fs if f["direction"] == "bullish")
    s = sum(f["weight"] for f in fs if f["direction"] == "bearish")
    total = b + s
    score = 0 if total == 0 else round(100 * (b - s) / total)
    label = "bullish" if score >= 40 else "bearish" if score <= -40 else "mixed"
    return {"score": score, "label": label, "bullish_weight": b, "bearish_weight": s,
            "note": "Weight of evidence from the factors listed - a summary, not a probability."}


def snapshot(ff: FeatureFrame, i: int = -1) -> dict[str, Any]:
    df = ff.df
    if df.empty:
        return {"available": False, "reason": "no bars", "notes": ff.notes}
    i = i if i >= 0 else len(df) + i
    row, prev = df.iloc[i], (df.iloc[i - 1] if i > 0 else None)
    fs = factors(row, prev)
    session_rows = df[df["session"] == row["session"]].iloc[: (i - df.index.get_loc(df[df["session"] == row["session"]].index[0]) + 1)] if ff.intraday else df.iloc[max(0, i - 60): i + 1]
    flags = df[[c for c in df.columns if c.startswith("cdl_")]].rename(columns=lambda c: c[4:])
    recent_patterns = []
    for j in range(max(0, i - 2), i + 1):
        for p in candles.at_row(flags, j):
            recent_patterns.append({**p, "ts": df.index[j].isoformat(), "bars_ago": i - j})
    g = lambda k: _f(row.get(k))  # noqa: E731
    return {
        "available": True,
        "timeframe": ff.timeframe.value,
        "ts": df.index[i].isoformat(),
        "price": g("close"),
        "bars_used": i + 1,
        "notes": ff.notes,
        "moving_averages": {k: g(k) for k in ("ema9", "ema21", "ema50", "ema200", "sma20", "sma50", "sma200")},
        "momentum": {"rsi": g("rsi"), "macd": g("macd"), "macd_signal": g("macd_signal"), "macd_hist": g("macd_hist"),
                     "stoch_k": g("stoch_k"), "stoch_d": g("stoch_d"), "roc": g("roc")},
        "volatility": {"atr": g("atr"), "atr_pct": g("atr_pct"), "bb_upper": g("bb_upper"), "bb_mid": g("bb_mid"),
                       "bb_lower": g("bb_lower"), "bb_width": g("bb_width"), "hv": g("hv"),
                       "day_range_atr": _f((row["day_high"] - row["day_low"]) / row["atr"]) if row.get("atr") else None},
        "volume": {"volume": g("volume"), "vol_ratio": g("vol_ratio"), "rvol": g("rvol"), "vol_spike": bool(row.get("vol_spike")),
                   "obv_slope": g("obv_slope"), "pressure": g("pressure"),
                   "profile": volume_profile(session_rows["close"], session_rows["volume"]) if len(session_rows) >= 5 else None},
        "session": {"vwap": g("vwap"), "pdh": g("pdh"), "pdl": g("pdl"), "pdc": g("pdc"), "pm_high": g("pm_high"),
                    "pm_low": g("pm_low"), "or_high": g("or_high") if bool(row.get("or_complete")) else None,
                    "or_low": g("or_low") if bool(row.get("or_complete")) else None, "day_high": g("day_high"), "day_low": g("day_low")},
        "structure": {"state": row.get("structure"), "last_swing_high": g("last_swing_high"), "prev_swing_high": g("prev_swing_high"),
                      "last_swing_low": g("last_swing_low"), "prev_swing_low": g("prev_swing_low"),
                      "consolidating": bool(row.get("consolidating")), "range_high": g("range_high"), "range_low": g("range_low"),
                      "bull_sweep": bool(row.get("bull_sweep")), "bear_sweep": bool(row.get("bear_sweep")),
                      "bull_divergence": bool(row.get("bull_divergence")), "bear_divergence": bool(row.get("bear_divergence")),
                      "swing_confirmation_lag_bars": SWING_K},
        "levels": key_levels(df, i),
        "candles": recent_patterns,
        "factors": fs,
        "bias": bias(fs),
    }


def mtf_summary(snaps: dict[str, dict]) -> dict:
    """Do the timeframes agree? Agreement across timeframes is a quality factor, not a signal."""
    rows = []
    for tf, s in snaps.items():
        if not s.get("available"):
            continue
        rows.append({"timeframe": tf, "bias": s["bias"]["label"], "score": s["bias"]["score"], "structure": s["structure"]["state"]})
    labels = {r["bias"] for r in rows}
    aligned = len(rows) >= 2 and len(labels) == 1 and labels != {"mixed"}
    return {"timeframes": rows, "aligned": aligned, "direction": rows[0]["bias"] if aligned else "mixed",
            "note": "All selected timeframes point the same way." if aligned else "Timeframes disagree or are mixed - lower conviction."}


def series_for_chart(ff: FeatureFrame, tail: int = 500) -> dict:
    """Indicator series for chart overlays."""
    df = ff.df.tail(tail)
    out = {}
    for col in ("ema9", "ema21", "ema50", "ema200", "vwap", "bb_upper", "bb_lower"):
        if col in df and df[col].notna().any():
            s = df[col].dropna()
            out[col] = [{"time": int(t.timestamp()), "value": round(float(v), 4)} for t, v in s.items()]
    out["rsi"] = [{"time": int(t.timestamp()), "value": round(float(v), 2)} for t, v in df["rsi"].dropna().items()]
    return out


def to_jsonable(x):
    if isinstance(x, dict):
        return {k: to_jsonable(v) for k, v in x.items()}
    if isinstance(x, list):
        return [to_jsonable(v) for v in x]
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return _f(x)
    if isinstance(x, tuple):
        return [to_jsonable(v) for v in x]
    return x
