"""Phase 2: validation, missing candles, cached fallback, freshness timestamps, feed-health alerts."""
from datetime import datetime, timedelta, timezone

import pytest

from app.analysis.service import AnalysisService
from app.core.market_clock import ET
from app.market_data.freshness import FreshnessTracker
from app.market_data.health import FeedHealthWatcher
from app.market_data.providers.base import ProviderError, StreamState
from app.market_data.types import DataStatus, ProviderInfo, Tick, Timeframe
from app.market_data.validation import validate_bars
from tests.fakes import FakeProvider, always_open_clock, bar
from tests.synth import intraday

D = datetime(2026, 11, 24, 10, 0, tzinfo=ET).astimezone(timezone.utc)


def mins(n):
    return D + timedelta(minutes=n)


def flat(n, px=100.0):
    return [bar("X", mins(i), px, px + 0.1, px - 0.1, px) for i in range(n)]


def test_impossible_bars_are_dropped_and_reported():
    bars = flat(10)
    bars[3] = bar("X", mins(3), 100, 99, 101, 100)            # high below low
    bars[5] = bar("X", mins(5), 0, 100.1, 99.9, 100)          # zero open
    bars[7] = bar("X", mins(7), 100, 100.1, 99.9, 104)        # close far above the high
    bars.append(bar("X", mins(9), 100, 100.2, 99.8, 100.1))   # duplicate timestamp: later copy wins
    clean, rep = validate_bars(bars, 60)
    assert len(clean) == 7
    reasons = " ".join(d["reason"] for d in rep.dropped)
    assert "high" in reasons and "zero" in reasons and "outside" in reasons and "duplicate" in reasons
    assert clean[-1].close == 100.1
    assert not rep.ok and "invalid" in rep.summary()


def test_rounding_noise_is_repaired_not_dropped():
    b = bar("X", mins(0), 100.02, 100.0, 99.0, 99.5)  # open 0.02% above the high
    clean, rep = validate_bars([b], 60)
    assert len(clean) == 1 and clean[0].high == 100.02 and rep.repaired == 1


def test_one_bar_spike_is_flagged_but_real_moves_are_not():
    bars = flat(30)
    bars[15] = bar("X", mins(15), 100, 112, 99.9, 100.05)  # 12% wick that instantly reverts
    _, rep = validate_bars(bars, 60)
    assert rep.suspect == [mins(15).isoformat()]
    # a genuine breakout that holds is not a "bad print"
    bars = flat(30)
    bars[15] = bar("X", mins(15), 100, 108, 99.9, 107.5)
    bars[16:] = [bar("X", mins(i), 107.5, 107.7, 107.3, 107.5) for i in range(16, 30)]
    _, rep = validate_bars(bars, 60)
    assert rep.suspect == []


def test_missing_candles_counted_in_regular_hours_only():
    bars = flat(30)
    del bars[10:13]                                           # 3 missing minutes mid-morning
    pre = [bar("X", D.replace(hour=12, minute=m), 100, 100.1, 99.9, 100) for m in (0, 7)]  # 07:00, 07:07 ET premarket
    _, rep = validate_bars(pre + bars, 60)
    assert rep.missing_candles == 3 and rep.gaps[0]["missing"] == 3
    assert rep.expected_candles == 30


async def test_failed_refresh_serves_labeled_cache_and_blocks_signals():
    prov = FakeProvider()
    prov.history["TSLA"] = intraday("TSLA", days=6, minutes=5)
    svc = AnalysisService(prov)
    ff = await svc.frame("TSLA", Timeframe.M5)
    assert svc.data_info(ff)["status"] == "historical" and ff.fetched_at and ff.quality is not None

    async def boom(*a, **k):
        raise ProviderError("HTTP 503 from Yahoo")
    prov.get_bars = boom
    svc._ttl = lambda tf: 0                                   # force a refresh attempt
    ff2 = await svc.frame("TSLA", Timeframe.M5)
    info = svc.data_info(ff2)
    assert ff2.served_from_cache and info["status"] == "cached" and "503" in info["reason"]
    # no cache at all -> the error surfaces instead of inventing data
    with pytest.raises(ProviderError):
        await svc.frame("NVDA", Timeframe.M5)


def test_labels_carry_source_and_timestamps():
    tr = FreshnessTracker(provider=ProviderInfo(name="fake", display_name="Fake"), streaming_enabled=False)
    now = datetime.now(timezone.utc)
    tr.on_tick(Tick(symbol="AAPL", price=1.0, ts=now - timedelta(seconds=20), received_at=now, provider="fake", source="fake-poll"))
    tr.poll_succeeded(now)
    from app.core.market_clock import Session
    lab = tr.label("AAPL", Session.REGULAR, now)
    assert lab.status == DataStatus.POLLING and lab.source == "fake-poll" and lab.provider == "fake"
    assert lab.data_time == now - timedelta(seconds=20) and lab.received_at == now and lab.age_seconds == 20


class _Alerts:
    def __init__(self):
        self.sent = []

    def emit(self, cat, sev, title, body, **kw):
        self.sent.append((sev, title))
        return True


class _Monitor:
    def __init__(self):
        self.clock = always_open_clock()
        self.monitoring_enabled = True
        self.streaming_enabled = True
        self.tracker = FreshnessTracker(provider=ProviderInfo(name="fake", display_name="Fake"))
        self.tracker.set_stream_state(StreamState.CONNECTED, "ok")
        self.tracker.poll_succeeded()

    def label(self, sym):
        return self.tracker.label(sym, self.clock.session_at().session)


def test_feed_health_alerts_after_a_minute_and_on_recovery(monkeypatch):
    import app.market_data.health as h
    t = [1000.0]
    monkeypatch.setattr(h.time, "monotonic", lambda: t[0])
    m, al = _Monitor(), _Alerts()
    w = FeedHealthWatcher(m, al, lambda: [{"symbol": "TSLA"}])
    m.tracker.on_tick(Tick(symbol="TSLA", price=1, ts=datetime.now(timezone.utc), received_at=datetime.now(timezone.utc),
                           provider="fake", source="fake-stream"))
    w.check()
    assert al.sent == []
    m.tracker.set_stream_state(StreamState.DISCONNECTED, "socket closed")
    w.check()
    t[0] += 30
    w.check()
    assert al.sent == []                                     # not yet: brief blips don't alert
    t[0] += 31
    w.check()
    assert ("medium", "Live stream disconnected") in al.sent
    n = len(al.sent)
    t[0] += 60
    w.check()
    assert len(al.sent) == n                                 # once, not every check
    m.tracker.set_stream_state(StreamState.CONNECTED, "back")
    w.check()
    assert al.sent[-1] == ("low", "Live stream reconnected")
