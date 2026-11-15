"""Fetches and caches bars per symbol/timeframe and builds feature frames for live use.

Live analysis only ever uses CLOSED bars: Yahoo's history includes the bar still forming,
which is dropped here so a signal can't be based on a candle that hasn't finished.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

from ..core.market_clock import ET, regular_close_minute
from ..market_data.providers.base import MarketDataProvider, ProviderError
from ..market_data.types import DataStatus, Timeframe
from ..market_data.validation import validate_bars
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
        """Closed, validated bars as a feature frame. If a refresh fails and an older copy exists,
        the older copy is returned marked served_from_cache (labeled CACHED, never used for signals)."""
        key = (symbol, tf)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            hit = self._cache.get(key)
            if hit and not force and time.monotonic() - hit[0] < self._ttl(tf):
                return hit[1]
            try:
                bars, notes = await self.provider.get_bars(symbol, tf, datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS[tf]))
            except ProviderError as e:
                if hit:
                    old = hit[1]
                    old.served_from_cache, old.refresh_error = True, str(e)
                    return old
                raise
            now = datetime.now(timezone.utc)
            if tf != Timeframe.D1:
                bars = [b for b in bars if b.ts + timedelta(seconds=tf.seconds) <= now]  # closed bars only
            bars, report = validate_bars(bars, tf.seconds if tf != Timeframe.D1 else None)
            from ..market_data.hours import asset_kind
            ff = await asyncio.to_thread(build, bars, tf, asset_kind(symbol) == "crypto")
            ff.notes = list(notes) + ff.notes
            ff.quality = report.to_dict()
            ff.provider = self.provider.info.name
            ff.source = bars[-1].source if bars else None
            ff.fetched_at = now
            if not report.ok:
                ff.notes.append(f"Data quality: {report.summary()}.")
            self._cache[key] = (time.monotonic(), ff, bars)
            return ff

    def data_info(self, ff: FeatureFrame) -> dict:
        """Where a chart's data came from and how old it is. Shown next to every chart."""
        now = datetime.now(timezone.utc)
        last = ff.df.index[-1].to_pydatetime() if not ff.df.empty else None
        age = (now - ff.fetched_at).total_seconds() if ff.fetched_at else None
        if ff.served_from_cache:
            status, reason = DataStatus.CACHED, (f"Showing the copy fetched at {ff.fetched_at.astimezone(ET):%H:%M:%S} ET because "
                                                 f"refreshing failed: {ff.refresh_error}. Signals are off for this chart.")
        else:
            status, reason = DataStatus.HISTORICAL, ("Bars from the provider's history endpoint; only fully closed bars are used. "
                                                     "The live price comes from the stream/poll, not these bars.")
        return {"status": status.value, "reason": reason, "provider": ff.provider, "source": ff.source,
                "fetched_at": ff.fetched_at.isoformat() if ff.fetched_at else None, "fetched_age_seconds": round(age, 1) if age is not None else None,
                "last_closed_bar": last.isoformat() if last else None, "bars": int(len(ff.df)), "quality": ff.quality,
                "refresh_error": ff.refresh_error}

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
            bars = [b for b in bars if 570 <= (lambda t: t.hour * 60 + t.minute)(b.ts.astimezone(ET)) < regular_close_minute(b.ts.astimezone(ET).date())]
        out["data"] = self.data_info(ff)
        out["chart"] = {"timeframe": ctf.value, "extended_hours": extended, "data": out["data"],
                        "bars": [{"time": int(b.ts.timestamp()), "open": b.open, "high": b.high, "low": b.low, "close": b.close,
                                  "volume": b.volume} for b in bars[-800:]],
                        "series": series_for_chart(ff, 800)}
        return out
