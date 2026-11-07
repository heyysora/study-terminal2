"""YahooProvider with yfinance replaced by a fake module (no network)."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pandas as pd
import pytest

from app.market_data.providers import yahoo
from app.market_data.providers.base import ProviderRateLimited, SymbolNotFound
from app.market_data.providers.yahoo import RateLimiter, YahooProvider, aggregate_4h, frame_to_bars
from app.market_data.types import Timeframe


def ohlcv(index, start=100.0):
    n = len(index)
    return pd.DataFrame({"Open": [start + i for i in range(n)], "High": [start + i + 1 for i in range(n)],
                         "Low": [start + i - 1 for i in range(n)], "Close": [start + i + 0.5 for i in range(n)],
                         "Adj Close": [0.0] * n, "Volume": [1000 * (i + 1) for i in range(n)]}, index=index)


class FakeYF:
    def __init__(self, history=None, info=None, download=None, exc=None):
        self._history, self._info, self._download, self._exc = history, info or {}, download, exc
        self.calls = []

    def Ticker(self, sym):  # noqa: N802
        outer = self

        class T:
            info = outer._info.get(sym, {})

            def history(self, **kw):
                outer.calls.append(("history", sym, kw))
                if outer._exc:
                    raise outer._exc
                return outer._history if outer._history is not None else pd.DataFrame()

        return T()

    def download(self, **kw):
        self.calls.append(("download", kw))
        if self._exc:
            raise self._exc
        return self._download

    def set_tz_cache_location(self, path):
        pass


@pytest.fixture
def use(monkeypatch):
    def _use(fake):
        monkeypatch.setattr(yahoo, "_yf", lambda: fake)
        return fake
    return _use


async def test_history_raw_prices_and_notes(use):
    idx = pd.date_range("2026-11-06 09:30", periods=3, freq="5min", tz="America/New_York")
    fake = use(FakeYF(history=ohlcv(idx)))
    bars, notes = await YahooProvider().get_bars("TSLA", Timeframe.M5, datetime.now(timezone.utc) - timedelta(days=2))
    assert [b.close for b in bars] == [100.5, 101.5, 102.5]
    assert bars[0].ts == datetime(2026, 11, 6, 14, 30, tzinfo=timezone.utc)
    kw = fake.calls[0][2]
    assert kw["auto_adjust"] is False and kw["interval"] == "5m" and kw["prepost"] is True
    assert any("volume as 0" in n for n in notes)


async def test_lookback_clamped_with_note(use):
    idx = pd.date_range("2026-11-06 09:30", periods=2, freq="1min", tz="America/New_York")
    use(FakeYF(history=ohlcv(idx)))
    _, notes = await YahooProvider().get_bars("TSLA", Timeframe.M1, datetime.now(timezone.utc) - timedelta(days=90))
    assert any("only serves 1Min" in n for n in notes)


async def test_empty_history_is_symbol_not_found(use):
    use(FakeYF(history=pd.DataFrame()))
    with pytest.raises(SymbolNotFound):
        await YahooProvider().get_bars("ZZZZ", Timeframe.D1, datetime.now(timezone.utc) - timedelta(days=5))


async def test_rate_limit_mapped_and_penalized(use):
    class YFRateLimitError(Exception):
        pass

    use(FakeYF(exc=YFRateLimitError("Too Many Requests. Rate limited.")))
    p = YahooProvider()
    with pytest.raises(ProviderRateLimited):
        await p.get_bars("TSLA", Timeframe.D1, datetime.now(timezone.utc) - timedelta(days=5))
    assert p.limiter.blocked_until > 0


def test_4h_aggregation_anchored_at_930():
    idx = pd.date_range("2026-11-06 09:30", periods=7, freq="60min", tz="America/New_York")  # 09:30..15:30
    bars = frame_to_bars(ohlcv(idx), "TSLA", Timeframe.H1, "x")
    out = aggregate_4h(bars)
    assert len(out) == 2
    assert out[0].open == 100 and out[0].close == 103.5 and out[0].high == 104 and out[0].volume == 10_000
    assert out[1].ts == datetime(2026, 11, 6, 18, 30, tzinfo=timezone.utc)  # 13:30 ET


async def test_recent_bars_multi_ticker(use):
    idx = pd.date_range("2026-11-06 15:58", periods=2, freq="1min", tz="America/New_York")
    df = pd.concat({"SPY": ohlcv(idx, 700), "AAPL": ohlcv(idx, 300)}, axis=1)
    df[("AAPL", "Close")] = float("nan")  # missing data rows are dropped
    use(FakeYF(download=df))
    out = await YahooProvider().get_recent_bars(["SPY", "AAPL", "NOPE"])
    assert list(out) == ["SPY"] and out["SPY"][-1].close == 701.5 and out["SPY"][-1].source == "yahoo-poll"


async def test_feed_info_classification(use):
    use(FakeYF(info={
        "AAPL": {"quoteType": "EQUITY", "quoteSourceName": "Nasdaq Real Time Price", "exchangeDataDelayedBy": 15},
        "XYZ": {"quoteType": "EQUITY", "quoteSourceName": "Delayed Quote", "exchangeDataDelayedBy": 15},
        "NOPE": {},
    }))
    p = YahooProvider()
    a = await p.get_feed_info("AAPL")
    assert a.realtime_price is True and "Nasdaq Last Sale" in a.note
    x = await p.get_feed_info("XYZ")
    assert x.realtime_price is False and x.delay_minutes == 15
    with pytest.raises(SymbolNotFound):
        await p.get_feed_info("NOPE")


async def test_rate_limiter_window():
    rl = RateLimiter(per_minute=3)
    await rl.acquire(3)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(rl.acquire(1), 0.2)
