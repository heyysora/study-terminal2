"""Futures levels and structure, computed bar by bar so that every column at row i only uses bars 0..i.

The same frame feeds the live signal (its last closed row) and the backtest (every row), so the two can't
drift apart. Levels follow futures conventions: the trade date starts at the Globex open the evening
before, "previous day" means the previous trade date's RTH, and overnight means the current trade date
before RTH.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .contracts import CT, ProductSpec, round_to_tick
from .sessions import FuturesClock
from .contracts import fmt_num


@dataclass
class LevelParams:
    or_minutes: int = 15           # opening range
    ib_minutes: int = 60           # initial balance
    premarket_minutes: int = 60    # the hour before RTH
    swing_n: int = 2               # fractal pivot: n bars each side
    atr_n: int = 14
    va_pct: float = 0.70           # value area
    max_gap_minutes: int = 20      # inside a session, a hole longer than this marks the data incomplete


def bars_to_frame(bars: list, clock: FuturesClock) -> pd.DataFrame:
    """bars: objects/dicts with ts (UTC), open, high, low, close, volume. Adds trade date and session flags;
    drops bars outside any session (maintenance break, holiday prints)."""
    rows = []
    for b in bars:
        d = b if isinstance(b, dict) else {k: getattr(b, k) for k in ("ts", "open", "high", "low", "close", "volume")}
        rows.append((pd.Timestamp(d["ts"]), float(d["open"]), float(d["high"]), float(d["low"]), float(d["close"]), float(d["volume"] or 0)))
    df = pd.DataFrame(rows, columns=["ts", "o", "h", "l", "c", "v"])
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    tds, rth, mins = [], [], []
    cache: dict = {}
    for t in df["ts"]:
        py = t.to_pydatetime()
        w = clock.window_at(py)
        if w is None:
            tds.append(None)
            rth.append(False)
            mins.append(np.nan)
            continue
        cache[w.trade_date] = w
        tds.append(w.trade_date)
        is_rth = bool(w.rth_start and w.rth_start <= py.astimezone(CT) < w.rth_end)
        rth.append(is_rth)
        mins.append((py - w.rth_start).total_seconds() / 60 if w.rth_start else np.nan)
    df["td"], df["rth"], df["min_from_rth"] = tds, rth, mins
    df = df[df["td"].notna()].reset_index(drop=True)
    df.attrs["windows"] = cache
    return df


def _atr(df: pd.DataFrame, n: int) -> pd.Series:
    pc = df["c"].shift(1)
    tr = pd.concat([df["h"] - df["l"], (df["h"] - pc).abs(), (df["l"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def build(df: pd.DataFrame, spec: ProductSpec, clock: FuturesClock, p: LevelParams | None = None, bar_minutes: int = 5) -> pd.DataFrame:
    p = p or LevelParams()
    if df.empty:
        return df
    df = df.copy()
    df["atr"] = _atr(df, p.atr_n)
    df["vol_avg20"] = df["v"].rolling(20, min_periods=5).mean().shift(1)
    tp = (df["h"] + df["l"] + df["c"]) / 3
    # session VWAP (resets at the Globex open of each trade date) and RTH VWAP (resets at the RTH open)
    g = df.groupby("td", sort=False)
    pv, vv, pv2 = (tp * df["v"]), df["v"], (tp * tp * df["v"])
    cv = g["v"].cumsum().replace(0, np.nan)
    df["vwap"] = (pv.groupby(df["td"]).cumsum()) / cv
    var = (pv2.groupby(df["td"]).cumsum()) / cv - df["vwap"] ** 2
    df["vwap_sd"] = np.sqrt(var.clip(lower=0))
    rth_key = df["td"].astype(str) + np.where(df["rth"], "R", "N")
    rv = vv.where(df["rth"], 0).groupby(rth_key).cumsum().replace(0, np.nan)
    df["rth_vwap"] = (pv.where(df["rth"], 0).groupby(rth_key).cumsum() / rv).where(df["rth"])

    # per-trade-date aggregates (known only after the date ends) -> shifted onto the next date
    dates = list(dict.fromkeys(df["td"]))
    rth_df = df[df["rth"]]
    agg_rth = rth_df.groupby("td").agg(h=("h", "max"), l=("l", "min"), c=("c", "last"))
    agg_all = df.groupby("td").agg(h=("h", "max"), l=("l", "min"))
    prev = {d: dates[i - 1] if i else None for i, d in enumerate(dates)}
    for col, src, k in (("pdh", agg_rth, "h"), ("pdl", agg_rth, "l"), ("pdc", agg_rth, "c"), ("pgh", agg_all, "h"), ("pgl", agg_all, "l")):
        m = {d: (src[k].get(prev[d]) if prev[d] is not None else np.nan) for d in dates}
        df[col] = df["td"].map(m).astype(float)
    # overnight (before RTH of the current trade date): running while it forms, frozen once RTH starts
    on_mask = ~df["rth"] & (df["min_from_rth"] < 0)
    onh = df["h"].where(on_mask).groupby(df["td"]).cummax()
    onl = df["l"].where(on_mask).groupby(df["td"]).cummin()
    df["onh"] = onh.groupby(df["td"]).ffill()
    df["onl"] = onl.groupby(df["td"]).ffill()
    pm_mask = on_mask & (df["min_from_rth"] >= -p.premarket_minutes)
    df["pmh"] = df["h"].where(pm_mask).groupby(df["td"]).cummax().groupby(df["td"]).ffill()
    df["pml"] = df["l"].where(pm_mask).groupby(df["td"]).cummin().groupby(df["td"]).ffill()
    # opening range and initial balance: NaN until complete (a level that is still forming is not a level yet)
    for name, mins in (("or", p.or_minutes), ("ib", p.ib_minutes)):
        mask = df["rth"] & (df["min_from_rth"] >= 0) & (df["min_from_rth"] < mins)
        hi = df["h"].where(mask).groupby(df["td"]).transform("max")
        lo = df["l"].where(mask).groupby(df["td"]).transform("min")
        known = df["min_from_rth"] + bar_minutes >= mins    # at the close of the bar ending at the cutoff, the range is final
        df[f"{name}_h"] = hi.where(known)
        df[f"{name}_l"] = lo.where(known)
    up = (df["c"] > df["or_h"]).astype(int).groupby(df["td"]).cummax()
    dn = (df["c"] < df["or_l"]).astype(int).groupby(df["td"]).cummax()
    df["or_broke_up"] = up.groupby(df["td"]).shift(1).fillna(0).astype(bool)   # broke out on an EARLIER bar today
    df["or_broke_dn"] = dn.groupby(df["td"]).shift(1).fillna(0).astype(bool)
    # swings: a pivot at j is only known at j + n
    n = p.swing_n
    h, l_ = df["h"].values, df["l"].values
    piv_h = np.full(len(df), np.nan)
    piv_l = np.full(len(df), np.nan)
    for j in range(n, len(df) - n):
        if h[j] == max(h[j - n:j + n + 1]) and h[j] > max(np.r_[h[j - n:j], h[j + 1:j + n + 1]]):
            piv_h[j + n] = h[j]
        if l_[j] == min(l_[j - n:j + n + 1]) and l_[j] < min(np.r_[l_[j - n:j], l_[j + 1:j + n + 1]]):
            piv_l[j + n] = l_[j]
    df["swing_h"] = pd.Series(piv_h).ffill().values
    df["swing_l"] = pd.Series(piv_l).ffill().values
    # structure: BOS = close beyond the last swing in the trend's direction; CHoCH = first break against it
    trend = np.zeros(len(df), dtype=int)
    bos_up = np.zeros(len(df), dtype=bool)
    bos_dn = np.zeros(len(df), dtype=bool)
    choch = np.zeros(len(df), dtype=bool)
    t = 0
    last_broken_h = last_broken_l = np.nan
    c = df["c"].values
    sh, sl = df["swing_h"].values, df["swing_l"].values
    for i in range(len(df)):
        if not np.isnan(sh[i]) and c[i] > sh[i] and sh[i] != last_broken_h:
            choch[i] = t == -1
            bos_up[i], t, last_broken_h = True, 1, sh[i]
        elif not np.isnan(sl[i]) and c[i] < sl[i] and sl[i] != last_broken_l:
            choch[i] = t == 1
            bos_dn[i], t, last_broken_l = True, -1, sl[i]
        trend[i] = t
    df["trend"], df["bos_up"], df["bos_dn"], df["choch"] = trend, bos_up, bos_dn, choch
    # fair value gaps formed at bar i (3-bar pattern ending at i)
    df["fvg_bull"] = df["l"] > df["h"].shift(2)          # gap between bar i-2 high and bar i low
    df["fvg_bear"] = df["h"] < df["l"].shift(2)
    df["fvg_bull_lo"] = df["h"].shift(2).where(df["fvg_bull"])
    df["fvg_bull_hi"] = df["l"].where(df["fvg_bull"])
    df["fvg_bear_hi"] = df["l"].shift(2).where(df["fvg_bear"])
    df["fvg_bear_lo"] = df["h"].where(df["fvg_bear"])
    # data completeness: holes inside a trade date
    gap = df["ts"].diff().dt.total_seconds().div(60)
    same = df["td"].eq(df["td"].shift(1))
    df["gap_min"] = gap.where(same, 0)
    df.attrs["spec"] = spec.root
    df.attrs["bar_minutes"] = bar_minutes
    return df


def volume_profile(df: pd.DataFrame, spec: ProductSpec, va_pct: float = 0.70, target_bins: int = 80) -> dict | None:
    """Volume by price, spreading each bar's volume evenly across its range. POC, value area, HVN/LVN.
    Built from bars, not ticks, so it's an approximation; it says so."""
    if df.empty or df["v"].sum() <= 0:
        return None
    tick = float(spec.tick)
    lo, hi = df["l"].min(), df["h"].max()
    ticks = max(1, int(round((hi - lo) / tick)))
    step_ticks = max(1, int(round(ticks / target_bins)))
    step = step_ticks * tick
    edges = np.arange(lo, hi + step, step)
    if len(edges) < 2:
        return None
    vol = np.zeros(len(edges))
    for bl, bh, bv in zip(df["l"].values, df["h"].values, df["v"].values, strict=True):
        if bv <= 0:
            continue
        i0 = int((bl - lo) // step)
        i1 = int((bh - lo) // step)
        k = max(1, i1 - i0 + 1)
        vol[i0:i1 + 1] += bv / k
    poc_i = int(vol.argmax())
    total = vol.sum()
    a = b = poc_i
    acc = vol[poc_i]
    while acc < va_pct * total and (a > 0 or b < len(vol) - 1):
        up = vol[b + 1] if b < len(vol) - 1 else -1
        dn = vol[a - 1] if a > 0 else -1
        if up >= dn:
            b += 1
            acc += up
        else:
            a -= 1
            acc += dn
    centers = edges + step / 2
    sm = np.convolve(vol, np.ones(3) / 3, mode="same")
    hvn = [round_to_tick(centers[i], spec) for i in range(1, len(sm) - 1) if sm[i] > sm[i - 1] and sm[i] >= sm[i + 1] and sm[i] > 1.2 * sm.mean()]
    lvn = [round_to_tick(centers[i], spec) for i in range(1, len(sm) - 1) if sm[i] < sm[i - 1] and sm[i] <= sm[i + 1] and sm[i] < 0.6 * sm.mean()
           and a <= i <= b]
    return {"poc": round_to_tick(centers[poc_i], spec), "vah": round_to_tick(edges[b] + step, spec), "val": round_to_tick(edges[a], spec),
            "hvn": hvn[:6], "lvn": lvn[:6], "bin_ticks": step_ticks,
            "note": "Built from bar volume spread across each bar's range, not tick-by-tick trades; treat levels as approximate."}


def recent_fvgs(df: pd.DataFrame, lookback: int = 60) -> list[dict]:
    """Unfilled fair value gaps from the last `lookback` bars, newest first."""
    out = []
    sub = df.tail(lookback)
    for idx, r in sub.iterrows():
        for kind, lo_c, hi_c in (("bullish", "fvg_bull_lo", "fvg_bull_hi"), ("bearish", "fvg_bear_lo", "fvg_bear_hi")):
            lo, hi = r[lo_c], r[hi_c]
            if pd.isna(lo) or pd.isna(hi):
                continue
            after = df.loc[idx + 1:]
            filled = (after["l"] <= lo).any() if kind == "bullish" else (after["h"] >= hi).any()
            if not filled:
                out.append({"kind": kind, "low": float(lo), "high": float(hi), "formed": r["ts"].isoformat()})
    return out[::-1][:6]


def sweep_events(df: pd.DataFrame, levels: dict, spec: ProductSpec, lookback: int = 6) -> list[dict]:
    """Bars that traded beyond a key level and closed back inside it (stop runs / liquidity sweeps)."""
    tick = float(spec.tick)
    out = []
    for _, r in df.tail(lookback).iterrows():
        for name, lv in levels.items():
            if lv is None or (isinstance(lv, float) and np.isnan(lv)):
                continue
            if r["h"] >= lv + tick and r["c"] < lv:
                out.append({"level": name, "price": lv, "side": "above", "ts": r["ts"].isoformat(),
                            "text": f"Swept above {name.upper()} ({fmt_num(lv)}) and closed back below"})
            if r["l"] <= lv - tick and r["c"] > lv:
                out.append({"level": name, "price": lv, "side": "below", "ts": r["ts"].isoformat(),
                            "text": f"Swept below {name.upper()} ({fmt_num(lv)}) and closed back above"})
    return out


def regime(F: pd.DataFrame, i: int) -> dict:
    """Market regime at bar i from information available at its close: structure trend, position vs VWAP,
    volatility relative to the recent past, and day type once the initial balance is set."""
    r = F.iloc[i]
    look = F["atr"].iloc[max(0, i - 600):i + 1].dropna()
    pct = float((look <= r["atr"]).mean() * 100) if len(look) > 50 and pd.notna(r["atr"]) else None
    vol = ("unknown" if pct is None else "low" if pct < 20 else "normal" if pct < 80 else "high" if pct < 97 else "extreme")
    trend = {1: "up", -1: "down", 0: "undetermined"}[int(r["trend"])]
    vw = "above VWAP" if pd.notna(r["vwap"]) and r["c"] > r["vwap"] else "below VWAP" if pd.notna(r["vwap"]) else "VWAP n/a"
    day = "initial balance forming"
    if pd.notna(r.get("ib_h")) and pd.notna(r.get("ib_l")):
        rng = r["ib_h"] - r["ib_l"]
        if rng > 0 and (r["c"] > r["ib_h"] + 0.5 * rng or r["c"] < r["ib_l"] - 0.5 * rng):
            day = "range extension (trend-day behaviour)"
        elif r["ib_l"] <= r["c"] <= r["ib_h"]:
            day = "inside the initial balance (rotational)"
        else:
            day = "testing outside the initial balance"
    label = f"{'trending ' + trend if trend != 'undetermined' else 'no clear trend'}, {vol} volatility"
    return {"label": label, "trend": trend, "vs_vwap": vw, "volatility": vol, "atr_percentile": round(pct, 0) if pct is not None else None,
            "day_type": day, "atr": round(float(r["atr"]), 4) if pd.notna(r["atr"]) else None, "as_of": r["ts"].isoformat()}
