"""YahooStream against a local server speaking Yahoo's protocol (base64 protobuf messages)."""
import asyncio
import base64
import json
import time

from websockets.asyncio.server import serve
from yfinance.pricing_pb2 import PricingData

from app.market_data.providers.base import StreamState
from app.market_data.providers.yahoo_stream import YahooStream


def encode(sym, price, ms=None, market_hours=1):
    p = PricingData(id=sym, price=price, time=ms or int(time.time() * 1000), market_hours=market_hours, day_volume=12345)
    return json.dumps({"type": "pricing", "message": base64.b64encode(p.SerializeToString()).decode()})


class FakeYahoo:
    def __init__(self):
        self.subs: set[str] = set()
        self.messages: list[dict] = []
        self.clients = set()
        self.connections = 0

    async def __aenter__(self):
        self.server = await serve(self.handler, "127.0.0.1", 0)
        self.url = f"ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/"
        return self

    async def __aexit__(self, *a):
        self.server.close()
        await self.server.wait_closed()

    async def handler(self, ws):
        self.connections += 1
        self.clients.add(ws)
        try:
            async for raw in ws:
                m = json.loads(raw)
                self.messages.append(m)
                self.subs |= set(m.get("subscribe", []))
                self.subs -= set(m.get("unsubscribe", []))
        finally:
            self.clients.discard(ws)

    async def push(self, text):
        for ws in list(self.clients):
            await ws.send(text)

    async def drop(self):
        for ws in list(self.clients):
            await ws.close()


async def wait_for(cond, timeout=5):
    end = asyncio.get_running_loop().time() + timeout
    while not cond():
        assert asyncio.get_running_loop().time() < end, "timed out"
        await asyncio.sleep(0.02)


async def test_subscribe_decode_filter_and_keepalive():
    async with FakeYahoo() as srv:
        ticks, states = [], []
        s = YahooStream(on_tick=ticks.append, on_state=lambda st, r: states.append(st), url=srv.url, resubscribe_every=0.1)
        await s.set_symbols(["spy", "AAPL"])
        task = asyncio.create_task(s.run())
        await wait_for(lambda: srv.subs == {"SPY", "AAPL"})
        await srv.push(encode("SPY", 600.25, market_hours=0))
        await srv.push(encode("MSFT", 1.0))  # not subscribed: ignored
        await srv.push("not json")           # garbage: ignored, stream survives
        await wait_for(lambda: len(ticks) == 1)
        t = ticks[0]
        assert t.symbol == "SPY" and t.price == 600.25 and t.market_hours == "pre" and t.day_volume == 12345
        assert t.source == "yahoo-stream" and t.provider == "yahoo"
        await wait_for(lambda: sum("subscribe" in m for m in srv.messages) >= 3)  # keep-alive resubscribes
        await s.set_symbols(["SPY"])
        await wait_for(lambda: srv.subs == {"SPY"})
        await s.stop()
        await asyncio.wait_for(task, 5)
        assert StreamState.CONNECTED in states


async def test_reconnects_and_resubscribes():
    async with FakeYahoo() as srv:
        states = []
        s = YahooStream(on_tick=lambda t: None, on_state=lambda st, r: states.append(st), url=srv.url, max_backoff=0.2)
        await s.set_symbols(["TSLA"])
        task = asyncio.create_task(s.run())
        await wait_for(lambda: srv.subs == {"TSLA"})
        srv.subs.clear()
        await srv.drop()
        await wait_for(lambda: srv.connections >= 2 and srv.subs == {"TSLA"})
        assert StreamState.DISCONNECTED in states and s.reconnects >= 1
        await s.stop()
        await asyncio.wait_for(task, 5)


async def test_unreachable_reports_disconnected():
    reasons = []
    s = YahooStream(on_tick=lambda t: None, on_state=lambda st, r: reasons.append((st, r)), url="ws://127.0.0.1:9/")
    task = asyncio.create_task(s.run())
    await wait_for(lambda: any(st == StreamState.DISCONNECTED and "retrying" in r for st, r in reasons))
    await s.stop()
    await asyncio.wait_for(task, 5)
