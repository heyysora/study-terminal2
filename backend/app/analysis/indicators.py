"""Technical indicators. Every function is causal: row i uses only rows <= i.

Conventions match TradingView where it matters: RSI/ATR use Wilder's RMA seeded with an
SMA; EMAs use the standard 2/(n+1) smoothing (they converge after ~3x the period).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rma(s: pd.Series, n: int) -> pd.Series:
    """Wilder's moving average, seeded with the SMA of the first n values (TradingView ta.rma)."""
    vals = s.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    valid = np.where(~np.isnan(vals))[0]
    if len(valid) < n:
        return pd.Series(out, index=s.index)
    start = valid[0]
    seed_end = start + n
    if seed_end > len(vals):
        return pd.Series(out, index=s.index)
    out[seed_end - 1] = np.nanmean(vals[start:seed_end])
    a = 1.0 / n
    for i in range(seed_end, len(vals)):
        v = vals[i]
        out[i] = out[i - 1] if np.isnan(v) else out[i - 1] + a * (v - out[i - 1])
    return pd.Series(out, index=s.index)


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    gain = rma(d.clip(lower=0), n)
    loss = rma((-d).clip(lower=0), n)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).where(gain.notna())


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return pd.DataFrame({"macd": line, "macd_signal": sig, "macd_hist": line - sig})


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, smooth_k: int = 3, d: int = 3) -> pd.DataFrame:
    hh, ll = high.rolling(k, min_periods=k).max(), low.rolling(k, min_periods=k).min()
    raw = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    kk = raw.rolling(smooth_k, min_periods=smooth_k).mean()
    return pd.DataFrame({"stoch_k": kk, "stoch_d": kk.rolling(d, min_periods=d).mean()})


def roc(close: pd.Series, n: int = 10) -> pd.Series:
    return 100 * (close / close.shift(n) - 1)


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    pc = close.shift(1)
    return pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    return rma(true_range(high, low, close), n)


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = sma(close, n)
    sd = close.rolling(n, min_periods=n).std(ddof=0)
    up, lo = mid + k * sd, mid - k * sd
    return pd.DataFrame({"bb_mid": mid, "bb_upper": up, "bb_lower": lo, "bb_width": (up - lo) / mid,
                         "bb_pctb": (close - lo) / (up - lo).replace(0, np.nan)})


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def close_location(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """-1 (closed at the low: sellers in control) .. +1 (closed at the high: buyers in control)."""
    rng = (high - low).replace(0, np.nan)
    return (((close - low) - (high - close)) / rng).fillna(0)


def historical_volatility(close: pd.Series, n: int, periods_per_year: float) -> pd.Series:
    """Annualized std-dev of log returns, in percent."""
    lr = np.log(close / close.shift(1))
    return lr.rolling(n, min_periods=n).std(ddof=1) * np.sqrt(periods_per_year) * 100


def session_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, session_key: pd.Series) -> pd.Series:
    """VWAP that resets each session. NaN until the session has traded volume."""
    tp = (high + low + close) / 3
    pv = (tp * volume).groupby(session_key).cumsum()
    vv = volume.groupby(session_key).cumsum()
    return pv / vv.replace(0, np.nan)


def volume_profile(close: pd.Series, volume: pd.Series, bins: int = 40, value_area: float = 0.70) -> dict | None:
    """Point of control and value area from close-weighted volume. Approximate: uses bar closes."""
    if len(close) < 5 or volume.sum() <= 0:
        return None
    lo, hi = float(close.min()), float(close.max())
    if hi <= lo:
        return {"poc": lo, "vah": hi, "val": lo}
    edges = np.linspace(lo, hi, bins + 1)
    idx = np.clip(np.digitize(close.to_numpy(), edges) - 1, 0, bins - 1)
    vol = np.bincount(idx, weights=volume.to_numpy(dtype=float), minlength=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    poc_i = int(vol.argmax())
    total, inside = vol.sum(), vol[poc_i]
    l, r = poc_i, poc_i
    while inside < value_area * total and (l > 0 or r < bins - 1):
        left = vol[l - 1] if l > 0 else -1
        right = vol[r + 1] if r < bins - 1 else -1
        if right >= left:
            r += 1
            inside += vol[r]
        else:
            l -= 1
            inside += vol[l]
    return {"poc": round(float(centers[poc_i]), 4), "vah": round(float(edges[r + 1]), 4), "val": round(float(edges[l]), 4)}
