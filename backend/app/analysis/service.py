"""Fetches and caches bars per symbol/timeframe and builds feature frames for live use.

Live analysis only ever uses CLOSED bars: Yahoo's history includes the bar still forming,
which is dropped here so a signal can't be based on a candle that hasn't finished.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

from ..market_data.providers.base import MarketDataProvider
from ..market_data.types import Timeframe
from .engine import mtf_summary, series_for_chart, snapshot, to_jsonable
from .features import FeatureFrame, build

LOOKBACK_DAYS = {Timeframe.M1: 5, Timeframe.M2: 10, Timeframe.M5: 15, Timeframe.M15: 30, Timeframe.M30: 55,
                 Timeframe.H1: 200, Timeframe.H4: 700, Timeframe.D1: 600}


class AnalysisService:
    def __init__(self, provider: MarketDataProvider):
        self.provider = provider
        self._cache: dict[tuple[str, Timeframe], tuple[float, FeatureFrame, list]] = {}
        self._locks: dict[tuple[str, Timeframe], asyncio.Lock] = {}

    def _ttl(self, tf: Timeframe) -> float:
        return min(max(tf.seconds / 2, 30), 900)

    async def frame(self, symbol: str, tf: Timeframe, force: bool = False) -> FeatureFrame:
        key = (symbol, tf)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._cache.get(key)
            if hit and not force and time.monotonic() - hit[0] < self._ttl(tf):
                return hit[1]
            bars, notes = await self.provider.get_bars(symbol, tf, datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS[tf]))
            now = datetime.now(timezone.utc)
            if tf != Timeframe.D1:
                bars = [b for b in bars if b.ts + timedelta(seconds=tf.seconds) <= now]  # closed bars only
            ff = await asyncio.to_thread(build, bars, tf)
            ff.notes = list(notes) + ff.notes
            self._cache[key] = (time.monotonic(), ff, bars)
            return ff

    def cached_bars(self, symbol: str, tf: Timeframe) -> list:
        hit = self._cache.get((symbol, tf))
        return hit[2] if hit else []

    async def analyze(self, symbol: str, timeframes: list[Timeframe], chart_tf: Timeframe | None = None, extended: bool = False) -> dict:
        snaps, frames = {}, {}
        for tf in timeframes:
            ff = await self.frame(symbol, tf)
            frames[tf] = ff
            snaps[tf.value] = to_jsonable(snapshot(ff))
        out = {"symbol": symbol, "snapshots": snaps, "mtf": mtf_summary(snaps)}
        ctf = chart_tf or timeframes[0]
        ff = frames.get(ctf) or await self.frame(symbol, ctf)
        bars = self.cached_bars(symbol, ctf)
        if ctf not in (Timeframe.D1, Timeframe.H4) and not extended:
            # match the analysis: indicators are computed on the regular session only
            from ..core.market_clock import ET

            bars = [b for b in bars if 570 <= (lambda t: t.hour * 60 + t.minute)(b.ts.astimezone(ET)) < 960]
        out["chart"] = {"timeframe": ctf.value, "extended_hours": extended,
                        "bars": [{"time": int(b.ts.timestamp()), "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                                  "volume": b.volume} for b in bars[-800:]],
                        "series": series_for_chart(ff, 800)}
        return out
