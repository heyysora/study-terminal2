"""Turn candles read from a chart into timestamped bars for the futures analysis.

Times are CALCULATED: the right-most candle is the bar containing the capture time (or the session's last bar when the market is
closed); each candle to its left is the previous session-aligned bar. That assumes the chart shows every bar without gaps, which is
how time-based candle charts work; it's stated wherever these bars are used.

Levels that need history the screenshot doesn't contain are removed, not guessed: previous-day levels need the whole previous session
visible, overnight levels need the current session's open visible, opening range / initial balance need the RTH open visible, and
session VWAP needs the session open visible unless you assigned the VWAP line's color (then the on-screen VWAP is used).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ..futures import features as ff
from ..futures.candles import bucket_start
from ..futures.sessions import FuturesClock


def candle_times(n: int, tf_seconds: int, captured_at: datetime, clock: FuturesClock) -> list[datetime] | None:
    """Start times for n contiguous candles ending with the one that contains `captured_at`, oldest first."""
    t = captured_at
    b = bucket_start(t, tf_seconds, clock)
    probe = 0
    while b is None and probe < 6 * 24 * 60:                    # market closed: last bar of the previous session
        t -= timedelta(minutes=1)
        probe += 1
        b = bucket_start(t, tf_seconds, clock)
    if b is None:
        return None
    out = [b[0]]
    cur = b[0]
    while len(out) < n:
        p = cur - timedelta(seconds=1)
        prev = bucket_start(p, tf_seconds, clock)
        probe = 0
        while prev is None and probe < 6 * 24 * 60:            # skip the daily break / weekend
            p -= timedelta(minutes=1)
            probe += 1
            prev = bucket_start(p, tf_seconds, clock)
        if prev is None:
            return None
        cur = prev[0]
        out.append(cur)
    return out[::-1]


def bars_from_reading(reading, tf_seconds: int, clock: FuturesClock) -> tuple[list[dict], list[str]]:
    notes: list[str] = []
    cs = reading.candles
    if not cs:
        return [], ["No candles readable."]
    times = candle_times(len(cs), tf_seconds, datetime.fromisoformat(reading.captured_at), clock)
    if times is None:
        return [], ["Couldn't place the candles in a trading session."]
    bars = []
    for c, t in zip(cs, times, strict=True):
        o = c.open if c.open is not None else (c.high + c.low) / 2
        cl = c.close if c.close is not None else (c.high + c.low) / 2
        bars.append({"ts": t, "open": o, "high": c.high, "low": c.low, "close": cl,
                     "volume": float(c.volume_rel * 1000) if c.volume_rel is not None else 0.0, "closed": True,
                     "confidence": c.confidence, "body_known": c.body_known})
    bars[-1]["closed"] = False                                # the right-most candle is still forming
    if any(not b["body_known"] for b in bars):
        notes.append(f"{sum(1 for b in bars if not b['body_known'])} candle bodies weren't readable; their open/close are set to the "
                     "middle of the range and those candles count as low confidence.")
    notes.append("Candle times are calculated from the timeframe and the capture time (no time-axis reading).")
    return bars, notes


def visual_frame(bars: list[dict], spec, clock: FuturesClock, tf_seconds: int, screen_vwap: list | None = None,
                 has_volume: bool = True) -> tuple[pd.DataFrame, list[str]]:
    """Feature frame from completed visual bars, with history-dependent levels removed when that history isn't on screen."""
    notes: list[str] = []
    done = [b for b in bars if b.get("closed", True)]
    F = ff.build(ff.bars_to_frame(done, clock), spec, clock, bar_minutes=max(1, tf_seconds // 60))
    if F.empty:
        return F, ["No completed candles."]
    first_ts = F["ts"].iloc[0].to_pydatetime()
    wins = F.attrs.get("windows", {})
    first_td = F["td"].iloc[0]
    w0 = wins.get(first_td) or clock.window(first_td)
    session_start_visible = bool(w0 and first_ts <= w0.open + timedelta(seconds=tf_seconds))
    # previous-day levels: the first trade date shown must be complete for the next date's values to be right
    if not session_start_visible:
        nxt = F["td"] != first_td
        for col in ("pdh", "pdl", "pdc", "pgh", "pgl"):
            F.loc[nxt, col] = np.nan
        F.loc[F["td"] == first_td, ["onh", "onl", "pmh", "pml"]] = np.nan
        notes.append("Previous-day and overnight levels need the start of the earlier session on screen; they're shown as unavailable.")
    # opening range / initial balance: the RTH open of each date must be visible
    for td, g in F.groupby("td"):
        rth = g[g["rth"]]
        if len(rth) and rth["min_from_rth"].iloc[0] > 0.5:
            F.loc[F["td"] == td, ["or_h", "or_l", "ib_h", "ib_l"]] = np.nan
    # VWAP: the line you mapped on screen, else only when the session open is visible
    if screen_vwap is not None:
        vals = screen_vwap[: len(F)]
        F["vwap"] = pd.Series([np.nan if v is None else float(v) for v in vals] + [np.nan] * (len(F) - len(vals)), dtype=float).values
        notes.append("VWAP is read from the chart (the line color you assigned).")
    elif not has_volume or not session_start_visible:
        F[["vwap", "vwap_sd", "rth_vwap"]] = np.nan
        notes.append("VWAP is unavailable: assign the VWAP line color in the profile, or show the session open and the volume pane.")
    return F, notes


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
