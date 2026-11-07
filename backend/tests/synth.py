"""Deterministic synthetic market data for tests (never shown to users as real data)."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

import numpy as np

from app.core.market_clock import ET
from app.market_data.types import Bar, Timeframe


def sessions(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def intraday(symbol="TEST", days=6, minutes=5, start=date(2026, 9, 1), seed=1, drift=0.0, vol=0.002,
             base=100.0, premarket=True, path=None) -> list[Bar]:
    """Random-walk 5m bars for regular hours (+ zero-volume premarket bars like Yahoo).
    `path`: optional list of closes for the LAST session to script a pattern."""
    rng = np.random.default_rng(seed)
    bars, price = [], base
    tf = Timeframe(f"{minutes}Min")
    sess = sessions(start, days)
    for di, d in enumerate(sess):
        if premarket:
            for k in range(0, 330, minutes * 6):  # sparse premarket bars 04:00-09:30
                t = datetime.combine(d, time(4, 0), tzinfo=ET) + timedelta(minutes=k)
                p = price * (1 + rng.normal(0, vol))
                bars.append(Bar(symbol=symbol, timeframe=tf.value, ts=t.astimezone(timezone.utc), open=p, high=p * 1.001,
                                low=p * 0.999, close=p, volume=0, provider="synthetic", source="test"))
        n = 390 // minutes
        scripted = path if (path is not None and di == len(sess) - 1) else None
        for k in range(n):
            t = datetime.combine(d, time(9, 30), tzinfo=ET) + timedelta(minutes=k * minutes)
            o = price
            c = scripted[k] if scripted is not None and k < len(scripted) else price * (1 + drift + rng.normal(0, vol))
            h = max(o, c) * (1 + abs(rng.normal(0, vol / 3)))
            lo = min(o, c) * (1 - abs(rng.normal(0, vol / 3)))
            v = float(rng.integers(5_000, 15_000)) * (3 if k < 6 else 1)
            bars.append(Bar(symbol=symbol, timeframe=tf.value, ts=t.astimezone(timezone.utc), open=o, high=h, low=lo,
                            close=c, volume=v, provider="synthetic", source="test"))
            price = c
    return bars


def daily(symbol="TEST", n=300, start=date(2025, 1, 2), seed=2, drift=0.0005, vol=0.015, base=50.0) -> list[Bar]:
    rng = np.random.default_rng(seed)
    out, price = [], base
    for d in sessions(start, n):
        o = price
        c = price * (1 + drift + rng.normal(0, vol))
        h, lo = max(o, c) * (1 + abs(rng.normal(0, vol / 3))), min(o, c) * (1 - abs(rng.normal(0, vol / 3)))
        out.append(Bar(symbol=symbol, timeframe="1Day", ts=datetime.combine(d, time(0, 0), tzinfo=ET).astimezone(timezone.utc),
                       open=o, high=h, low=lo, close=c, volume=float(rng.integers(1e6, 3e6)), provider="synthetic", source="test"))
        price = c
    return out
