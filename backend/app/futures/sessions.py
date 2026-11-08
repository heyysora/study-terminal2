"""CME Globex sessions for futures, in exchange time (America/Chicago, so daylight saving is handled by zoneinfo).

A futures "trade date" starts the evening before: the session that opens Sunday 17:00 CT is Monday's
session. Bars at 18:00 CT on Tuesday belong to Wednesday. Every level that says "previous day" must use
trade dates, not calendar dates, or the overnight session gets glued to the wrong day.

Holidays and early halts come from exchange_calendars (CMES / CBOT / NYMEX / COMEX). That package models
the session open and holiday early closes but not the daily 16:00-17:00 CT maintenance break, so the
product's normal close (16:00 CT) is applied on top. Holiday halt times in exchange_calendars can differ by
a few minutes from CME's published holiday schedule; the UI says so and points to CME's calendar.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache

from .contracts import CT, ProductSpec, parse_hhmm

log = logging.getLogger(__name__)
SRC_HOLIDAYS = "https://www.cmegroup.com/trading-hours.html"


@dataclass(frozen=True)
class SessionWindow:
    trade_date: date
    open: datetime          # Globex open, the evening before
    close: datetime         # normal or holiday close
    rth_start: datetime | None
    rth_end: datetime | None
    early_close: bool

    def contains(self, ts: datetime) -> bool:
        return self.open <= ts < self.close

    def to_dict(self) -> dict:
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"trade_date": self.trade_date.isoformat(), "open": iso(self.open), "close": iso(self.close),
                "rth_start": iso(self.rth_start), "rth_end": iso(self.rth_end), "early_close": self.early_close}


@lru_cache(maxsize=8)
def _schedule(calendar: str) -> dict[date, tuple[datetime, datetime]]:
    try:
        import exchange_calendars as xc

        cal = xc.get_calendar(calendar)
        out = {}
        for s, row in cal.schedule.iterrows():
            out[s.date()] = (row["open"].to_pydatetime().astimezone(CT), row["close"].to_pydatetime().astimezone(CT))
        return out
    except Exception:  # pragma: no cover
        log.exception("futures calendar %s unavailable", calendar)
        return {}


class FuturesClock:
    """Session math for one product. Pure functions of time; no network."""

    def __init__(self, spec: ProductSpec, rth: tuple[str, str] | None = None):
        self.spec = spec
        self.rth_start = parse_hhmm(rth[0] if rth else spec.rth_start_ct)
        self.rth_end = parse_hhmm(rth[1] if rth else spec.rth_end_ct)
        self.g_open = parse_hhmm(spec.globex_open_ct)
        self.g_close = parse_hhmm(spec.globex_close_ct)
        self.sched = _schedule(spec.calendar)
        self.coverage = (min(self.sched), max(self.sched)) if self.sched else None

    @property
    def calendar_source(self) -> str:
        if not self.coverage:
            return "weekday rule only (holiday calendar unavailable)"
        return f"exchange_calendars {self.spec.calendar} (local), covers to {self.coverage[1].isoformat()}"

    def window(self, d: date) -> SessionWindow | None:
        """The session for trade date d, or None if the exchange is closed that trade date."""
        if self.sched and self.coverage and self.coverage[0] <= d <= self.coverage[1]:
            if d not in self.sched:
                return None
            cal_open, cal_close = self.sched[d]
            normal_close = datetime.combine(d, self.g_close, tzinfo=CT)
            close = min(cal_close, normal_close)
            early = cal_close < normal_close
            opn = cal_open
        else:
            if d.weekday() >= 5:
                return None
            prev = d - timedelta(days=3 if d.weekday() == 0 else 1)
            opn = datetime.combine(prev, self.g_open, tzinfo=CT)
            close = datetime.combine(d, self.g_close, tzinfo=CT)
            early = False
        rs = datetime.combine(d, self.rth_start, tzinfo=CT)
        re_ = min(datetime.combine(d, self.rth_end, tzinfo=CT), close)
        if rs >= close:
            rs = re_ = None
        return SessionWindow(d, opn, close, rs, re_, early)

    def trade_date_of(self, ts: datetime) -> date | None:
        """Trade date a timestamp belongs to; None during the daily break, weekends and holidays."""
        w = self.window_at(ts)
        return w.trade_date if w else None

    def window_at(self, ts: datetime) -> SessionWindow | None:
        t = ts.astimezone(CT)
        for d in (t.date(), t.date() + timedelta(days=1), t.date() + timedelta(days=3)):
            w = self.window(d)
            if w and w.contains(t):
                return w
        return None

    def next_window(self, ts: datetime) -> SessionWindow | None:
        t = ts.astimezone(CT)
        for i in range(0, 12):
            w = self.window(t.date() + timedelta(days=i))
            if w and w.close > t:
                return w
        return None

    def prev_window(self, d: date) -> SessionWindow | None:
        for i in range(1, 12):
            w = self.window(d - timedelta(days=i))
            if w:
                return w
        return None

    def state(self, ts: datetime | None = None) -> dict:
        ts = ts or datetime.now(timezone.utc)
        t = ts.astimezone(CT)
        w = self.window_at(t)
        if not w:
            nw = self.next_window(t)
            return {"state": "closed", "label": "Closed", "trade_date": None, "now_ct": t.isoformat(),
                    "reason": "Daily maintenance break (16:00-17:00 CT)" if t.weekday() < 5 and t.time() >= self.g_close and t.time() < self.g_open
                    else "Weekend or exchange holiday",
                    "next_open": nw.open.isoformat() if nw else None, "window": None, "calendar_source": self.calendar_source}
        if w.rth_start and w.rth_start <= t < w.rth_end:
            st, label = "rth", "Regular hours (RTH)"
        elif w.rth_start and t < w.rth_start:
            st, label = "overnight", "Overnight / Globex (before RTH)"
        else:
            st, label = "post", "After RTH (Globex)"
        return {"state": st, "label": label, "trade_date": w.trade_date.isoformat(), "now_ct": t.isoformat(),
                "minutes_to_close": round((w.close - t).total_seconds() / 60, 1),
                "minutes_to_rth": round((w.rth_start - t).total_seconds() / 60, 1) if w.rth_start and t < w.rth_start else None,
                "early_close": w.early_close, "window": w.to_dict(), "calendar_source": self.calendar_source,
                "holiday_note": ("Holiday hours come from exchange_calendars and can differ by minutes from CME's published "
                                 f"schedule ({SRC_HOLIDAYS})." if w.early_close else None)}

    def is_rth(self, ts: datetime) -> bool:
        w = self.window_at(ts)
        return bool(w and w.rth_start and w.rth_start <= ts.astimezone(CT) < w.rth_end)


def ct_time(ts: datetime) -> time:
    return ts.astimezone(CT).time()
