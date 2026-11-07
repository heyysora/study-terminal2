"""The market data provider interface.

To add a provider (Finnhub, Polygon/Massive, Tiingo, a local CSV replay, ...):
  1. Subclass MarketDataProvider, fill in `info` honestly (especially
     `guaranteed_realtime` and `requires_api_key`).
  2. Implement get_bars / get_recent_bars / get_feed_info.
  3. If it can push ticks, return a TickStream from create_stream().
  4. Register it in providers/registry.py.
Nothing else in the app (monitor, signals, paper simulator, backtester) changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from enum import Enum

from ..types import Bar, ProviderInfo, SymbolFeedInfo, Tick, Timeframe


class ProviderError(Exception):
    pass


class ProviderRateLimited(ProviderError):
    """The source throttled us. The monitor backs off and labels data accordingly."""


class SymbolNotFound(ProviderError):
    pass


class StreamState(str, Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    FAILED = "failed"


TickHandler = Callable[[Tick], None]
StateHandler = Callable[[StreamState, str], None]


class TickStream(ABC):
    """A push feed of ticks. Implementations own reconnection."""

    state: StreamState = StreamState.IDLE
    state_reason: str = ""
    reconnects: int = 0

    @abstractmethod
    async def set_symbols(self, symbols: list[str]) -> None: ...

    @abstractmethod
    async def run(self) -> None:
        """Run until stop(); reconnect on failure."""

    @abstractmethod
    async def stop(self) -> None: ...


class MarketDataProvider(ABC):
    info: ProviderInfo

    @abstractmethod
    async def get_bars(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime | None = None) -> tuple[list[Bar], list[str]]:
        """Historical bars, oldest first. Returns (bars, notes) where notes explain any
        clamping the provider had to do (e.g. 1-minute history only goes back N days)."""

    @abstractmethod
    async def get_recent_bars(self, symbols: list[str]) -> dict[str, list[Bar]]:
        """Today's 1-minute bars (including extended hours) for polling-based monitoring."""

    @abstractmethod
    async def get_feed_info(self, symbol: str) -> SymbolFeedInfo:
        """How timely this symbol's quotes are according to the provider."""

    async def get_movers(self, kind: str, count: int = 25) -> list[dict]:
        """Market-wide lists for the scanner (e.g. day_gainers, most_actives). Optional.
        Each dict: symbol, price, change_pct, volume, avg_volume, market_cap, name, premarket_change_pct."""
        return []

    movers_kinds: tuple[str, ...] = ()

    def create_stream(self, on_tick: TickHandler, on_state: StateHandler) -> TickStream | None:
        return None

    async def aclose(self) -> None:
        return None
