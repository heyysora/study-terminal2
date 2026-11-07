from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.core.market_clock import MarketClock
from app.market_data.types import DataStatus
from app.paper.engine import (
    OrderRequest, OrderRole, OrderStatus, OrderType, PaperConfig, PaperEngine, PriceRef, RiskConfig, Side, TIF,
    position_size,
)

ET = ZoneInfo("America/New_York")
CLOCK = MarketClock()
T0 = datetime(2026, 11, 24, 10, 0, tzinfo=ET).astimezone(timezone.utc)  # Tuesday, regular session
LIVE = DataStatus.NEAR_REALTIME


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def ref(price, minutes=0, status=LIVE, bid=None, ask=None):
    return PriceRef(price=price, ts=at(minutes), status=status, bid=bid, ask=ask)


def engine(**kw) -> PaperEngine:
    cfg = PaperConfig(starting_cash=25_000, slippage_bps=0, slippage_min=0, **{k: v for k, v in kw.items() if k in PaperConfig.__dataclass_fields__})
    risk = RiskConfig(**{k: v for k, v in kw.items() if k in RiskConfig.__dataclass_fields__})
    return PaperEngine(cfg, risk, CLOCK, now=T0)


def buy(qty, stop=None, tp=None, **kw):
    return OrderRequest(symbol="TSLA", side=Side.BUY, qty=qty, stop_loss=stop, take_profit=tp, **kw)


def test_position_size_math():
    # $25,000 * 0.5% = $125 risk; $2.50/share risk -> 50 shares
    assert position_size(25_000, 0.5, 100.0, 97.5) == 50
    assert position_size(25_000, 0.5, 100.0, 100.0) == 0


def test_market_buy_bracket_and_target_exit():
    e = engine()
    o, pv = e.submit(buy(50, stop=97.5, tp=105), ref(100), at(0))
    assert pv.ok and o.status == OrderStatus.FILLED and o.fill_price == 100
    assert pv.risk_dollars == 125.0 and pv.reward_risk == 2.0
    assert e.positions["TSLA"].qty == 50
    kids = [x for x in e.orders.values() if x.parent_id == o.id]
    assert {k.role for k in kids} == {OrderRole.STOP_LOSS, OrderRole.TAKE_PROFIT}

    e.on_price("TSLA", 103, at(1), LIVE)
    assert e.unrealized() == pytest.approx(150)
    assert e.on_price("TSLA", 105, at(2), LIVE) == []  # touching the target isn't enough
    fills = e.on_price("TSLA", 105.2, at(3), LIVE)
    assert len(fills) == 1 and fills[0].price == 105 and fills[0].realized_pnl == 250
    assert "TSLA" not in e.positions
    assert all(k.status in (OrderStatus.FILLED, OrderStatus.CANCELED) for k in kids)
    assert e.equity() == pytest.approx(25_250)


def test_limit_gets_gap_improvement_only_on_bar_open():
    e = engine()
    o, _ = e.submit(buy(10, stop=90, type=OrderType.LIMIT, limit_price=95), ref(100), at(0))
    assert e.on_price("TSLA", 94, at(1), LIVE, high=94.5, low=93.8, open_=94.2)[0].price == 94.2


def test_stop_gap_fills_worse_than_stop():
    e = engine()
    e.submit(buy(50, stop=97.5), ref(100), at(0))
    fills = e.on_price("TSLA", 96, at(1), LIVE, high=96.5, low=95.8, open_=96.4)
    assert fills[0].price == 96.4  # gapped below the stop -> filled at the open, not 97.50
    assert fills[0].realized_pnl == pytest.approx(-180)


def test_bar_touching_stop_and_target_assumes_stop_first():
    e = engine()
    e.submit(buy(50, stop=97.5, tp=105), ref(100), at(0))
    fills = e.on_price("TSLA", 101, at(1), LIVE, high=106, low=97, open_=100)
    assert len(fills) == 1 and fills[0].role == OrderRole.STOP_LOSS


def test_slippage_and_commission():
    e = PaperEngine(PaperConfig(starting_cash=25_000, slippage_bps=10, commission_per_share=0.01, commission_per_order=1),
                    RiskConfig(), CLOCK, now=T0)
    o, _ = e.submit(buy(40, stop=97.5), ref(100, ask=100.02), at(0))
    assert o.fill_price == pytest.approx(100.02 * 1.001, abs=1e-4)  # buys at the ask, plus 10 bps
    assert e.account.commissions == pytest.approx(1.40)
    assert e.account.cash == pytest.approx(25_000 - 40 * o.fill_price - 1.40, abs=0.01)


def test_short_round_trip_and_borrow_fee():
    e = engine()
    o, pv = e.submit(OrderRequest(symbol="TSLA", side=Side.SELL, qty=40, stop_loss=103), ref(100), at(0))
    assert pv.intent == "open_short" and o.status == OrderStatus.FILLED
    assert any("not verified" in w.lower() for w in pv.warnings)
    assert e.positions["TSLA"].qty == -40
    e.on_price("TSLA", 98, at(5), LIVE)
    assert e.unrealized() == pytest.approx(80)
    # next day: borrow fee charged on the short
    e.roll(at(60 * 24))
    assert e.account.borrow_fees == pytest.approx(40 * 98 * 0.03 / 360, rel=1e-6)
    o2, pv2 = e.submit(OrderRequest(symbol="TSLA", side=Side.BUY, qty=40), ref(98, 60 * 24), at(60 * 24))
    # the bracket stop still holds the shares, so a manual cover is refused...
    assert not pv2.ok and "free to close" in pv2.errors[0]
    # ...Close Position cancels protective orders first
    o3, pv3 = e.close_position("TSLA", ref(98, 60 * 24), at(60 * 24))
    assert pv3.ok and pv3.intent == "close_short" and "TSLA" not in e.positions
    assert e.account.realized_pnl == pytest.approx(80)


def test_risk_rejections():
    e = engine()
    _, pv = e.submit(buy(10), ref(100), at(0))
    assert not pv.ok and "needs a stop loss" in pv.errors[0]
    o, pv = e.submit(buy(100, stop=97.5), ref(100), at(0))  # $250 risk > $125
    assert o.status == OrderStatus.REJECTED and pv.suggested_qty == 50
    _, pv = e.submit(buy(10, stop=101), ref(100), at(0))
    assert any("below the entry" in x for x in pv.errors)
    _, pv = e.submit(buy(50, stop=97.5, tp=102), ref(100), at(0))
    assert pv.ok and any("below your preferred" in w for w in pv.warnings)


def test_buying_power_limit():
    e = engine(max_per_trade_pct=100)
    _, pv = e.submit(buy(600, stop=99), ref(100), at(0))  # $60k > 2x $25k
    assert not pv.ok and any("buying power" in x for x in pv.errors)


def test_daily_loss_limit_blocks_entries_not_exits():
    e = engine(max_per_trade_pct=5)
    e.submit(buy(200, stop=95), ref(100), at(0))
    e.on_price("TSLA", 97.4, at(1), LIVE)  # -$520 > 2% of 25k ($500), stop not yet hit
    assert e.summary()["daily_loss_limit_hit"]
    _, pv = e.submit(OrderRequest(symbol="AAPL", side=Side.BUY, qty=1, stop_loss=90), ref(100), at(2))
    assert not pv.ok and "Daily loss limit" in pv.errors[0]
    o, pv = e.close_position("TSLA", ref(97.4, 3), at(3))
    assert pv.ok and o.status == OrderStatus.FILLED


def test_max_open_positions():
    e = engine(max_open_positions=2)
    for sym in ("A", "B"):
        e.submit(OrderRequest(symbol=sym, side=Side.BUY, qty=10, stop_loss=99), ref(100), at(0))
    _, pv = e.submit(OrderRequest(symbol="C", side=Side.BUY, qty=10, stop_loss=99), ref(100), at(0))
    assert not pv.ok and "Max open positions" in pv.errors[0]


def test_no_fills_on_bad_data_and_no_market_orders_without_fresh_price():
    e = engine()
    _, pv = e.submit(buy(10, stop=99), ref(100, status=DataStatus.DELAYED), at(0))
    assert not pv.ok and "delayed" in pv.errors[0]
    o, _ = e.submit(buy(10, stop=99, type=OrderType.LIMIT, limit_price=99.5), None, at(0))
    assert o.status == OrderStatus.OPEN
    assert e.on_price("TSLA", 99, at(1), DataStatus.STALE) == []
    assert e.on_price("TSLA", 99, at(1), DataStatus.DELAYED) == []
    assert e.on_price("TSLA", 99, at(2), DataStatus.POLLING)[0].price == 99.5  # resting limit fills at its price


def test_market_orders_rejected_outside_regular_hours_and_limit_extended_hours():
    e = engine()
    pre = datetime(2026, 11, 24, 8, 0, tzinfo=ET).astimezone(timezone.utc)
    _, pv = e.submit(buy(10, stop=99), PriceRef(100, pre, LIVE), pre)
    assert not pv.ok and "regular hours" in pv.errors[-1]
    o, pv = e.submit(buy(10, stop=99, type=OrderType.LIMIT, limit_price=100, extended_hours=True), PriceRef(100, pre, LIVE), pre)
    assert pv.ok
    assert e.on_price("TSLA", 99.9, pre + timedelta(minutes=1), LIVE)[0].price == 100
    with pytest.raises(ValidationError):
        buy(10, stop=99, type=OrderType.STOP, stop_price=101, extended_hours=True)


def test_stop_entry_breakout_and_stop_limit():
    e = engine()
    o, pv = e.submit(buy(41, stop=97.5, type=OrderType.STOP, stop_price=100.5), ref(100), at(0))  # $3/sh risk -> 41 max
    assert pv.ok and o.status == OrderStatus.OPEN
    assert e.on_price("TSLA", 100.4, at(1), LIVE) == []
    assert e.on_price("TSLA", 100.6, at(2), LIVE)[0].price == 100.6
    e2 = engine()
    o2, _ = e2.submit(buy(37, stop=97.5, type=OrderType.STOP_LIMIT, stop_price=100.5, limit_price=100.8), ref(100), at(0))
    assert e2.on_price("TSLA", 100.6, at(1), LIVE) == [] and e2.orders[o2.id].triggered
    assert e2.on_price("TSLA", 100.7, at(2), LIVE)[0].price == 100.8


def test_day_orders_expire_gtc_do_not():
    e = engine()
    day, _ = e.submit(buy(10, stop=90, type=OrderType.LIMIT, limit_price=95), ref(100), at(0))
    gtc, _ = e.submit(buy(10, stop=90, type=OrderType.LIMIT, limit_price=95, tif=TIF.GTC), ref(100), at(0))
    after_close = datetime(2026, 11, 24, 16, 1, tzinfo=ET).astimezone(timezone.utc)
    e.roll(after_close)
    assert e.orders[day.id].status == OrderStatus.EXPIRED and e.orders[gtc.id].status == OrderStatus.OPEN


def test_flip_prevented_and_cancel():
    e = engine()
    e.submit(buy(50, stop=97.5), ref(100), at(0))
    _, pv = e.submit(OrderRequest(symbol="TSLA", side=Side.SELL, qty=80), ref(100), at(1))
    assert not pv.ok and "flip" in pv.errors[0]
    o, _ = e.submit(OrderRequest(symbol="AAPL", side=Side.BUY, qty=10, type=OrderType.LIMIT, limit_price=95, stop_loss=90),
                    ref(100), at(1))
    e.cancel(o.id, at(2))
    assert e.orders[o.id].status == OrderStatus.CANCELED
    with pytest.raises(ValueError):
        e.cancel(o.id, at(3))


def test_reset():
    e = engine()
    e.submit(buy(50, stop=97.5), ref(100), at(0))
    e.reset(10_000, at(1))
    assert e.equity() == 10_000 and not e.positions and not e.orders and not e.fills


def test_order_placed_mid_bar_ignores_earlier_bar_extremes():
    e = engine()
    o, _ = e.submit(buy(10, stop=90, type=OrderType.LIMIT, limit_price=99), ref(100, 0.5), at(0.5))
    # bar 10:00-10:01 dipped to 98 but we don't know if that was before 10:00:30
    assert e.on_price("TSLA", 100, at(1), LIVE, high=100.2, low=98, open_=99.5, bar_start=at(0)) == []
    assert e.on_price("TSLA", 98.9, at(2), LIVE, high=100, low=98.5, open_=99.8, bar_start=at(1))[0].price == 99
