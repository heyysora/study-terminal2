"""Live crypto prices through ccxt: read-only, cached, and honest when an exchange doesn't answer. No network in these tests."""
import time

import pytest

from app.market_data import exchanges as X


class FakeEx:
    def __init__(self, eid, fail=False, last=100.0):
        self.eid, self.fail, self.last, self.calls = eid, fail, last, 0

    def fetch_tickers(self, syms):
        self.calls += 1
        if self.fail:
            raise RuntimeError("down")
        return {s: {"last": self.last + i, "high": self.last + 10, "low": self.last - 10, "bid": None, "ask": None, "timestamp": 1}
                for i, s in enumerate(syms)}

    def fetch_ohlcv(self, sym, tf, limit=26):
        now = int(time.time() * 1000)
        return [[now - (25 - i) * 3600_000, 80.0, 0, 0, 80.0 + i, 1] for i in range(26)]


def markets(**fail):
    made = {}

    def factory(eid):
        made[eid] = FakeEx(eid, fail=fail.get(eid, False))
        return made[eid]
    return X.CryptoMarkets(ttl=60, factory=factory), made


async def test_prices_come_from_the_first_exchange_that_answers():
    m, made = markets(kraken=True)
    t = await m.tickers()
    assert t["ok"] and t["source"] == "Coinbase" and len(t["rows"]) == len(X.COINS)
    assert t["rows"][0]["symbol"] == "BTC-USD" and t["rows"][0]["price"] == 100.0 and t["rows"][0]["high_24h"] == 110.0
    assert "Watch only" in t["note"]


async def test_prices_are_cached_and_the_24_hour_change_fills_in():
    m, made = markets()
    await m.tickers()
    await m.tickers()
    assert made["kraken"].calls == 1
    await m._hist_task
    t = await m.tickers()
    r = t["rows"][0]
    assert r["change_24h_pct"] == 25.0 and len(r["spark"]) == 24        # 100 now against 80 a day ago


async def test_when_no_exchange_answers_it_says_so_and_shows_nothing_made_up():
    m, _ = markets(kraken=True, coinbaseexchange=True, bitstamp=True)
    t = await m.tickers()
    assert t["ok"] is False and t["rows"] == [] and "Couldn't reach" in t["error"]


async def test_old_prices_are_marked_stale_not_passed_off_as_live():
    m, made = markets()
    await m.tickers()
    made["kraken"].fail = True
    for eid in ("coinbaseexchange", "bitstamp"):
        m._ex[eid] = FakeEx(eid, fail=True)
    m._tick["fetched_at"] -= 120
    m._tick_at -= 120
    t = await m.tickers()
    assert t["ok"] and t["stale"] is True and t["age_seconds"] >= 120 and "last prices received" in t["error"]


async def test_only_listed_dollar_pairs_have_a_live_price():
    assert X.pair("BTC-USD") == "BTC/USD" and X.pair("eth") == "ETH/USD"
    assert X.pair("AAPL") is None and X.pair("BTC-EUR") is None
    m, _ = markets()
    assert (await m.price("SOL-USD"))["coin"] == "SOL" and await m.price("SPY") is None


async def test_api_serves_markets_and_the_lock_check(settings):
    from .test_memecoins import _client
    async with await _client(settings) as (app, c):
        app.state.crypto = markets()[0]
        r = (await c.get("/api/crypto/markets")).json()
        assert r["ok"] and r["rows"][0]["coin"] == "BTC"
        assert (await c.get("/api/crypto/price/AAPL")).status_code == 404
        lock = (await c.get("/api/crypto/lock-check")).json()
        assert lock["library"] is True and lock["locked"] is True


def test_unknown_exchange_names_are_refused():
    with pytest.raises(ValueError):
        X.make("binance")
