"""Futures market data with honest labels.

Sources:
  * Yahoo Finance (default, free, no account). Specific contracts (ESZ26.CME) and continuous front month (ES=F).
    Yahoo itself reports CME futures quotes as delayed (10 minutes when checked on 2026-11-07), so these bars
    are labeled DELAYED and never produce signals or live paper fills.
  * TopstepX API (optional, paid by you, read-only; see projectx.py). Polled bars -> POLLING when fresh.

Status rules: market closed -> HISTORICAL. Newest bar older than the expected delay plus two bars -> STALE.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from ..market_data.types import Timeframe
from .contracts import Contract
from .feed import SourceHealth, validate_bars
from .projectx import ProjectXClient, ProjectXError
from .sessions import FuturesClock

log = logging.getLogger(__name__)

SOURCES = [
    {"id": "yahoo", "name": "Yahoo Finance", "realtime": "No: delayed (Yahoo reports a 10-minute delay on CME futures)",
     "coverage": "CME/CBOT/NYMEX/COMEX specific contracts (e.g. ESZ26.CME) and continuous front month (ES=F)",
     "streaming": "No (pulled on a timer)", "requirements": "None", "cost": "Free",
     "limits": "Unofficial; 1-minute bars for about 7 days, 5-minute for about 60 days; rate-limited without notice",
     "status_in_app": "DELAYED: analysis and study only, no signals, no live paper fills", "default": True},
    {"id": "projectx", "name": "TopstepX API (ProjectX Gateway)", "realtime": "Yes (real-time data included with the subscription)",
     "coverage": "Products tradable on TopstepX", "streaming": "Yes via SignalR hubs; Study Terminal polls REST bars (POLLING)",
     "requirements": "A Topstep account, a ProjectX API Access subscription and an API key from TopstepX > Settings > API",
     "cost": "$29/month, or $14.50 with the code 'topstep' (help.topstep.com, checked 2026-11-07)",
     "limits": "retrieveBars 50 requests / 30 s; other endpoints 200 / 60 s; 20,000 bars per request",
     "status_in_app": "POLLING when fresh: signals allowed on 5-minute bars", "default": False,
     "note": "Optional. Read-only in Study Terminal. Not tested against a real account."},
    {"id": "databento", "name": "Databento (not built in)", "realtime": "Yes", "coverage": "Full CME Globex (CME, CBOT, NYMEX, COMEX)",
     "streaming": "Yes", "requirements": "Account and CME license", "cost": "Live CME data from $32.65/month non-professional license plus usage, "
     "or a $199/month plan; historical pay-as-you-go with $125 free credits", "limits": "Usage-based",
     "status_in_app": "Not integrated (paid). The provider interface is ready for it.", "default": False},
    {"id": "screen", "name": "Your TopstepX screen (OCR)", "realtime": "As fast as your screen", "coverage": "Whatever chart you show",
     "streaming": "Screen capture, with your consent", "requirements": "Screen monitoring turned on", "cost": "Free",
     "limits": "Reads the visible price and chart only; can misread; never used as the price for signals or fills",
     "status_in_app": "Cross-check only", "default": False},
]


class FuturesData:
    def __init__(self, yahoo, store, projectx: ProjectXClient | None = None):
        self.yahoo, self.store, self.projectx = yahoo, store, projectx
        self._cache: dict[tuple, tuple[float, list, dict, list]] = {}
        self._delay: dict[str, tuple[float, int | None, str | None]] = {}
        self._lock = asyncio.Lock()
        self.health: dict[str, SourceHealth] = {}
        self.last_validation: dict[str, dict] = {}

    @property
    def source(self) -> str:
        want = self.store.get("futures.data_source", "yahoo")
        return "projectx" if want == "projectx" and self.projectx else "yahoo"

    async def _delay_minutes(self, symbol: str) -> tuple[int | None, str | None]:
        hit = self._delay.get(symbol)
        if hit and time.monotonic() - hit[0] < 3600:
            return hit[1], hit[2]
        try:
            info = await self.yahoo.get_feed_info(symbol)
            d = info.delay_minutes
            if d is None and info.realtime_price is False:
                d = None
            src = info.price_source
        except Exception as e:  # noqa: BLE001
            log.info("feed info failed for %s: %s", symbol, e)
            d, src = None, None
        self._delay[symbol] = (time.monotonic(), d, src)
        return d, src

    def _h(self, key: str) -> SourceHealth:
        return self.health.setdefault(key, SourceHealth(key))

    async def bars(self, contract: Contract, tf: Timeframe, clock: FuturesClock, days: float = 6, now: datetime | None = None) -> tuple[list[dict], dict, list[str]]:
        key = (contract.code, tf.value, self.source, round(days, 2))
        ttl = 20 if tf.seconds <= 300 else 60
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1], hit[2], hit[3]
        async with self._lock:
            now = now or datetime.now(timezone.utc)
            notes: list[str] = []
            source_used = self.source
            h = self._h(f"{source_used}:{contract.code}:{tf.value}")
            if h.backing_off and hit:
                return self._cached(hit, h, notes)
            try:
                bars, symbol, source_used, n = await self._fetch(contract, tf, days, now, source_used)
                notes += n
                h.ok()
            except Exception as e:  # noqa: BLE001 - any provider failure: serve the last good copy, labeled
                h.fail(f"{type(e).__name__}: {str(e)[:160]}")
                if hit:
                    return self._cached(hit, h, notes)
                return [], {"provider": source_used, "symbol": contract.code, "timeframe": tf.value, "status": "unavailable",
                            "reason": f"Couldn't load data: {h.last_error}. Retrying in {h.to_dict()['retry_in_seconds']} s.",
                            "health": h.to_dict()}, notes
            bars, rep = validate_bars(bars, tf.seconds, contract.spec, clock, now)
            self.last_validation[f"{contract.code}:{tf.value}"] = rep
            label = await self.label(bars, tf, clock, source_used, symbol, now)
            label["validation"] = {k: rep[k] for k in ("summary", "duplicates", "impossible", "future", "off_tick", "missing_total", "ok")}
            label["health"] = h.to_dict()
            label["fetched_at"] = now.isoformat()
            self._cache[key] = (time.monotonic(), bars, label, notes)
            return bars, label, notes

    def _cached(self, hit, h: SourceHealth, notes: list[str]):
        age = time.monotonic() - hit[0]
        label = {**hit[2], "status": "cached", "health": h.to_dict(),
                 "reason": f"Showing the copy fetched {age / 60:.0f} min ago because the source is failing ({h.last_error}). "
                           "Not live: no signals or simulator entries until fresh data returns."}
        return hit[1], label, notes + ["Source failing; cached copy shown."]

    async def _fetch(self, contract: Contract, tf: Timeframe, days: float, now: datetime, source_used: str):
        notes: list[str] = []
        if source_used == "projectx":
            try:
                bars = await self.projectx.bars(contract.short_code, tf.seconds // 60, now - timedelta(days=days), now)
                return bars, contract.short_code, "projectx", notes
            except ProjectXError as e:
                notes.append(f"TopstepX API failed ({e}). Showing Yahoo's DELAYED data instead, labeled as such; live TopstepX data is "
                             "unavailable until the API recovers.")
        symbol = contract.yahoo_symbol
        try:
            raw, n2 = await self.yahoo.get_bars(symbol, tf, now - timedelta(days=days))
        except Exception as e:  # noqa: BLE001
            cont = f"{contract.root}=F"
            notes.append(f"Yahoo has no data for {symbol} ({type(e).__name__}); using the continuous front-month series {cont}, "
                         "which can differ from your contract around a roll.")
            symbol = cont
            raw, n2 = await self.yahoo.get_bars(cont, tf, now - timedelta(days=days))
        bars = [{"ts": b.ts, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in raw]
        notes += [n for n in n2 if "extended-hours" not in n and "dividend" not in n]
        return bars, symbol, "yahoo", notes

    async def label(self, bars: list[dict], tf: Timeframe, clock: FuturesClock, source: str, symbol: str, now: datetime) -> dict:
        base = {"provider": source, "symbol": symbol, "timeframe": tf.value}
        if not bars:
            return {**base, "status": "unavailable", "reason": "No bars returned."}
        last_end = bars[-1]["ts"] + timedelta(seconds=tf.seconds)
        age = (now - last_end).total_seconds()
        base.update({"data_time": bars[-1]["ts"].isoformat(), "age_seconds": round(age, 1)})
        if clock.window_at(now) is None:
            return {**base, "status": "historical", "reason": "Market closed (weekend, holiday or daily break). Showing the last session."}
        if source == "projectx":
            if age > 2 * tf.seconds + 60:
                return {**base, "status": "stale", "reason": f"Newest TopstepX bar ended {age / 60:.0f} minutes ago."}
            return {**base, "status": "polling", "reason": "TopstepX API bars, polled (not streamed). Fine for 5-minute setups."}
        delay, src = await self._delay_minutes(symbol)
        expected = (delay or 0) * 60
        if age > expected + 2 * tf.seconds + 300:
            return {**base, "status": "stale", "delay_minutes": delay,
                    "reason": f"Newest Yahoo bar ended {age / 60:.0f} minutes ago (more than the {delay or '?'}-minute delay plus two bars)."}
        if delay:
            return {**base, "status": "delayed", "delay_minutes": delay, "price_source": src,
                    "reason": f"Yahoo reports this futures quote as delayed {delay} minutes."}
        if delay == 0:
            return {**base, "status": "delayed", "delay_minutes": 0,
                    "reason": "Yahoo lists no delay for this quote, but its futures data is unofficial and usually delayed; treated as delayed."}
        return {**base, "status": "delayed", "delay_minutes": None,
                "reason": "Yahoo didn't confirm whether this futures quote is real-time; treated as delayed."}
