"""Decides each symbol's DataStatus. This is the only code allowed to label data.

Rules, in order:
  no data at all                      -> UNAVAILABLE
  market closed                       -> HISTORICAL
  provider says symbol is delayed     -> DELAYED
  newest data older than the window   -> STALE
  fresh tick from a connected stream  -> REALTIME only if the provider guarantees it,
                                         otherwise NEAR_REALTIME
  fresh data from polling only        -> POLLING (never called live)

The same object gates trading signals:
  REALTIME / NEAR_REALTIME -> signals on any timeframe
  POLLING                  -> signals only on 5-minute or slower setups (data can lag ~1-2 min)
  anything else            -> no new signals
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..core.market_clock import ET, Session
from .providers.base import StreamState
from .types import DataStatus, LabeledValue, ProviderInfo, SymbolFeedInfo, Tick

VOLUME_NOTE = ("Approximate: Yahoo volume comes from a partial source, and extended-hours "
               "1-minute volume is reported as 0.")


@dataclass
class _SymbolState:
    last_stream: Tick | None = None
    last_poll: Tick | None = None
    feed: SymbolFeedInfo | None = None

    @property
    def latest(self) -> Tick | None:
        ticks = [t for t in (self.last_stream, self.last_poll) if t]
        return max(ticks, key=lambda t: t.ts) if ticks else None


@dataclass
class FreshnessTracker:
    provider: ProviderInfo
    poll_interval_s: float = 30.0
    regular_stale_s: float = 120.0
    extended_stale_s: float = 900.0
    streaming_enabled: bool = True
    stream_state: StreamState = StreamState.IDLE
    stream_reason: str = "not started"
    poll_error: str | None = None
    last_poll_ok: datetime | None = None
    paused: str | None = None
    _symbols: dict[str, _SymbolState] = field(default_factory=dict)

    # ---------------- inputs ----------------

    def _s(self, symbol: str) -> _SymbolState:
        return self._symbols.setdefault(symbol, _SymbolState())

    def on_tick(self, tick: Tick) -> None:
        st = self._s(tick.symbol)
        if tick.source.endswith("stream"):
            if st.last_stream is None or tick.ts >= st.last_stream.ts:
                st.last_stream = tick
        elif st.last_poll is None or tick.ts >= st.last_poll.ts:
            st.last_poll = tick

    def set_feed_info(self, info: SymbolFeedInfo) -> None:
        self._s(info.symbol).feed = info

    def feed_info(self, symbol: str) -> SymbolFeedInfo | None:
        st = self._symbols.get(symbol)
        return st.feed if st else None

    def latest(self, symbol: str) -> Tick | None:
        st = self._symbols.get(symbol)
        return st.latest if st else None

    def forget(self, symbol: str) -> None:
        self._symbols.pop(symbol, None)

    def set_stream_state(self, state: StreamState, reason: str) -> None:
        self.stream_state, self.stream_reason = state, reason

    def poll_succeeded(self, at: datetime | None = None) -> None:
        self.poll_error, self.last_poll_ok = None, at or datetime.now(timezone.utc)

    def poll_failed(self, reason: str) -> None:
        self.poll_error = reason

    # ---------------- outputs ----------------

    def _limit(self, session: Session) -> float:
        return self.regular_stale_s if session == Session.REGULAR else self.extended_stale_s

    @property
    def stream_connected(self) -> bool:
        return self.streaming_enabled and self.stream_state == StreamState.CONNECTED

    def provider_health(self) -> tuple[bool, str]:
        if self.stream_connected:
            return True, "Streaming socket connected"
        if self.poll_error:
            return False, f"Polling failing: {self.poll_error}"
        if self.last_poll_ok and datetime.now(timezone.utc) - self.last_poll_ok < timedelta(seconds=self.poll_interval_s * 3):
            return True, "Polling OK" + ("" if not self.streaming_enabled else f" (stream: {self.stream_reason})")
        return False, f"No successful update yet (stream: {self.stream_reason})"

    def label(self, symbol: str, session: Session, now: datetime | None = None) -> LabeledValue:
        now = now or datetime.now(timezone.utc)
        st = self._symbols.get(symbol)
        latest = st.latest if st else None
        age = (now - latest.ts).total_seconds() if latest else None

        def lv(status: DataStatus, reason: str, source: str | None = None) -> LabeledValue:
            return LabeledValue(status=status, reason=reason, provider=self.provider.name, source=source,
                                age_seconds=round(age, 1) if age is not None else None, volume_note=VOLUME_NOTE)

        if self.paused:
            return lv(DataStatus.UNAVAILABLE, f"Monitoring paused ({self.paused}) - prices are not being watched")
        if latest is None:
            ok, why = self.provider_health()
            return lv(DataStatus.UNAVAILABLE, "No data received for this symbol yet" if ok else f"No data: {why}")
        if session == Session.CLOSED:
            return lv(DataStatus.HISTORICAL, f"Market closed; last value from {latest.ts.astimezone(ET):%a %m-%d %H:%M} ET", latest.source)
        feed = st.feed
        if feed and feed.realtime_price is False and (feed.delay_minutes or 0) > 0:
            return lv(DataStatus.DELAYED, f"{self.provider.display_name} marks {symbol} as delayed {feed.delay_minutes} min", latest.source)

        limit = self._limit(session)
        stream_tick = st.last_stream
        if stream_tick and self.stream_connected:
            s_age = (now - stream_tick.ts).total_seconds()
            if s_age <= limit:
                if self.provider.guaranteed_realtime and feed and feed.realtime_price:
                    return lv(DataStatus.REALTIME, f"Licensed real-time stream; last tick {s_age:.0f}s ago", stream_tick.source)
                return lv(DataStatus.NEAR_REALTIME,
                          f"Unofficial stream, not guaranteed real-time; last tick {s_age:.0f}s ago", stream_tick.source)

        if age is not None and age > limit:
            hint = "" if self.stream_connected else f" Stream: {self.stream_reason}."
            return lv(DataStatus.STALE, f"Newest data is {age:.0f}s old (limit {limit:.0f}s in {session.value}); "
                                        f"thinly traded symbols can go quiet.{hint}", latest.source)
        return lv(DataStatus.POLLING, f"Polled 1-minute bars every {self.poll_interval_s:.0f}s; can lag up to "
                                      f"~{self.poll_interval_s + 60:.0f}s. Not a live feed.", latest.source)

    def signals_allowed(self, symbol: str, session: Session, now: datetime | None = None) -> tuple[bool, str, str | None]:
        """(allowed, reason, fastest timeframe allowed)."""
        lab = self.label(symbol, session, now)
        if lab.status in (DataStatus.REALTIME, DataStatus.NEAR_REALTIME):
            return True, lab.reason, "1Min"
        if lab.status == DataStatus.POLLING:
            return True, "Polled data: only 5-minute or slower setups are evaluated", "5Min"
        return False, f"{lab.status.value}: {lab.reason}", None
