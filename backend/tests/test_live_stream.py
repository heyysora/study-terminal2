"""0.8 live stream against a LOCAL MOCK SignalR hub (tests/mock_signalr.py). These are mocked tests: they exercise Study Terminal's
protocol handling, data integrity and reconnection logic, NOT the real TopstepX service (see docs/LIVE_MARKET_DATA.md)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core.events import Broadcaster
from app.futures import contracts as fc
from app.futures import stream as st
from app.futures.data import FuturesData
from app.futures.paper import TRADABLE
from app.futures.pipeline import LIVE
from app.futures.sessions import FuturesClock
from app.market_data.types import Timeframe

from .mock_signalr import MockHub

UTC = timezone.utc
T0 = datetime(2026, 11, 10, 14, 30, tzinfo=UTC)            # Tue 08:30 CT; front contracts are the Dec 2026 (Z26) quarterlies


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class FakeProjectX:
    """Stands in for the REST client: contract ids, a token, and 1-minute history for backfill."""

    def __init__(self):
        self.history: dict[str, list[dict]] = {}
        self.bar_calls: list[tuple] = []
        self.invalidated = 0

    async def find_contract(self, name):
        return {"id": f"CON.F.US.{name}", "name": name}

    async def token(self):
        return "jwt-abc"

    def invalidate_token(self):
        self.invalidated += 1

    async def bars(self, name, minutes, start, end=None, limit=5000):
        self.bar_calls.append((name, minutes, start, end))
        return [b for b in self.history.get(name, []) if start <= b["ts"] < (end or T0 + timedelta(days=1))]


async def until(pred, timeout=5.0):
    for _ in range(int(timeout / 0.02)):
        if pred():
            return
        await asyncio.sleep(0.02)
    raise TimeoutError


@pytest.fixture
def fast_backoff(monkeypatch):
    monkeypatch.setattr(st, "BACKOFF", [0.05] * 6)


async def make(hub, px, clock, roots=("MNQ",), **kw):
    bc = Broadcaster()
    q = bc.subscribe()
    s = st.LiveStream(px, list(roots), rtc_url=hub.url, broadcaster=bc, now=clock, publish_interval=0, **kw)
    s._ticker = None
    s._task = asyncio.create_task(s._run())                 # no 1 s tick loop in tests; tick() is called explicitly
    return s, q


def drain(q):
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


async def test_connects_with_token_and_subscribes_only_to_market_data(fast_backoff):
    async with MockHub() as hub:
        clock = Clock(T0)
        s, _ = await make(hub, FakeProjectX(), clock, roots=("MNQ", "ES"))
        await until(lambda: len(hub.invocations) >= 4 and s.state == "connected")
        assert hub.tokens == ["jwt-abc"]
        assert sorted((m["target"], m["arguments"][0]) for m in hub.invocations) == [
            ("SubscribeContractQuotes", "CON.F.US.ESZ6"), ("SubscribeContractQuotes", "CON.F.US.MNQZ6"),
            ("SubscribeContractTrades", "CON.F.US.ESZ6"), ("SubscribeContractTrades", "CON.F.US.MNQZ6")]
        with pytest.raises(st.HubError):
            await s._hub.invoke("PlaceOrder", 1)                # the client can't send anything but the two subscriptions
        await s.stop()


async def test_quotes_and_trades_carry_integrity_fields(fast_backoff):
    async with MockHub() as hub:
        clock = Clock(T0 + timedelta(seconds=30))
        s, q = await make(hub, FakeProjectX(), clock)
        await until(lambda: s.state == "connected" and s.feeds["MNQ"].subscribed)
        cid = "CON.F.US.MNQZ6"
        await hub.push("GatewayQuote", cid, {"symbol": "F.US.MNQ", "lastPrice": 21000.25, "bestBid": 21000.0, "bestAsk": 21000.25,
                                              "timestamp": "2026-11-10T14:30:29.500Z"})
        await hub.push("GatewayTrade", cid, {"symbolId": "F.US.MNQ", "price": 21000.25, "volume": 2, "type": 0, "timestamp": "2026-11-10T14:30:05Z"})
        await hub.push("GatewayTrade", cid, [{"price": 21001.0, "volume": 1, "type": 0, "timestamp": "2026-11-10T14:30:20Z"},
                                             {"price": 21000.5, "volume": 3, "type": 1, "timestamp": "2026-11-10T14:30:28Z"}])
        await until(lambda: s.feeds["MNQ"].builder.stats.applied == 3)
        info = s.status_of("MNQ")
        assert info["status"] == "realtime" and info["source"] == "topstepx-stream" and info["contract"] == "MNQZ26"
        assert info["price"] == 21000.5 and info["bid"] == 21000.0 and info["ask"] == 21000.25
        assert info["trade_exchange_ts"] == "2026-11-10T14:30:28+00:00" and info["quote_exchange_ts"] == "2026-11-10T14:30:29.500000+00:00"
        assert info["exchange_ts"] == info["quote_exchange_ts"] and info["received_at"] == clock.t.isoformat()
        bar = s.feeds["MNQ"].builder.bars_list()[0]
        assert (bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"]) == (21000.25, 21001.0, 21000.25, 21000.5, 6)
        pushes = [e for e in drain(q) if e["type"] == "futures_live"]
        assert pushes and pushes[-1]["data"]["status"] == "realtime" and pushes[-1]["data"]["bar"]["close"] == 21000.5
        assert all(p["data"]["source"] == "topstepx-stream" and "received_at" in p["data"] for p in pushes)
        # a late print (earlier exchange time) updates the bar but never moves the last price backwards
        await hub.push("GatewayTrade", cid, {"price": 20999.0, "volume": 1, "type": 1, "timestamp": "2026-11-10T14:30:01Z"})
        await until(lambda: s.feeds["MNQ"].builder.stats.applied == 4)
        assert s.status_of("MNQ")["price"] == 21000.5 and s.feeds["MNQ"].builder.bars_list()[0]["open"] == 20999.0
        # duplicate print
        await hub.push("GatewayTrade", cid, {"price": 21000.5, "volume": 3, "type": 1, "timestamp": "2026-11-10T14:30:28Z"})
        await until(lambda: s.feeds["MNQ"].builder.stats.duplicates == 1)
        await s.stop()


async def test_stale_and_closed_market(fast_backoff):
    async with MockHub() as hub:
        clock = Clock(T0)
        s, _ = await make(hub, FakeProjectX(), clock, stale_seconds=30)
        await until(lambda: s.state == "connected")
        assert s.status_of("MNQ")["status"] == "stale"                     # connected but nothing received yet
        await hub.push("GatewayQuote", "CON.F.US.MNQZ6", {"lastPrice": 21000.0, "timestamp": "2026-11-10T14:30:00Z"})
        await until(lambda: s.feeds["MNQ"].last_market_msg is not None)
        assert s.status_of("MNQ")["status"] == "realtime"
        clock.t = T0 + timedelta(seconds=31)
        assert s.status_of("MNQ")["status"] == "stale"
        clock.t = datetime(2026, 11, 10, 22, 30, tzinfo=UTC)               # daily break
        assert s.status_of("MNQ")["status"] == "historical"
        await s.stop()


async def test_disconnect_reconnect_and_backfill(fast_backoff):
    async with MockHub() as hub:
        clock = Clock(T0 + timedelta(minutes=1, seconds=10))
        px = FakeProjectX()
        s, q = await make(hub, px, clock)
        await until(lambda: s.state == "connected" and s.feeds["MNQ"].subscribed)
        await hub.push("GatewayTrade", "CON.F.US.MNQZ6", {"price": 21000.0, "volume": 1, "type": 0, "timestamp": "2026-11-10T14:30:05Z"})
        await until(lambda: s.feeds["MNQ"].builder.stats.applied == 1)
        await hub.drop_all()                                                # network drop
        await until(lambda: s.state == "disconnected")
        assert s.status_of("MNQ")["status"] == "disconnected" and "No live signals" in s.status_of("MNQ")["reason"]
        # while disconnected, minutes 1-3 traded; TopstepX REST has them
        px.history["MNQZ6"] = [{"ts": T0 + timedelta(minutes=i), "open": 21000.0 + i, "high": 21001.0 + i, "low": 20999.0 + i,
                                "close": 21000.5 + i, "volume": 10.0} for i in range(0, 4)]
        clock.t = T0 + timedelta(minutes=4, seconds=5)
        await until(lambda: s.state == "connected" and hub.connects == 2 and s.gaps)
        g = s.gaps[-1]
        assert g["contract"] == "MNQZ26" and g["backfill"]["added"] == 3 and g["backfill"]["replaced"] == 1
        bars = s.feeds["MNQ"].builder.bars_list()
        assert [b["ts"] for b in bars] == [T0 + timedelta(minutes=i) for i in range(4)] and bars[0]["volume"] == 10.0
        assert len([m for m in hub.invocations if m["target"] == "SubscribeContractTrades"]) == 2     # re-subscribed
        states = [e["data"]["state"] for e in drain(q) if e["type"] == "futures_stream"]
        assert "disconnected" in states and states[-1] == "connected"
        await s.stop()


async def test_subscription_refused_is_shown_not_hidden(fast_backoff):
    async with MockHub(refuse={"SubscribeContractTrades"}) as hub:
        s, _ = await make(hub, FakeProjectX(), Clock(T0))
        await until(lambda: s.feeds["MNQ"].subscribe_error is not None)
        info = s.status_of("MNQ")
        assert info["status"] == "disconnected" and "subscription" in info["reason"].lower()
        await s.stop()


async def test_bar_close_callback_and_rollover(fast_backoff):
    async with MockHub() as hub:
        clock = Clock(T0 + timedelta(seconds=10))
        closed = []
        s, q = await make(hub, FakeProjectX(), clock, on_bar_close=lambda r, b: closed.append((r, b["ts"])))
        await until(lambda: s.state == "connected" and s.feeds["MNQ"].subscribed)
        await hub.push("GatewayTrade", "CON.F.US.MNQZ6", {"price": 21000.0, "volume": 1, "type": 0, "timestamp": "2026-11-10T14:30:05Z"})
        await until(lambda: s.feeds["MNQ"].builder.stats.applied == 1)
        clock.t = T0 + timedelta(minutes=1, seconds=3)
        await s.tick()
        assert closed == [("MNQ", T0)] and any(e["type"] == "futures_bar_closed" for e in drain(q))
        # after the December roll date the stream switches to March and resubscribes
        clock.t = datetime(2026, 12, 15, 15, 0, tzinfo=UTC)
        rolled = await s.check_rollover()
        assert rolled == ["MNQZ26->MNQH27"]
        await until(lambda: any(m["arguments"][0] == "CON.F.US.MNQH7" for m in hub.invocations))
        await s.stop()


async def test_data_layer_labels_stream_bars_and_never_trades_on_disconnect(fast_backoff):
    class Store(dict):
        def get(self, k, d=None):
            return super().get(k, d)
    async with MockHub() as hub:
        clock = Clock(T0 + timedelta(minutes=2, seconds=30))
        px = FakeProjectX()
        px.history["MNQZ6"] = [{"ts": T0 - timedelta(minutes=i), "open": 20990.0, "high": 20995.0, "low": 20985.0, "close": 20992.0,
                                "volume": 5.0} for i in range(1, 30)]
        s, _ = await make(hub, px, clock)
        await until(lambda: s.state == "connected" and s.feeds["MNQ"].subscribed)
        for sec, p in [(5, 21000.0), (65, 21002.0), (130, 21003.0)]:
            await hub.push("GatewayTrade", "CON.F.US.MNQZ6", {"price": p, "volume": 1, "type": 0,
                                                              "timestamp": (T0 + timedelta(seconds=sec)).isoformat()})
        await until(lambda: s.feeds["MNQ"].builder.stats.applied == 3)
        s.feeds["MNQ"].builder.close_due(clock.t)
        data = FuturesData(yahoo=None, store=Store({"futures.data_source": "projectx"}), projectx=px)
        data.stream = s
        c = fc.front_contract("MNQ", T0.date())
        clk = FuturesClock(c.spec)
        bars, label, _ = await data.bars(c, Timeframe.M1, clk, days=1, now=clock.t)
        assert label["status"] == "realtime" and label["provider"] == "topstepx-stream" and label["status"] in LIVE
        assert bars[-1]["ts"] == T0 + timedelta(minutes=2) and bars[-1]["closed"] is False and bars[-2]["closed"] is True
        assert bars[0]["ts"] == T0 - timedelta(minutes=29)                    # REST history before the stream
        five, l5, _ = await data.bars(c, Timeframe.M5, clk, days=1, now=clock.t)
        assert five[-1]["ts"] == T0 and five[-1]["volume"] == 3 and not five[-1]["closed"]
        await hub.drop_all()
        await until(lambda: s.state == "disconnected")
        _, ld, _ = await data.bars(c, Timeframe.M1, clk, days=1, now=clock.t)
        assert ld["status"] == "disconnected" and ld["status"] not in TRADABLE and ld["status"] not in LIVE
        await s.stop()


def test_yahoo_is_never_live():
    assert "delayed" not in TRADABLE and "delayed" not in LIVE
    assert "disconnected" not in TRADABLE and "stale" not in LIVE
