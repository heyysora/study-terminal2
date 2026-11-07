"""Market data types shared by providers, the monitor, the paper simulator and the API."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DataStatus(str, Enum):
    """How much a number on screen can be trusted right now. Shown next to every price.

    REALTIME       Contractually real-time feed. No free provider in this app qualifies;
                   reserved for future paid/licensed providers.
    NEAR_REALTIME  Pushed by a streaming source and timestamps are fresh, but the source
                   is unofficial / not guaranteed (e.g. Yahoo's streaming socket).
    POLLING        Pulled on a timer from an endpoint built for history (e.g. Yahoo 1-min
                   bars). Lags by up to poll interval + bar length. Never called live.
    DELAYED        The source itself says the data is delayed (e.g. 15 minutes).
    HISTORICAL     A historical query, or the market is closed.
    STALE          Should be updating but hasn't been within the allowed window.
    UNAVAILABLE    No data: provider down, rate-limited, symbol unknown, or not loaded yet.
    """

    REALTIME = "realtime"
    NEAR_REALTIME = "near_realtime"
    POLLING = "polling"
    DELAYED = "delayed"
    HISTORICAL = "historical"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


# Statuses whose prices the paper simulator may fill against, and signals may use.
TRADABLE_STATUSES = {DataStatus.REALTIME, DataStatus.NEAR_REALTIME, DataStatus.POLLING}


class Timeframe(str, Enum):
    M1 = "1Min"
    M2 = "2Min"
    M5 = "5Min"
    M15 = "15Min"
    M30 = "30Min"
    H1 = "1Hour"
    H4 = "4Hour"
    D1 = "1Day"

    @property
    def seconds(self) -> int:
        return {"1Min": 60, "2Min": 120, "5Min": 300, "15Min": 900, "30Min": 1800,
                "1Hour": 3600, "4Hour": 14400, "1Day": 86400}[self.value]


class Bar(BaseModel):
    symbol: str
    timeframe: str
    ts: datetime  # bar open time, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    trade_count: int | None = None
    provider: str
    source: str  # e.g. "yahoo-history", "yahoo-poll"


class Tick(BaseModel):
    """A price update. `ts` is the time the source says the price happened;
    `received_at` is when this app got it. Freshness uses `ts`."""

    symbol: str
    price: float
    ts: datetime
    received_at: datetime
    provider: str
    source: str  # "yahoo-stream" | "yahoo-poll"
    day_volume: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    open: float | None = None
    prev_close: float | None = None
    change_pct: float | None = None
    bid: float | None = None
    ask: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    market_hours: str | None = None  # source's own session flag, if it sends one


class SymbolFeedInfo(BaseModel):
    """What the provider says about how timely a symbol's quotes are."""

    symbol: str
    provider: str
    realtime_price: bool | None = None  # None = unknown
    price_source: str | None = None      # e.g. "Nasdaq Real Time Price"
    delay_minutes: int | None = None
    quote_type: str | None = None
    exchange: str | None = None
    name: str | None = None
    checked_at: datetime | None = None
    note: str | None = None


class ProviderInfo(BaseModel):
    name: str
    display_name: str
    requires_api_key: bool = False
    supports_history: bool = True
    supports_polling: bool = True
    supports_streaming: bool = False
    guaranteed_realtime: bool = False
    history_limits: dict[str, str] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class LabeledValue(BaseModel):
    status: DataStatus
    reason: str
    provider: str
    source: str | None = None
    age_seconds: float | None = None
    volume_note: str | None = None
