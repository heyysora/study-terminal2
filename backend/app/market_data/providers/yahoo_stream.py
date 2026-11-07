"""Yahoo Finance streaming socket client.

Protocol (undocumented, observed and used by yfinance):
  client -> {"subscribe": ["AAPL", "TSLA"]}        (re-sent every ~15s as a keep-alive)
  client -> {"unsubscribe": ["AAPL"]}
  server -> {"type": "pricing", "message": "<base64 protobuf PricingData>"}

No authentication. Updates arrive when a price changes, so a quiet symbol sends
nothing; the freshness tracker decides when silence becomes STALE.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timezone

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus, InvalidURI

from ..types import Tick
from .base import StateHandler, StreamState, TickHandler, TickStream

log = logging.getLogger(__name__)

YAHOO_STREAM_URL = "wss://streamer.finance.yahoo.com/?version=2"
MARKET_HOURS = {0: "pre", 1: "regular", 2: "post", 3: "extended"}


def decode_pricing(b64: str) -> dict:
    from google.protobuf.json_format import MessageToDict
    from yfinance.pricing_pb2 import PricingData

    p = PricingData()
    p.ParseFromString(base64.b64decode(b64))
    return MessageToDict(p, preserving_proto_field_name=True)


def _f(d: dict, k: str) -> float | None:
    v = d.get(k)
    try:
        v = float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
    return v if v not in (0.0,) or k in ("change", "change_percent") else None


def pricing_to_tick(d: dict, received_at: datetime) -> Tick | None:
    sym, price, t = d.get("id"), d.get("price"), d.get("time")
    if not sym or price is None or t is None:
        return None
    ts = datetime.fromtimestamp(int(t) / 1000, tz=timezone.utc)
    # proto3 omits fields equal to their default (0), and 0 means pre-market, so absent == "pre".
    mh = int(d.get("market_hours", 0))
    return Tick(
        symbol=sym, price=float(price), ts=ts, received_at=received_at, provider="yahoo", source="yahoo-stream",
        day_volume=_f(d, "day_volume"), day_high=_f(d, "day_high"), day_low=_f(d, "day_low"), open=_f(d, "open_price"),
        prev_close=_f(d, "previous_close"), change_pct=_f(d, "change_percent"), bid=_f(d, "bid"), ask=_f(d, "ask"),
        bid_size=_f(d, "bid_size"), ask_size=_f(d, "ask_size"),
        market_hours=MARKET_HOURS.get(mh, str(mh)),
    )


class YahooStream(TickStream):
    def __init__(self, on_tick: TickHandler, on_state: StateHandler, url: str = YAHOO_STREAM_URL,
                 resubscribe_every: float = 15.0, max_backoff: float = 60.0):
        self.url = url
        self.on_tick = on_tick
        self.on_state = on_state
        self.resubscribe_every = resubscribe_every
        self.max_backoff = max_backoff
        self.state = StreamState.IDLE
        self.state_reason = "not started"
        self.reconnects = 0
        self.messages = 0
        self._symbols: set[str] = set()
        self._sent: set[str] = set()
        self._ws = None
        self._stop = asyncio.Event()

    def _set(self, state: StreamState, reason: str) -> None:
        if (state, reason) != (self.state, self.state_reason):
            self.state, self.state_reason = state, reason
            self.on_state(state, reason)

    async def set_symbols(self, symbols: list[str]) -> None:
        self._symbols = {s.upper() for s in symbols}
        await self._sync()

    async def _sync(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            remove = sorted(self._sent - self._symbols)
            if remove:
                await ws.send(json.dumps({"unsubscribe": remove}))
            if self._symbols:
                await ws.send(json.dumps({"subscribe": sorted(self._symbols)}))
            self._sent = set(self._symbols)
        except ConnectionClosed:
            pass  # run() reconnects

    async def _keepalive(self) -> None:
        while True:
            await asyncio.sleep(self.resubscribe_every)
            await self._sync()

    async def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            await self._ws.close()

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            self._set(StreamState.CONNECTING, "Connecting to Yahoo streaming socket")
            keepalive = None
            try:
                async with connect(self.url, open_timeout=15, ping_interval=20, ping_timeout=20, close_timeout=5,
                                   max_size=2**22) as ws:
                    self._ws = ws
                    self._sent = set()
                    await self._sync()
                    backoff = 1.0
                    self._set(StreamState.CONNECTED, "Connected to Yahoo streaming socket (unofficial)")
                    keepalive = asyncio.create_task(self._keepalive())
                    async for raw in ws:
                        self._handle(raw)
                if not self._stop.is_set():
                    self._set(StreamState.DISCONNECTED, "Yahoo closed the stream; reconnecting")
            except (ConnectionClosed, InvalidStatus, InvalidURI, OSError, asyncio.TimeoutError) as e:
                if self._stop.is_set():
                    break
                self._set(StreamState.DISCONNECTED, f"Stream connection lost ({type(e).__name__}); retrying in {backoff:.0f}s")
            finally:
                if keepalive:
                    keepalive.cancel()
                self._ws = None
            if self._stop.is_set():
                break
            self.reconnects += 1
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, self.max_backoff)
        self._set(StreamState.DISCONNECTED, "Stream stopped")

    def _handle(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
            data = decode_pricing(msg["message"])
            tick = pricing_to_tick(data, datetime.now(timezone.utc))
        except Exception:
            log.debug("undecodable Yahoo stream message ignored", exc_info=True)
            return
        if tick is None or tick.symbol not in self._symbols:
            return
        self.messages += 1
        try:
            self.on_tick(tick)
        except Exception:
            log.exception("tick handler failed for %s", tick.symbol)
