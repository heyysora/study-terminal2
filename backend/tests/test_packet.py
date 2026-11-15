"""The 'last closed candle' packet: structure, plain words, agreement checks (counts, not chances), ADX sanity, crypto all-hours."""
from datetime import datetime, timedelta, timezone

from app.analysis.features import build
from app.analysis.packet import SCHEMA, adx
from app.analysis.packet import build as packet
from app.market_data.types import Bar, Timeframe

from .test_day_trader_checklist import walk


def bars(drift=0.0, all_day=False, seed=2):
    out = []
    for b in walk(days=12, drift=drift, seed=seed):
        out.append(Bar(symbol="T", timeframe=Timeframe.M5, ts=b.ts, open=b.open, high=b.high, low=b.low, close=b.close,
                       volume=1000, provider="test", source="test"))
    return out


def test_packet_shape_and_words():
    ff = build(bars(), Timeframe.M5)
    p = packet("T", "5Min", ff, None, {"status": "historical"})
    assert p["schema"] == SCHEMA and p["closed_candle_only"] and len(p["recent_candles"]) == 5
    assert p["regime"] in ("TREND_UP", "TREND_DOWN", "RANGE", "HIGH_VOLATILITY")
    assert p["candle_in_words"].startswith("A ") and p["candle"]["close_position"] is not None
    for side in ("long", "short"):
        a = p["agreement"][side]
        assert a["score"] == 20 * sum(a["checks"].values()) and set(a["checks"]) == {"trend", "momentum", "strength", "volume", "higher_timeframe"}
    assert "Not a chance of winning" in p["agreement"]["meaning"] and "can't place orders" in p["for_an_ai"]
    assert p["risk_map"]["long"]["stop"] < p["candle"]["close"] < p["risk_map"]["long"]["target_1_5r"]


def test_uptrend_reads_as_up():
    ff = build(bars(drift=0.0012, seed=5), Timeframe.M5)
    p = packet("T", "5Min", ff, ff)
    assert p["trend"]["ema21_50_200"] == "up" and p["agreement"]["long"]["score"] > p["agreement"]["short"]["score"]


def test_adx_bounds():
    ff = build(bars(), Timeframe.M5)
    a = adx(ff.df).dropna()
    assert ((a["adx"] >= 0) & (a["adx"] <= 100)).all() and ((a["plus_di"] >= 0)).all()


def test_crypto_keeps_every_hour():
    t0 = datetime(2026, 11, 14, 0, 0, tzinfo=timezone.utc)                     # a Saturday, round the clock
    bs = [Bar(symbol="BTC-USD", timeframe=Timeframe.M5, ts=t0 + timedelta(minutes=5 * i), open=100, high=101, low=99, close=100 + (i % 7),
              volume=1, provider="t", source="t") for i in range(288)]
    assert len(build(bs, Timeframe.M5).df) == 0 or len(build(bs, Timeframe.M5).df) < 288    # stock hours: weekend bars dropped
    assert len(build(bs, Timeframe.M5, all_hours=True).df) == 288
