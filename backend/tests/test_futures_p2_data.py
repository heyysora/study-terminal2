"""Futures data reliability: validation, missing candles, backoff with labeled cache, downtime gaps, platform default."""
from datetime import datetime, timedelta, timezone


from app.futures import contracts as fc
from app.futures.data import FuturesData
from app.futures.feed import DowntimeTracker, SourceHealth, validate_bars
from app.futures.sessions import FuturesClock
from app.market_data.types import Bar, Timeframe

ES = fc.get("ES")
CLK = FuturesClock(ES)
T0 = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)   # Tue 09:00 CT


def b(ts, o=6000, h=6001, lo=5999, c=6000, v=10):
    return {"ts": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v}


def test_validate_drops_bad_bars_and_reports():
    bars = [b(T0), b(T0 + timedelta(minutes=2)), b(T0 + timedelta(minutes=1)), b(T0 + timedelta(minutes=2), c=6000.5),
            b(T0 + timedelta(minutes=3), h=5998), b(T0 + timedelta(minutes=4), o=-1), b(T0 + timedelta(hours=5)),
            b(T0 + timedelta(minutes=5), c=6000.1)]
    clean, rep = validate_bars(bars, 60, ES, CLK, now=T0 + timedelta(minutes=10))
    assert [x["ts"] for x in clean] == [T0, T0 + timedelta(minutes=1), T0 + timedelta(minutes=2), T0 + timedelta(minutes=5)]
    assert clean[2]["close"] == 6000.5                       # newest duplicate kept
    assert rep["duplicates"] == 1 and rep["impossible"] == 2 and rep["future"] == 1 and rep["out_of_order"] == 2
    assert rep["off_tick"] == 1 and not rep["ok"]   # 6000.1 is off the 0.25 grid; 6000.5 is on it


def test_missing_candles_counted_per_session():
    bars = [b(T0 + timedelta(minutes=i)) for i in range(30) if i not in (5, 6, 7)]
    _, rep = validate_bars(bars, 60, ES, CLK, now=T0 + timedelta(minutes=30))
    s = rep["missing_by_session"]["2026-11-10"]
    assert s["expected"] == 30 and s["missing"] == 3


def test_backoff_doubles_and_resets():
    h = SourceHealth("x")
    h.fail("boom")
    first = h.next_retry
    h.fail("boom")
    assert h.backing_off and h.next_retry > first and h.failures == 2
    h.ok()
    assert not h.backing_off and h.failures == 0 and h.last_success_wall


class _Store(dict):
    def get(self, k, d=None):
        return super().get(k, d)


class _FlakyYahoo:
    def __init__(self):
        self.fail = False

    async def get_feed_info(self, symbol):
        from app.market_data.types import SymbolFeedInfo
        return SymbolFeedInfo(symbol=symbol, provider="yahoo", delay_minutes=10)

    async def get_bars(self, symbol, tf, start, end=None):
        if self.fail:
            raise RuntimeError("Yahoo is down")
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        return [Bar(symbol=symbol, timeframe=tf.value, ts=now - timedelta(minutes=15 - i), open=6000, high=6001, low=5999, close=6000,
                    volume=5, provider="yahoo", source="t") for i in range(5)], []


async def test_failure_serves_cache_labeled_cached_never_live():
    y = _FlakyYahoo()
    d = FuturesData(y, _Store())
    c = fc.Contract("ES", 2026, 12)
    bars, lab, _ = await d.bars(c, Timeframe.M1, CLK, days=1)
    assert bars and lab["validation"]["ok"]
    y.fail = True
    d._cache = {k: (v[0] - 999, *v[1:]) for k, v in d._cache.items()}   # expire the cache
    bars2, lab2, notes = await d.bars(c, Timeframe.M1, CLK, days=1)
    assert bars2 == bars and lab2["status"] == "cached" and "Not live" in lab2["reason"]
    assert lab2["health"]["consecutive_failures"] == 1


async def test_failure_without_cache_is_unavailable():
    y = _FlakyYahoo()
    y.fail = True
    d = FuturesData(y, _Store())
    bars, lab, _ = await d.bars(fc.Contract("ES", 2026, 12), Timeframe.M1, CLK)
    assert bars == [] and lab["status"] == "unavailable"


async def test_cache_key_includes_lookback():
    d = FuturesData(_FlakyYahoo(), _Store())
    c = fc.Contract("ES", 2026, 12)
    await d.bars(c, Timeframe.M1, CLK, days=1)
    await d.bars(c, Timeframe.M1, CLK, days=3)
    assert len(d._cache) == 2


def test_downtime_tracker_reports_sleep_gaps():
    t = DowntimeTracker(20)
    assert t.tick(T0) is None and t.tick(T0 + timedelta(seconds=21)) is None
    gap = t.tick(T0 + timedelta(minutes=45))
    assert gap and gap["seconds"] == 2679 and len(t.gaps) == 1


def test_topstepx_is_default_platform_in_futures_mode(settings, db):
    from app.screen.service import ScreenService
    from app.settings.store import SettingsStore

    store = SettingsStore(db)
    s = ScreenService(None, None, store, None)
    assert s.platform() == "auto"
    store.update({"app.market_mode": "futures"})
    assert s.platform() == "topstepx"
    store.update({"futures.platform": "tradingview"})          # persistent per-mode choice
    assert s.platform() == "tradingview"
    store.update({"app.market_mode": "equities"})
    assert s.platform() == "auto"
