"""Candlestick patterns. Each column is a boolean series; row i looks at bars i and i-1 only."""
from __future__ import annotations

import pandas as pd

PATTERNS = {
    "bullish_engulfing": ("bullish", "Bullish engulfing: a green candle whose body swallows the prior red body - buyers took over."),
    "bearish_engulfing": ("bearish", "Bearish engulfing: a red candle whose body swallows the prior green body - sellers took over."),
    "doji": ("neutral", "Doji: open and close almost equal - indecision; meaningful only at a key level."),
    "hammer": ("bullish", "Hammer: long lower wick after a dip - sellers pushed down, buyers pushed it back up."),
    "shooting_star": ("bearish", "Shooting star: long upper wick after a rise - buyers pushed up, sellers slammed it back."),
    "bullish_pin_bar": ("bullish", "Bullish pin bar: rejection of lower prices (long lower wick, close near the high)."),
    "bearish_pin_bar": ("bearish", "Bearish pin bar: rejection of higher prices (long upper wick, close near the low)."),
    "inside_bar": ("neutral", "Inside bar: range inside the previous candle - the market is pausing/coiling."),
    "bullish_breakout_candle": ("bullish", "Bullish breakout candle: big green body closing near its high on a wide range."),
    "bearish_breakout_candle": ("bearish", "Bearish breakout candle: big red body closing near its low on a wide range."),
}


def detect(df: pd.DataFrame, atr: pd.Series) -> pd.DataFrame:
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    po, pc, ph, pl = o.shift(1), c.shift(1), h.shift(1), l.shift(1)
    body = (c - o).abs()
    rng = (h - l).where(h > l)
    upper = h - pd.concat([o, c], axis=1).max(axis=1)
    lower = pd.concat([o, c], axis=1).min(axis=1) - l
    green, red = c > o, c < o
    prior_drop = c.shift(1) < c.shift(4)
    prior_rise = c.shift(1) > c.shift(4)
    out = pd.DataFrame(index=df.index)
    out["bullish_engulfing"] = green & (pc < po) & (c >= po) & (o <= pc) & (body > (po - pc).abs())
    out["bearish_engulfing"] = red & (pc > po) & (c <= po) & (o >= pc) & (body > (po - pc).abs())
    out["doji"] = (body <= 0.1 * rng)
    out["hammer"] = (lower >= 2 * body) & (upper <= 0.3 * rng) & prior_drop & (body > 0.05 * rng)
    out["shooting_star"] = (upper >= 2 * body) & (lower <= 0.3 * rng) & prior_rise & (body > 0.05 * rng)
    out["bullish_pin_bar"] = (lower >= 0.6 * rng) & (c >= l + 0.66 * rng)
    out["bearish_pin_bar"] = (upper >= 0.6 * rng) & (c <= l + 0.34 * rng)
    out["inside_bar"] = (h <= ph) & (l >= pl)
    wide = rng >= 1.5 * atr
    out["bullish_breakout_candle"] = green & wide & (body >= 0.7 * rng)
    out["bearish_breakout_candle"] = red & wide & (body >= 0.7 * rng)
    return out.fillna(False).astype(bool)


def at_row(flags: pd.DataFrame, i: int) -> list[dict]:
    row = flags.iloc[i]
    return [{"name": k, "direction": PATTERNS[k][0], "meaning": PATTERNS[k][1]} for k in PATTERNS if bool(row.get(k, False))]
