"""MarketMonitor: always-on market monitoring through a pluggable provider.

  stream loop  provider's push feed (Yahoo socket), if available and enabled
  poll loop    1-minute bars for every monitored symbol on a timer (fills stream gaps,
               feeds the bar cache, and is the only source in poll_only mode)
  feed loop    asks the provider how timely each symbol's quotes are (real-time vs delayed)
  heartbeat    re-labels freshness every 5s and pushes changes to the UI

Everything downstream (UI, paper simulator, and later the scanner/signals) consumes
Ticks + labels from here and never talks to a provider directly.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..config import Settings
from ..core.events import Broadcaster
from ..core.market_clock import MarketClock
from ..db.models import AppEvent, BarRecord, WatchlistSymbol
from ..db.session import Database
from .freshness import FreshnessTracker
from .providers.base import MarketDataProvider, ProviderError, ProviderRateLimited, StreamState, SymbolNotFound, TickStream
from .types import Bar, DataStatus, LabeledValue, Tick, Timeframe

log = logging.getLogger(__name__)

TickListener = Callable[[Tick, LabeledValue], None]
BarListener = Callable[[Bar, LabeledValue], None]


@dataclass
class MarketMonitor:
    settings: Settings
    db: Database
    provider: MarketDataProvider
    broadcaster: Broadcaster = field(default_factory=Broadcaster)
    clock: MarketClock = field(default_factory=MarketClock)

    def __post_init__(self) -> None:
        s = self.settings
        self.streaming_enabled = s.live_mode == "stream_and_poll" and self.provider.info.supports_streaming
        self.tracker = FreshnessTracker(
            provider=self.provider.info, poll_interval_s=s.poll_interval_seconds,
            regular_stale_s=s.regular_hours_stale_seconds, extended_stale_s=s.extended_hours_stale_seconds,
            streaming_enabled=self.streaming_enabled,
        )
        if not self.streaming_enabled:
            self.tracker.set_stream_state(StreamState.IDLE, "Streaming disabled (poll_only mode)")
        self.stream: TickStream | None = None
        self.tick_listeners: list[TickListener] = []
        self.bar_listeners: list[BarListener] = []
        self.extra_symbols: Callable[[], list[str]] = lambda: []
        self._tasks: list[asyncio.Task] = []
        self._pending_bars: list[Bar] = []
        self._last_bar_ts: dict[str, datetime] = {}
        self._last_status: dict[str, str] = {}
        self._unknown: set[str] = set()
        self.polls = 0
        self.started_at = datetime.now(timezone.utc)
        self.monitoring_enabled = True
        self.paused_reason: str | None = None
        self.sleep_events: list[dict] = []

    # ---------------- lifecycle ----------------

    async def start(self) -> None:
        if self.streaming_enabled:
            self.stream = self.provider.create_stream(self._on_stream_tick, self._on_stream_state)
            await self.stream.set_symbols(self.monitored_symbols())
            self._tasks.append(asyncio.create_task(self.stream.run(), name="stream"))
        self._tasks += [
            asyncio.create_task(self._poll_loop(), name="poll"),
            asyncio.create_task(self._feed_info_loop(), name="feed-info"),
            asyncio.create_task(self._heartbeat(), name="heartbeat"),
            asyncio.create_task(self._bar_writer(), name="bar-writer"),
        ]
        self._event("info", "market_data", f"Monitoring via {self.provider.info.display_name}; mode={self.settings.live_mode}")

    async def stop(self) -> None:
        if self.stream:
            await self.stream.stop()
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
        await self._flush_bars()
        await self.provider.aclose()

    # ---------------- symbols ----------------

    def watchlist_symbols(self) -> list[str]:
        with self.db.session() as s:
            rows = s.scalars(select(WatchlistSymbol.symbol).order_by(WatchlistSymbol.watchlist_id, WatchlistSymbol.position)).all()
        return list(dict.fromkeys(rows))

    def monitored_symbols(self) -> list[str]:
        """Open positions/orders first (never dropped), then watchlists, capped for rate limits."""
        syms = list(dict.fromkeys([*self.extra_symbols(), *self.watchlist_symbols()]))
        return [s for s in syms if s not in self._unknown][: self.settings.max_live_symbols]

    def over_limit(self) -> list[str]:
        syms = list(dict.fromkeys([*self.extra_symbols(), *self.watchlist_symbols()]))
        return [s for s in syms if s not in self._unknown][self.settings.max_live_symbols:]

    async def refresh_symbols(self) -> None:
        if self.stream and self.monitoring_enabled:
            await self.stream.set_symbols(self.monitored_symbols())

    # ---------------- stream ----------------

    def _on_stream_state(self, state: StreamState, reason: str) -> None:
        self.tracker.set_stream_state(state, reason)
        level = "info" if state in (StreamState.CONNECTED, StreamState.CONNECTING) else "warning"
        self._event(level, "stream", f"{state.value}: {reason}")
        self.broadcaster.publish({"type": "connection", "data": self.status()})

    def _on_stream_tick(self, tick: Tick) -> None:
        self.tracker.on_tick(tick)
        label = self.label(tick.symbol)
        self.broadcaster.publish({"type": "tick", "data": {**tick.model_dump(mode="json"), "label": label.model_dump(mode="json")}})
        for fn in self.tick_listeners:
            try:
                fn(tick, label)
            except Exception:
                log.exception("tick listener failed")

    # ---------------- polling ----------------

    async def poll_once(self, symbols: list[str] | None = None) -> int:
        symbols = symbols if symbols is not None else self.monitored_symbols()
        if not symbols:
            return 0
        try:
            data = await self.provider.get_recent_bars(symbols)
        except ProviderRateLimited as e:
            self.tracker.poll_failed(str(e))
            self._event("warning", "market_data", str(e))
            return 0
        except ProviderError as e:
            self.tracker.poll_failed(str(e))
            self._event("warning", "market_data", f"Poll failed: {e}")
            return 0
        now = datetime.now(timezone.utc)
        self.tracker.poll_succeeded(now)
        self.polls += 1
        for sym, bars in data.items():
            if not bars:
                continue
            last_seen = self._last_bar_ts.get(sym)
            new = [b for b in bars if last_seen is None or b.ts >= last_seen]
            if last_seen is None:
                new = bars[-3:]  # first poll: only the latest bars matter for live use
            self._pending_bars.extend(new)
            self._last_bar_ts[sym] = bars[-1].ts
            last = bars[-1]
            tick = Tick(symbol=sym, price=last.close, ts=min(last.ts + timedelta(seconds=60), now), received_at=now,
                        provider=last.provider, source=last.source, day_volume=None)
            self.tracker.on_tick(tick)
            label = self.label(sym)
            for b in new:
                for fn in self.bar_listeners:
                    try:
                        fn(b, label)
                    except Exception:
                        log.exception("bar listener failed")
            self.broadcaster.publish({"type": "bar", "data": {**last.model_dump(mode="json"), "label": label.model_dump(mode="json")}})
        return len(data)

    async def _poll_loop(self) -> None:
        while True:
            if self.monitoring_enabled:
                await self.poll_once()
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def pause(self, reason: str = "Paused by you") -> None:
        self.monitoring_enabled, self.paused_reason = False, reason
        self.tracker.paused = reason
        if self.stream:
            await self.stream.set_symbols([])
        self.tracker.set_stream_state(StreamState.IDLE, f"Monitoring paused: {reason}")
        self.tracker.poll_failed(f"Monitoring paused: {reason}")
        self._event("warning", "monitoring", f"Market monitoring paused ({reason}). Nothing is being watched.")
        self.broadcaster.publish({"type": "connection", "data": self.status()})

    async def resume(self) -> None:
        self.monitoring_enabled, self.paused_reason = True, None
        self.tracker.paused = None
        self.tracker.poll_error = None
        await self.refresh_symbols()
        self._event("info", "monitoring", "Market monitoring resumed.")
        await self.poll_once()
        self.broadcaster.publish({"type": "connection", "data": self.status()})

    async def _feed_info_loop(self) -> None:
        """Slowly learn which symbols Yahoo serves in real time vs delayed (refreshed every 12h)."""
        while True:
            for sym in self.monitored_symbols():
                fi = self.tracker.feed_info(sym)
                if fi and fi.checked_at and datetime.now(timezone.utc) - fi.checked_at < timedelta(hours=12):
                    continue
                try:
                    self.tracker.set_feed_info(await self.provider.get_feed_info(sym))
                except SymbolNotFound:
                    self._unknown.add(sym)
                    self._event("warning", "market_data", f"{sym}: provider has no quote for this symbol; it is not monitored")
                    await self.refresh_symbols()
                except ProviderError as e:
                    log.info("feed info for %s unavailable: %s", sym, e)
                await asyncio.sleep(2)
            await asyncio.sleep(30)

    # ---------------- heartbeat / persistence ----------------

    async def _heartbeat(self) -> None:
        import time as _t
        last_wall, last_mono = _t.time(), _t.monotonic()
        while True:
            await asyncio.sleep(5)
            wall, mono = _t.time(), _t.monotonic()
            gap = (wall - last_wall) - 5
            # Sleep/hibernate: wall clock jumps while this loop wasn't running.
            if gap > 30 or (mono - last_mono) > 35:
                mins = max(gap, mono - last_mono - 5) / 60
                ev = {"at": datetime.now(timezone.utc).isoformat(), "minutes": round(mins, 1)}
                self.sleep_events.append(ev)
                self._event("warning", "monitoring", f"The computer was asleep or the app was suspended for ~{mins:.0f} min. "
                                                     "Nothing was monitored during that time; data is being refreshed now.")
                self.broadcaster.publish({"type": "system", "data": {"kind": "resumed_from_sleep", **ev}})
                if self.monitoring_enabled:
                    await self.poll_once()
            last_wall, last_mono = wall, mono
            changed = {}
            for sym in self.monitored_symbols():
                lab = self.label(sym)
                if self._last_status.get(sym) != lab.status.value:
                    self._last_status[sym] = lab.status.value
                    changed[sym] = lab.model_dump(mode="json")
            if changed:
                self.broadcaster.publish({"type": "freshness", "data": changed})

    async def _bar_writer(self) -> None:
        while True:
            await asyncio.sleep(10)
            await self._flush_bars()

    async def _flush_bars(self) -> None:
        if not self._pending_bars:
            return
        bars, self._pending_bars = self._pending_bars, []
        try:
            await asyncio.to_thread(self._upsert_bars, bars)
        except Exception:
            log.exception("failed to persist %d bars", len(bars))

    def _upsert_bars(self, bars: list[Bar]) -> None:
        if not bars:
            return
        rows = [dict(symbol=b.symbol, timeframe=b.timeframe, ts=b.ts, open=b.open, high=b.high, low=b.low, close=b.close,
                     volume=b.volume, vwap=b.vwap, trade_count=b.trade_count, provider=b.provider, source=b.source) for b in bars]
        upd = ("open", "high", "low", "close", "volume", "vwap", "trade_count", "source")
        with self.db.session() as s:
            if self.db.engine.dialect.name == "sqlite":
                ins = sqlite_insert
            else:  # PostgreSQL
                from sqlalchemy.dialects.postgresql import insert as ins
            for i in range(0, len(rows), 500):
                stmt = ins(BarRecord).values(rows[i:i + 500])
                s.execute(stmt.on_conflict_do_update(index_elements=["symbol", "timeframe", "ts", "provider"],
                                                     set_={k: stmt.excluded[k] for k in upd}))

    # ---------------- queries ----------------

    def label(self, symbol: str) -> LabeledValue:
        return self.tracker.label(symbol, self.clock.session_at().session)

    def signals_allowed(self, symbol: str) -> tuple[bool, str, str | None]:
        return self.tracker.signals_allowed(symbol, self.clock.session_at().session)

    def status(self) -> dict:
        sess = self.clock.session_at()
        healthy, why = self.tracker.provider_health()
        return {
            "monitoring_enabled": self.monitoring_enabled,
            "paused_reason": self.paused_reason,
            "last_sleep": self.sleep_events[-1] if self.sleep_events else None,
            "provider": self.provider.info.model_dump(),
            "live_mode": self.settings.live_mode,
            "healthy": healthy,
            "health_reason": why,
            "stream": {"enabled": self.streaming_enabled, "state": self.tracker.stream_state.value,
                       "reason": self.tracker.stream_reason, "reconnects": self.stream.reconnects if self.stream else 0},
            "polling": {"interval_seconds": self.settings.poll_interval_seconds, "polls": self.polls,
                        "last_ok": self.tracker.last_poll_ok.isoformat() if self.tracker.last_poll_ok else None,
                        "error": self.tracker.poll_error},
            "monitored_symbols": self.monitored_symbols(),
            "not_monitored_over_limit": self.over_limit(),
            "unknown_symbols": sorted(self._unknown),
            "market": sess.to_dict(),
        }

    def live_view(self) -> list[dict]:
        out = []
        for sym in self.monitored_symbols():
            t = self.tracker.latest(sym)
            ok, why, min_tf = self.signals_allowed(sym)
            fi = self.tracker.feed_info(sym)
            out.append({
                "symbol": sym,
                "last": t.model_dump(mode="json") if t else None,
                "label": self.label(sym).model_dump(mode="json"),
                "feed_info": fi.model_dump(mode="json") if fi else None,
                "signals": {"allowed": ok, "reason": why, "fastest_timeframe": min_tf},
            })
        return out

    async def quote(self, symbol: str) -> dict:
        """Latest known price for any symbol; polls on demand if it isn't monitored."""
        if self.tracker.latest(symbol) is None:
            await self.poll_once([symbol])
        t = self.tracker.latest(symbol)
        fi = self.tracker.feed_info(symbol)
        return {"symbol": symbol, "last": t.model_dump(mode="json") if t else None,
                "label": self.label(symbol).model_dump(mode="json"), "feed_info": fi.model_dump(mode="json") if fi else None}

    async def bars(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime | None = None):
        bars, notes = await self.provider.get_bars(symbol, timeframe, start, end)
        await asyncio.to_thread(self._upsert_bars, bars)
        label = LabeledValue(status=DataStatus.HISTORICAL, reason="Historical query; the newest bar may still be forming",
                             provider=self.provider.info.name, source=bars[0].source if bars else None)
        return bars, notes, label

    def cached_bars(self, symbol: str, timeframe: str, since: datetime) -> list[Bar]:
        with self.db.session() as s:
            rows = s.scalars(select(BarRecord).where(BarRecord.symbol == symbol.upper(), BarRecord.timeframe == timeframe,
                                                     BarRecord.ts >= since).order_by(BarRecord.ts)).all()
            return [Bar(symbol=r.symbol, timeframe=r.timeframe, ts=r.ts, open=r.open, high=r.high, low=r.low, close=r.close,
                        volume=r.volume, vwap=r.vwap, trade_count=r.trade_count, provider=r.provider, source=r.source)
                    for r in rows]

    def _event(self, level: str, category: str, message: str) -> None:
        getattr(log, {"error": "error", "warning": "warning"}.get(level, "info"))(message)
        try:
            with self.db.session() as s:
                s.add(AppEvent(level=level, category=category, message=message[:2000]))
        except Exception:
            log.exception("could not record app event")
        self.broadcaster.publish({"type": "event", "data": {"level": level, "category": category, "message": message,
                                                            "ts": datetime.now(timezone.utc).isoformat()}})
