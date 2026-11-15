"""Database models (SQLAlchemy 2.0). SQLite now; the same models work on PostgreSQL."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UTCDateTime(TypeDecorator):
    """Stores UTC, always returns timezone-aware UTC datetimes (SQLite drops tzinfo)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime passed to UTCDateTime column")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    symbols: Mapped[list["WatchlistSymbol"]] = relationship(
        back_populates="watchlist", cascade="all, delete-orphan", order_by="WatchlistSymbol.position"
    )


class WatchlistSymbol(Base):
    __tablename__ = "watchlist_symbols"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    watchlist: Mapped[Watchlist] = relationship(back_populates="symbols")


class BarRecord(Base):
    """OHLCV bar cache. `provider` is stored so bars from different sources are never mixed."""

    __tablename__ = "bars"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "ts", "provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8))
    ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)  # bar open time
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)
    vwap: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provider: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(32))  # e.g. "yahoo-history" | "yahoo-poll"


class AppEvent(Base):
    """Connection/system event log shown in the UI (disconnects, auth failures, stale data)."""

    __tablename__ = "app_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(8))
    category: Mapped[str] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)


class SettingRecord(Base):
    """User-editable settings persisted across restarts (JSON-encoded values)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


# ---------------- paper trading simulator ----------------

class FuturesStateRecord(Base):
    """Futures simulator state (JSON). id=1 is the practice account, id=2 the replay account, id=3 backtest evidence."""

    __tablename__ = "futures_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[str] = mapped_column(Text)


class FuturesFillRecord(Base):
    """Every futures simulator fill, kept permanently (the state blob only keeps recent ones)."""

    __tablename__ = "futures_fills"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account: Mapped[str] = mapped_column(String(16), index=True)   # practice | replay | sandbox
    ts: Mapped[str] = mapped_column(String(40), index=True)
    data: Mapped[str] = mapped_column(Text)


class FuturesDecisionRecord(Base):
    """One decision-pipeline result per (contract, setup, direction, bar). Re-evaluations of the same bar update it."""

    __tablename__ = "futures_decisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    contract: Mapped[str] = mapped_column(String(16), index=True)
    bar_time: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), index=True)
    mode: Mapped[str] = mapped_column(String(16))
    first_seen: Mapped[str] = mapped_column(String(40), index=True)
    last_seen: Mapped[str] = mapped_column(String(40))
    acted: Mapped[str | None] = mapped_column(String(64), nullable=True)   # order id when the automation acted on it
    data: Mapped[str] = mapped_column(Text)


class PaperStateRecord(Base):
    """Single row: account balances + open positions (JSON). Rewritten after every change."""

    __tablename__ = "paper_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class PaperOrderRecord(Base):
    __tablename__ = "paper_orders"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    data: Mapped[str] = mapped_column(Text)  # full order JSON


class PaperFillRecord(Base):
    __tablename__ = "paper_fills"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    order_id: Mapped[str] = mapped_column(String(16), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    data: Mapped[str] = mapped_column(Text)


# ---------------- backtests, calibration, alerts, learning, settings ----------------

class BacktestRunRecord(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(16))  # backtest | walk_forward | optimize
    summary: Mapped[str] = mapped_column(Text)     # JSON: config + metrics
    detail: Mapped[str] = mapped_column(Text)      # JSON: trades, equity, folds


class SetupStatRecord(Base):
    """Out-of-sample performance per setup/timeframe. Feeds signal confidence."""

    __tablename__ = "setup_stats"
    __table_args__ = (UniqueConstraint("setup", "timeframe"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    setup: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    data: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class AlertRecord(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    category: Mapped[str] = mapped_column(String(16))   # entry | position | market | system
    severity: Mapped[str] = mapped_column(String(8))    # info | low | medium | high
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    data: Mapped[str] = mapped_column(Text, default="{}")
    read: Mapped[int] = mapped_column(Integer, default=0)


class LearningProgressRecord(Base):
    __tablename__ = "learning_progress"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lesson_id: Mapped[str] = mapped_column(String(48), index=True)
    kind: Mapped[str] = mapped_column(String(16))   # completed | quiz
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    data: Mapped[str] = mapped_column(Text, default="{}")
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# ---------------- journal (Stage 11) ----------------

class SignalLogRecord(Base):
    """Every generated signal, logged when it first appears and whenever its action or state changes."""
    __tablename__ = "signal_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    signal_id: Mapped[str] = mapped_column(String(64), index=True)   # symbol|setup|timeframe
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    setup: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    timeframe: Mapped[str] = mapped_column(String(8))
    action: Mapped[str] = mapped_column(String(24), index=True)
    state: Mapped[str] = mapped_column(String(16))
    tradeable: Mapped[int] = mapped_column(Integer, default=0)
    evidence_tier: Mapped[str] = mapped_column(String(16), default="none")
    data: Mapped[str] = mapped_column(Text)   # compact signal snapshot (plan, confidence components, market, data label)


class JournalTradeRecord(Base):
    """Immutable snapshot of a closed paper round-trip trade. Survives a paper-account reset."""
    __tablename__ = "journal_trades"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)   # id of the trade's first fill
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    closed_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    data: Mapped[str] = mapped_column(Text)


class JournalNoteRecord(Base):
    """Your own notes, tags and plan verdict on a trade (open or closed)."""
    __tablename__ = "journal_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_key: Mapped[str] = mapped_column(String(32), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    kind: Mapped[str] = mapped_column(String(16), default="note")    # note | tags | followed_plan
    text: Mapped[str] = mapped_column(Text, default="")


class NewsItemRecord(Base):
    """Headlines and analyst actions seen by the app (kept so you can look back at what was known when)."""
    __tablename__ = "news_items"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    published: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    data: Mapped[str] = mapped_column(Text)


class MemePosition(Base):
    """Memecoin PRACTICE position (pretend money; never a wallet)."""

    __tablename__ = "meme_positions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128), default="")
    qty: Mapped[float] = mapped_column(Float)
    cost_usd: Mapped[float] = mapped_column(Float)          # what was paid in total, fees included
    stop_price: Mapped[float] = mapped_column(Float)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    url: Mapped[str] = mapped_column(String(256), default="")


class MemePlan(Base):
    """Exit plan for a memecoin PRACTICE position: take part of the profit at the target, then trail a stop under the highest price."""

    __tablename__ = "meme_plans"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    take_fraction: Mapped[float] = mapped_column(Float, default=1.0)      # share sold when the target is reached
    trail_pct: Mapped[float | None] = mapped_column(Float, nullable=True)  # stop follows this far under the highest price seen
    high_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    took_profit: Mapped[int] = mapped_column(Integer, default=0)


class MemeNote(Base):
    """What YOU wrote about a memecoin practice trade. The app never fills these in for you."""

    __tablename__ = "meme_notes"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    why: Mapped[str] = mapped_column(String(600), default="")             # why you bought
    lesson: Mapped[str] = mapped_column(String(600), default="")          # what you learned
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class MemeFill(Base):
    """Every memecoin practice buy and sell, with the modelled fee and price impact."""

    __tablename__ = "meme_fills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    token: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(4))           # buy | sell
    qty: Mapped[float] = mapped_column(Float)
    price_usd: Mapped[float] = mapped_column(Float)        # average fill price after price impact
    usd: Mapped[float] = mapped_column(Float)              # cash in (sell) or out (buy), before fees
    fee_usd: Mapped[float] = mapped_column(Float)
    impact_pct: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(16), default="you")   # you | stop | target
