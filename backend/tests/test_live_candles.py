"""0.8 candle engine (mocked trade data, no network): construction, aggregation, volume, duplicates, out-of-order, precision."""
from datetime import datetime, timedelta, timezone

from app.futures import contracts as fc
from app.futures.candles import CandleBuilder, aggregate, bucket_start, snap
from app.futures.sessions import FuturesClock

UTC = timezone.utc
MNQ = fc.get("MNQ")
CLK = FuturesClock(MNQ)
T0 = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)          # Tue 08:30 CT, inside the session (opened Mon 17:00 CT = 23:00 UTC)


def b():
    return CandleBuilder(MNQ, CLK)


def test_trades_build_one_minute_bars():
    cb = b()
    cb.add_trade(21000.25, 2, T0 + timedelta(seconds=1), 0)
    cb.add_trade(21001.00, 1, T0 + timedelta(seconds=20), 0)
    cb.add_trade(20999.75, 3, T0 + timedelta(seconds=40), 1)
    r = cb.add_trade(21000.50, 1, T0 + timedelta(seconds=59), 0)
    assert r["kind"] == "update"
    bar = cb.bars_list()[0]
    assert (bar["open"], bar["high"], bar["low"], bar["close"]) == (21000.25, 21001.0, 20999.75, 21000.5)
    assert bar["volume"] == 7 and bar["buy_volume"] == 4 and bar["sell_volume"] == 3 and bar["trades"] == 4
    assert cb.add_trade(21002.0, 1, T0 + timedelta(minutes=1, seconds=3))["kind"] == "new"
    assert [x["ts"] for x in cb.bars_list()] == [T0, T0 + timedelta(minutes=1)]


def test_bars_close_on_the_clock_with_grace():
    cb = b()
    cb.add_trade(21000.25, 1, T0 + timedelta(seconds=5))
    assert cb.close_due(T0 + timedelta(seconds=61)) == []                       # still within the 2 s grace
    closed = cb.close_due(T0 + timedelta(seconds=62))
    assert len(closed) == 1 and closed[0]["closed"] and cb.close_due(T0 + timedelta(minutes=5)) == []


def test_duplicates_dropped_and_counted():
    cb = b()
    t = T0 + timedelta(seconds=10, microseconds=123456)
    cb.add_trade(21000.25, 2, t, 0)
    assert cb.add_trade(21000.25, 2, t, 0)["kind"] == "duplicate"
    assert cb.add_trade(21000.25, 2, t, 1)["kind"] == "update"                 # different side: a different print
    assert cb.bars_list()[0]["volume"] == 4 and cb.stats.duplicates == 1


def test_out_of_order_trades_revise_the_right_bar():
    cb = b()
    cb.add_trade(21000.00, 1, T0 + timedelta(seconds=30))
    cb.add_trade(21005.00, 1, T0 + timedelta(minutes=1, seconds=10))
    cb.close_due(T0 + timedelta(minutes=1, seconds=5))
    # an earlier print for minute 0 arrives late: becomes the open, extends the low, bar marked revised
    r = cb.add_trade(20998.00, 4, T0 + timedelta(seconds=2))
    assert r["kind"] == "revised"
    m0 = cb.bars_list()[0]
    assert m0["open"] == 20998.0 and m0["low"] == 20998.0 and m0["close"] == 21000.0 and m0["volume"] == 5 and m0["revised"] == 1
    # a late print that opens a minute before the others keeps bars in time order
    cb.add_trade(20990.00, 1, T0 - timedelta(minutes=2, seconds=-5))
    assert [x["ts"] for x in cb.bars_list()] == [T0 - timedelta(minutes=2), T0, T0 + timedelta(minutes=1)]
    # beyond the 10-minute revision window: counted, not applied
    assert cb.add_trade(20000.00, 1, T0 - timedelta(minutes=30))["kind"] == "too_late" and cb.stats.too_late == 1


def test_tick_precision():
    assert snap(21000.250000000004, MNQ) == (21000.25, True)
    assert snap(21000.3, MNQ) == (None, False)
    cb = b()
    assert cb.add_trade(21000.3, 1, T0)["kind"] == "off_tick" and cb.stats.off_tick == 1 and not cb.bars
    cb.add_trade(21000.500000001, 1, T0)
    assert cb.bars_list()[0]["close"] == 21000.5


def test_outside_session_and_close_print():
    cb = b()
    brk = datetime(2026, 11, 10, 22, 30, tzinfo=UTC)             # 16:30 CT, daily break
    assert cb.add_trade(21000.0, 1, brk)["kind"] == "outside_session"
    close = datetime(2026, 11, 10, 22, 0, 2, tzinfo=UTC)          # 2 s after the 16:00 CT close: settlement print
    r = cb.add_trade(21000.0, 1, close)
    assert r["kind"] == "new" and r["bar"]["ts"] == datetime(2026, 11, 10, 21, 59, tzinfo=UTC)


def _ones(start, n, px=21000.0):
    return [{"ts": start + timedelta(minutes=i), "open": px + i, "high": px + i + 1, "low": px + i - 1, "close": px + i + 0.5,
             "volume": 10 + i} for i in range(n)]


def test_aggregation_and_volume_sum():
    five = aggregate(_ones(T0, 10), 300, CLK, now=T0 + timedelta(minutes=7))
    assert [x["ts"] for x in five] == [T0, T0 + timedelta(minutes=5)]
    a = five[0]
    assert (a["open"], a["high"], a["low"], a["close"], a["volume"]) == (21000.0, 21005.0, 20999.0, 21004.5, 60)
    assert a["closed"] and not five[1]["closed"]


def test_session_anchored_hour_4h_and_daily():
    open_ = datetime(2026, 11, 9, 23, 0, tzinfo=UTC)               # Mon 17:00 CT Globex open of trade date Tue 11-10
    assert bucket_start(open_ + timedelta(minutes=59), 3600, CLK)[0] == open_
    s4, e4 = bucket_start(datetime(2026, 11, 10, 3, 30, tzinfo=UTC), 14400, CLK)
    assert s4 == datetime(2026, 11, 10, 3, 0, tzinfo=UTC) and e4 == datetime(2026, 11, 10, 7, 0, tzinfo=UTC)   # 21:00-01:00 CT
    last4 = bucket_start(datetime(2026, 11, 10, 21, 30, tzinfo=UTC), 14400, CLK)
    assert last4 == (datetime(2026, 11, 10, 19, 0, tzinfo=UTC), datetime(2026, 11, 10, 22, 0, tzinfo=UTC))       # cut at the close
    d = aggregate(_ones(open_, 30) + _ones(T0, 30), 86400, CLK)
    assert len(d) == 1 and d[0]["ts"] == datetime(2026, 11, 10, tzinfo=UTC) and d[0]["volume"] == 2 * sum(10 + i for i in range(30))
    # the next session's first bar starts a new daily bar
    nxt = aggregate(_ones(datetime(2026, 11, 10, 23, 0, tzinfo=UTC), 2), 86400, CLK)
    assert nxt[0]["ts"] == datetime(2026, 11, 11, tzinfo=UTC)
    assert bucket_start(datetime(2026, 11, 10, 22, 30, tzinfo=UTC), 3600, CLK) is None              # daily break


def test_backfill_replaces_ended_minutes_only():
    cb = b()
    cb.add_trade(21000.0, 1, T0 + timedelta(seconds=5))               # stream saw only 1 contract in minute 0
    now = T0 + timedelta(minutes=3, seconds=30)
    cb.add_trade(21010.0, 1, T0 + timedelta(minutes=3, seconds=10))   # forming minute 3
    hist = _ones(T0, 4)                                               # REST has minutes 0..3 (3 is still forming)
    res = cb.merge_history(hist, now)
    assert res == {"added": 2, "replaced": 1}
    bars = cb.bars_list()
    assert bars[0]["volume"] == 10 and bars[0]["source"] == "backfill"
    assert bars[3]["source"] == "stream" and bars[3]["close"] == 21010.0
    assert cb.missing_minutes(T0, T0 + timedelta(minutes=4)) == []
    assert cb.missing_minutes(T0, T0 + timedelta(minutes=6)) == [T0 + timedelta(minutes=4), T0 + timedelta(minutes=5)]
