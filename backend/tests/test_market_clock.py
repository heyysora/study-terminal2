from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from app.core.market_clock import MarketClock, Session, TradingDay

ET = ZoneInfo("America/New_York")


def et(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=ET).astimezone(timezone.utc)


def test_exchange_calendar_normal_day():
    c = MarketClock()
    assert c.session_at(et(2026, 11, 24, 3, 59)).session == Session.CLOSED
    assert c.session_at(et(2026, 11, 24, 4, 0)).session == Session.PREMARKET
    assert c.session_at(et(2026, 11, 24, 9, 30)).session == Session.REGULAR
    assert c.session_at(et(2026, 11, 24, 15, 59)).session == Session.REGULAR
    assert c.session_at(et(2026, 11, 24, 16, 0)).session == Session.AFTER_HOURS
    assert c.session_at(et(2026, 11, 24, 20, 0)).session == Session.CLOSED


def test_holiday_and_next_open_from_local_calendar():
    c = MarketClock()
    info = c.session_at(et(2026, 11, 26, 11, 0))  # Thanksgiving
    assert info.session == Session.CLOSED and not info.is_trading_day
    assert info.calendar_source == MarketClock.EXCHANGE
    assert info.next_regular_open_et == datetime(2026, 11, 27, 9, 30, tzinfo=ET)


def test_early_close_day_after_thanksgiving():
    c = MarketClock()
    info = c.session_at(et(2026, 11, 27, 13, 30))
    assert info.session == Session.AFTER_HOURS and info.early_close
    assert c.session_at(et(2026, 11, 27, 17, 30)).session == Session.CLOSED


def test_weekend():
    c = MarketClock()
    info = c.session_at(et(2026, 11, 28, 12, 0))
    assert info.session == Session.CLOSED
    assert info.next_regular_open_et == datetime(2026, 11, 30, 9, 30, tzinfo=ET)


def test_fallback_is_labeled():
    c = MarketClock(load=False)
    info = c.session_at(et(2026, 11, 26, 11, 0))  # holiday, but fallback doesn't know
    assert info.session == Session.REGULAR
    assert "holidays unknown" in info.calendar_source


def test_explicit_days():
    c = MarketClock(load=False)
    c.load_days([TradingDay(date(2030, 1, 2), regular_close=time(13, 0))], date(2030, 1, 1), date(2030, 1, 3))
    assert c.session_at(et(2030, 1, 1, 10, 0)).session == Session.CLOSED
    assert c.session_at(et(2030, 1, 2, 12, 0)).session == Session.REGULAR


def test_dst_boundary():
    c = MarketClock()
    assert c.session_at(datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc)).session == Session.REGULAR  # EST
    assert c.session_at(datetime(2026, 10, 30, 13, 30, tzinfo=timezone.utc)).session == Session.REGULAR  # EDT
    assert c.session_at(datetime(2026, 10, 30, 13, 29, tzinfo=timezone.utc)).session == Session.PREMARKET
