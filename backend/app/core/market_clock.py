"""US equity market sessions.

Primary source: the `exchange_calendars` package's NYSE calendar, computed locally
(no network, no account). It knows holidays and early closes about a year ahead.
Outside its range, a weekday-only fallback is used and every SessionInfo says so
in `calendar_source`, so the UI can show the caveat instead of silently being
wrong on a holiday.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")  # Windows needs the `tzdata` package for this

PREMARKET_OPEN = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
AFTER_HOURS_CLOSE = time(20, 0)
EARLY_CLOSE_AFTER_HOURS_END = time(17, 0)


class Session(str, Enum):
    PREMARKET = "premarket"
    REGULAR = "regular"
    AFTER_HOURS = "after_hours"
    CLOSED = "closed"


@dataclass(frozen=True)
class TradingDay:
    day: date
    regular_open: time = REGULAR_OPEN
    regular_close: time = REGULAR_CLOSE
    session_open: time = PREMARKET_OPEN
    session_close: time = AFTER_HOURS_CLOSE

    @property
    def early_close(self) -> bool:
        return self.regular_close < REGULAR_CLOSE


@dataclass(frozen=True)
class SessionInfo:
    session: Session
    now_et: datetime
    is_trading_day: bool
    regular_open_et: datetime | None
    regular_close_et: datetime | None
    early_close: bool
    next_regular_open_et: datetime | None
    calendar_source: str

    def to_dict(self) -> dict:
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {
            "session": self.session.value,
            "now_et": iso(self.now_et),
            "is_trading_day": self.is_trading_day,
            "regular_open_et": iso(self.regular_open_et),
            "regular_close_et": iso(self.regular_close_et),
            "early_close": self.early_close,
            "next_regular_open_et": iso(self.next_regular_open_et),
            "calendar_source": self.calendar_source,
        }


class MarketClock:
    FALLBACK = "fallback-weekday-rule (holidays unknown)"
    EXCHANGE = "exchange-calendar (NYSE, local)"

    def __init__(self, load: bool = True) -> None:
        self._days: dict[date, TradingDay] = {}
        self._covered: tuple[date, date] | None = None
        if load:
            self.load_exchange_calendar()

    def load_exchange_calendar(self) -> None:
        try:
            import exchange_calendars as xc
            import pandas as pd

            cal = xc.get_calendar("XNYS")
            today = datetime.now(timezone.utc).date()
            start = cal.first_session.date()  # full history: backtests need old sessions too
            end = cal.last_session.date()
            days = {}
            for s in cal.sessions_in_range(pd.Timestamp(start), pd.Timestamp(end)):
                o = cal.session_open(s).tz_convert(ET).time()
                c = cal.session_close(s).tz_convert(ET).time()
                td = TradingDay(day=s.date(), regular_open=o, regular_close=c)
                if td.early_close:
                    td = TradingDay(day=s.date(), regular_open=o, regular_close=c, session_close=EARLY_CLOSE_AFTER_HOURS_END)
                days[s.date()] = td
            self._days, self._covered = days, (start, end)
        except Exception:  # pragma: no cover - only if the package is missing/broken
            log.exception("exchange calendar unavailable; using weekday fallback")
            self._days, self._covered = {}, None

    def load_days(self, days: list[TradingDay], start: date, end: date) -> None:
        """Explicit calendar (tests / future providers). Days absent in [start, end] are closed."""
        self._days = {d.day: d for d in days}
        self._covered = (start, end)

    @property
    def has_calendar(self) -> bool:
        return self._covered is not None

    def _covers(self, d: date) -> bool:
        return self._covered is not None and self._covered[0] <= d <= self._covered[1]

    def trading_day(self, d: date) -> tuple[TradingDay | None, str]:
        if self._covers(d):
            return self._days.get(d), self.EXCHANGE
        if d.weekday() < 5:
            return TradingDay(day=d), self.FALLBACK
        return None, self.FALLBACK

    def session_at(self, now: datetime | None = None) -> SessionInfo:
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        now_et = now.astimezone(ET)
        td, source = self.trading_day(now_et.date())

        session = Session.CLOSED
        r_open = r_close = None
        if td:
            at = lambda t: datetime.combine(td.day, t, tzinfo=ET)  # noqa: E731
            r_open, r_close = at(td.regular_open), at(td.regular_close)
            s_open, s_close = at(td.session_open), at(td.session_close)
            if s_open <= now_et < r_open:
                session = Session.PREMARKET
            elif r_open <= now_et < r_close:
                session = Session.REGULAR
            elif r_close <= now_et < s_close:
                session = Session.AFTER_HOURS

        next_open, next_source = self._next_regular_open(now_et)
        if next_source == self.FALLBACK:
            source = self.FALLBACK
        return SessionInfo(session, now_et, td is not None, r_open, r_close, bool(td and td.early_close), next_open, source)

    def session_of(self, ts: datetime) -> Session:
        return self.session_at(ts).session

    def _next_regular_open(self, now_et: datetime) -> tuple[datetime | None, str]:
        source = self.EXCHANGE
        for i in range(0, 15):
            d = now_et.date() + timedelta(days=i)
            td, src = self.trading_day(d)
            if src == self.FALLBACK:
                source = self.FALLBACK
            if td:
                o = datetime.combine(d, td.regular_open, tzinfo=ET)
                if o > now_et:
                    return o, source
        return None, source
