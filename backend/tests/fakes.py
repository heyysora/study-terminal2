"""Test doubles: a provider with a hand-driven stream, and an always-open market clock."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone

from app.core.market_clock import ET, MarketClock, TradingDay
from app.market_data.providers.base import MarketDataProvider, StreamState, SymbolNotFound, TickStream
from app.market_data.types import Bar, ProviderInfo, SymbolFeedInfo, Tick, Timeframe


def always_open_clock() -> MarketClock:
    c = MarketClock(load=False)
    today = datetime.now(ET).date()
    days = [TradingDay(today + timedelta(days=i), regular_open=time(0, 0), regular_close=time(23, 59, 59),
                       session_open=time(0, 0), session_close=time(23, 59, 59)) for i in range(-3, 4)]
    c.load_days(days, today - timedelta(days=3), today + timedelta(days=3))
    return c


class FakeStream(TickStream):
    def __init__(self, on_tick, on_state):
        self.on_tick, self.on_state = on_tick, on_state
        self.symbols: set[str] = set()
        self.state, self.state_reason = StreamState.IDLE, ""
        self._stop = asyncio.Event()

    async def set_symbols(self, symbols):
        self.symbols = set(symbols)

    async def run(self):
        self.state = StreamState.CONNECTED
        self.on_state(StreamState.CONNECTED, "fake connected")
        await self._stop.wait()

    async def stop(self):
        self._stop.set()

    def push(self, symbol: str, price: float, ts: datetime | None = None, bid=None, ask=None):
        now = datetime.now(timezone.utc)
        self.on_tick(Tick(symbol=symbol, price=price, ts=ts or now, received_at=now, provider="fake",
                          source="fake-stream", bid=bid, ask=ask))


class FakeProvider(MarketDataProvider):
    info = ProviderInfo(name="fake", display_name="Fake provider (tests)", supports_streaming=True)

    def __init__(self):
        self.stream: FakeStream | None = None
        self.recent: dict[str, list[Bar]] = {}
        self.history: dict[str, list[Bar]] = {}
        self.feed: dict[str, SymbolFeedInfo] = {}

    async def get_bars(self, symbol, timeframe, start, end=None):
        if symbol not in self.history:
            raise SymbolNotFound(symbol)
        return self.history[symbol], ["fake note"]

    async def get_recent_bars(self, symbols):
        return {s: self.recent[s] for s in symbols if s in self.recent}

    async def get_feed_info(self, symbol):
        if symbol in self.feed:
            return self.feed[symbol]
        return SymbolFeedInfo(symbol=symbol, provider="fake", realtime_price=True, delay_minutes=0,
                              checked_at=datetime.now(timezone.utc))

    def create_stream(self, on_tick, on_state):
        self.stream = FakeStream(on_tick, on_state)
        return self.stream


def bar(symbol: str, ts: datetime, o: float, h: float, lo: float, c: float, v: float = 1000, tf=Timeframe.M1) -> Bar:
    return Bar(symbol=symbol, timeframe=tf.value, ts=ts, open=o, high=h, low=lo, close=c, volume=v, provider="fake",
               source="fake-poll")
