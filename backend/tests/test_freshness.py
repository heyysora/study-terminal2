from datetime import datetime, timedelta, timezone

from app.core.market_clock import Session
from app.market_data.freshness import FreshnessTracker
from app.market_data.providers.base import StreamState
from app.market_data.types import DataStatus, ProviderInfo, SymbolFeedInfo, Tick

NOW = datetime(2026, 11, 9, 15, 0, tzinfo=timezone.utc)
YAHOO_LIKE = ProviderInfo(name="y", display_name="Y", supports_streaming=True, guaranteed_realtime=False)
LICENSED = ProviderInfo(name="lic", display_name="Licensed", supports_streaming=True, guaranteed_realtime=True)


def tick(sym="SPY", age=2.0, source="y-stream"):
    return Tick(symbol=sym, price=100, ts=NOW - timedelta(seconds=age), received_at=NOW, provider="y", source=source)


def tracker(info=YAHOO_LIKE, connected=True):
    t = FreshnessTracker(provider=info, poll_interval_s=30, regular_stale_s=120, extended_stale_s=900)
    if connected:
        t.set_stream_state(StreamState.CONNECTED, "ok")
    return t


def test_unofficial_stream_is_never_realtime():
    t = tracker()
    t.on_tick(tick())
    t.set_feed_info(SymbolFeedInfo(symbol="SPY", provider="y", realtime_price=True))
    lab = t.label("SPY", Session.REGULAR, NOW)
    assert lab.status == DataStatus.NEAR_REALTIME and "not guaranteed" in lab.reason


def test_licensed_realtime_provider_can_be_realtime():
    t = tracker(LICENSED)
    t.on_tick(tick())
    t.set_feed_info(SymbolFeedInfo(symbol="SPY", provider="lic", realtime_price=True))
    assert t.label("SPY", Session.REGULAR, NOW).status == DataStatus.REALTIME


def test_polled_data_is_labeled_polling_not_live():
    t = tracker(connected=False)
    t.on_tick(tick(age=50, source="y-poll"))
    lab = t.label("SPY", Session.REGULAR, NOW)
    assert lab.status == DataStatus.POLLING and "Not a live feed" in lab.reason
    ok, _, fastest = t.signals_allowed("SPY", Session.REGULAR, NOW)
    assert ok and fastest == "5Min"


def test_stream_down_falls_back_to_polling_label():
    t = tracker()
    t.on_tick(tick(age=5))
    t.on_tick(tick(age=30, source="y-poll"))
    t.set_stream_state(StreamState.DISCONNECTED, "lost")
    assert t.label("SPY", Session.REGULAR, NOW).status == DataStatus.POLLING


def test_delayed_symbol():
    t = tracker()
    t.on_tick(tick())
    t.set_feed_info(SymbolFeedInfo(symbol="SPY", provider="y", realtime_price=False, delay_minutes=15))
    assert t.label("SPY", Session.REGULAR, NOW).status == DataStatus.DELAYED
    assert t.signals_allowed("SPY", Session.REGULAR, NOW)[0] is False


def test_stale_and_extended_hours_tolerance():
    t = tracker()
    t.on_tick(tick(age=300))
    assert t.label("SPY", Session.REGULAR, NOW).status == DataStatus.STALE
    assert t.label("SPY", Session.PREMARKET, NOW).status == DataStatus.NEAR_REALTIME


def test_unavailable_and_closed():
    t = tracker()
    assert t.label("XYZ", Session.REGULAR, NOW).status == DataStatus.UNAVAILABLE
    t.on_tick(tick())
    assert t.label("SPY", Session.CLOSED, NOW).status == DataStatus.HISTORICAL
    assert t.signals_allowed("SPY", Session.CLOSED, NOW)[0] is False


def test_poll_failure_reported():
    t = tracker(connected=False)
    t.poll_failed("rate limited")
    lab = t.label("SPY", Session.REGULAR, NOW)
    assert lab.status == DataStatus.UNAVAILABLE and "rate limited" in lab.reason
