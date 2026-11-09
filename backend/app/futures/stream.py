"""TopstepX live market data over the documented ProjectX SignalR market hub. Read-only.

What the official docs specify (gateway.docs.projectx.com, "Real Time Data Overview" and "Connection URLs", checked 2026-11-08):
  * Market hub: https://rtc.topstepx.com/hubs/market?access_token=<JWT from Auth/loginKey>, WebSockets transport, no negotiation
    (the docs' client uses skipNegotiation: true), automatic reconnect, re-subscribe after reconnecting.
  * Methods: SubscribeContractQuotes(contractId), SubscribeContractTrades(contractId) (and SubscribeContractMarketDepth, unused here).
  * Events, each called with (contractId, data): GatewayQuote {symbol, lastPrice, bestBid, bestAsk, change, open, high, low, volume,
    lastUpdated, timestamp} and GatewayTrade {symbolId, price, timestamp, type (0 Buy, 1 Sell), volume}.
Not documented, handled defensively: unsubscribe method names (never called: changing contracts reconnects instead), whether a
GatewayTrade carries one trade or a list (both accepted), and whether quote events carry every field (missing fields keep their
previous value).

The SignalR JSON hub protocol is implemented directly on the `websockets` package already used for Yahoo streaming:
handshake {"protocol":"json","version":1}, invocation (type 1), completion (3), ping (6), close (7), records ended by 0x1E.
The client can only invoke the methods in ALLOWED_METHODS; it has no way to send anything else.

Entitlement: a ProjectX API Access subscription linked to your TopstepX account (see docs/LIVE_MARKET_DATA.md).
NOT TESTED against the real TopstepX hub: every test uses a local mock SignalR server.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from . import contracts as fc
from .candles import CandleBuilder, minute_start
from .sessions import FuturesClock

log = logging.getLogger(__name__)

RS = "\x1e"
DEFAULT_RTC = "https://rtc.topstepx.com"
ALLOWED_METHODS = frozenset({"SubscribeContractQuotes", "SubscribeContractTrades"})
BACKOFF = [1, 2, 5, 10, 30, 60]
SOURCE = "topstepx-stream"


def _parse_ts(s: Any) -> datetime | None:
    if not s:
        return None
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


class HubError(Exception):
    pass


class MarketHub:
    """Minimal SignalR JSON-protocol client for one hub connection."""

    def __init__(self, url: str, on_event: Callable[[str, list], None], *, ping_interval: float = 15.0, server_timeout: float = 30.0,
                 connect: Callable | None = None):
        self.url, self.on_event = url, on_event
        self.ping_interval, self.server_timeout = ping_interval, server_timeout
        self._connect = connect
        self.ws = None
        self._inv = 0
        self.pending: dict[str, asyncio.Future] = {}
        self.last_server_msg = 0.0

    async def open(self) -> None:
        if self._connect is None:
            from websockets.asyncio.client import connect as _c
            self._connect = _c
        self.ws = await self._connect(self.url, open_timeout=10, max_size=8 * 2**20, ping_interval=None)
        await self.ws.send(json.dumps({"protocol": "json", "version": 1}) + RS)
        raw = await asyncio.wait_for(self.ws.recv(), timeout=10)
        first = str(raw).split(RS)[0]
        hs = json.loads(first or "{}")
        if hs.get("error"):
            raise HubError(f"SignalR handshake refused: {hs['error']}")
        self.last_server_msg = time.monotonic()
        for rest in str(raw).split(RS)[1:]:
            if rest:
                self._dispatch(json.loads(rest))

    async def invoke(self, method: str, *args) -> asyncio.Future:
        if method not in ALLOWED_METHODS:
            raise HubError(f"{method} is not allowed: Study Terminal only subscribes to market data.")
        self._inv += 1
        iid = str(self._inv)
        fut = asyncio.get_running_loop().create_future()
        self.pending[iid] = fut
        await self.ws.send(json.dumps({"type": 1, "invocationId": iid, "target": method, "arguments": list(args)}) + RS)
        return fut

    def _dispatch(self, m: dict) -> None:
        t = m.get("type")
        if t == 1:
            self.on_event(m.get("target", ""), m.get("arguments") or [])
        elif t == 3:
            fut = self.pending.pop(str(m.get("invocationId")), None)
            if fut and not fut.done():
                if m.get("error"):
                    fut.set_exception(HubError(str(m["error"])))
                else:
                    fut.set_result(m.get("result"))
        elif t == 7:
            raise HubError(f"Server closed the connection: {m.get('error') or 'no reason given'}")

    async def run(self) -> None:
        """Read until the connection drops. Sends SignalR pings; treats server silence beyond server_timeout as a drop."""
        async def pinger():
            while True:
                await asyncio.sleep(self.ping_interval)
                await self.ws.send(json.dumps({"type": 6}) + RS)
        pt = asyncio.create_task(pinger())
        try:
            while True:
                raw = await asyncio.wait_for(self.ws.recv(), timeout=self.server_timeout)
                self.last_server_msg = time.monotonic()
                for part in str(raw).split(RS):
                    if part:
                        self._dispatch(json.loads(part))
        finally:
            pt.cancel()
            for f in self.pending.values():
                if not f.done():
                    f.set_exception(HubError("connection closed"))
            self.pending.clear()

    async def close(self) -> None:
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:  # noqa: BLE001
                pass


@dataclass
class RootFeed:
    root: str
    contract: fc.Contract
    builder: CandleBuilder
    contract_id: str | None = None
    quote: dict = field(default_factory=dict)          # last, bid, ask, exchange_ts, received_at
    last_market_msg: datetime | None = None
    subscribed: bool = False
    subscribe_error: str | None = None
    last_publish: float = 0.0


class LiveStream:
    """Keeps a live feed for each monitored product: quotes, trades -> candles, status, gaps, backfill, rollover."""

    def __init__(self, projectx, roots: list[str], *, rtc_url: str = DEFAULT_RTC, stale_seconds: float = 30.0,
                 broadcaster=None, on_bar_close: Callable[[str, dict], Awaitable[None] | None] | None = None,
                 now: Callable[[], datetime] | None = None, connect: Callable | None = None, publish_interval: float = 0.25):
        self.projectx = projectx
        self.rtc_url = rtc_url.rstrip("/")
        self.stale_seconds = stale_seconds
        self.broadcaster = broadcaster
        self.on_bar_close = on_bar_close
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._connect = connect
        self.publish_interval = publish_interval
        self.clocks: dict[str, FuturesClock] = {}
        self.feeds: dict[str, RootFeed] = {}
        for r in roots:
            self._new_feed(r)
        self.state = "stopped"                          # stopped | connecting | connected | disconnected
        self.state_reason = "Live stream not started."
        self.connected_since: datetime | None = None
        self.disconnected_since: datetime | None = None
        self.gaps: list[dict] = []                      # {from, to, seconds, backfill}
        self.reconnects = 0
        self.last_error: str | None = None
        self._hub: MarketHub | None = None
        self._task: asyncio.Task | None = None
        self._ticker: asyncio.Task | None = None

    # ---------------- setup ----------------

    def clock(self, root: str) -> FuturesClock:
        if root not in self.clocks:
            self.clocks[root] = FuturesClock(fc.get(root))
        return self.clocks[root]

    def _new_feed(self, root: str, on: date | None = None) -> RootFeed:
        today = on or self._now().astimezone(fc.CT).date()
        c = fc.front_contract(root, today)
        f = RootFeed(root=root, contract=c, builder=CandleBuilder(c.spec, self.clock(root)))
        self.feeds[root] = f
        return f

    def feed_for(self, contract_code: str) -> RootFeed | None:
        return next((f for f in self.feeds.values() if f.contract.code == contract_code), None)

    @property
    def hub_url(self) -> str:
        return f"{self.rtc_url}/hubs/market".replace("https://", "wss://").replace("http://", "ws://")

    # ---------------- lifecycle ----------------

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())
        self._ticker = asyncio.create_task(self._tick_loop())

    async def stop(self) -> None:
        for t in (self._task, self._ticker):
            if t:
                t.cancel()
        if self._hub:
            await self._hub.close()
        self._set_state("stopped", "Live stream stopped.")

    def _set_state(self, state: str, reason: str) -> None:
        now = self._now()
        if state == "connected" and self.state != "connected":
            self.connected_since = now
        if state in ("disconnected", "connecting") and self.state == "connected":
            self.disconnected_since = now
        self.state, self.state_reason = state, reason
        self._publish_status()

    async def _resolve(self) -> None:
        for f in self.feeds.values():
            if not f.contract_id:
                c = await self.projectx.find_contract(f.contract.short_code)
                f.contract_id = str(c["id"])

    async def _run(self) -> None:
        attempt = 0
        while True:
            try:
                self._set_state("connecting", "Connecting to the TopstepX market hub…")
                await self._resolve()
                token = await self.projectx.token()
                hub = MarketHub(f"{self.hub_url}?access_token={token}", self._on_event, connect=self._connect)
                self._hub = hub
                await hub.open()
                for f in self.feeds.values():
                    f.subscribed, f.subscribe_error = False, None
                    for m in ("SubscribeContractQuotes", "SubscribeContractTrades"):
                        fut = await hub.invoke(m, f.contract_id)
                        fut.add_done_callback(lambda fu, f=f, m=m: self._sub_result(f, m, fu))
                self._set_state("connected", "Connected to the TopstepX market hub.")
                attempt = 0
                asyncio.create_task(self._after_connect())
                await hub.run()
                raise HubError("connection closed by the server")
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - every failure means: show DISCONNECTED, back off, retry
                self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
                if "401" in str(e) or "Unauthorized" in str(e):
                    getattr(self.projectx, "invalidate_token", lambda: None)()
                wait = BACKOFF[min(attempt, len(BACKOFF) - 1)]
                attempt += 1
                self.reconnects += 1
                self._set_state("disconnected", f"TopstepX market hub disconnected ({self.last_error}). Retrying in {wait} s. "
                                                "No live signals until it reconnects.")
                await asyncio.sleep(wait)

    def _sub_result(self, f: RootFeed, method: str, fut: asyncio.Future) -> None:
        if fut.cancelled():
            return
        err = fut.exception()
        if err:
            f.subscribe_error = f"{method} refused: {err}"
            log.warning("TopstepX %s for %s refused: %s", method, f.contract.code, err)
        elif method == "SubscribeContractTrades":
            f.subscribed = True

    async def _after_connect(self) -> None:
        """Backfill every feed from TopstepX REST bars: since the last bar we have, or the last 2 hours on first connect."""
        now = self._now()
        gap_from = self.disconnected_since
        for f in self.feeds.values():
            have = next(reversed(f.builder.bars), None) if f.builder.bars else None
            since = (have - timedelta(minutes=1)) if have else now - timedelta(hours=2)
            try:
                hist = await self.projectx.bars(f.contract.short_code, 1, since, now)
                res = f.builder.merge_history(hist, now)
                res["missing_after"] = len(f.builder.missing_minutes(since, minute_start(now)))
            except Exception as e:  # noqa: BLE001
                res = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
            if gap_from:
                self.gaps.append({"from": gap_from.isoformat(), "to": now.isoformat(), "seconds": round((now - gap_from).total_seconds()),
                                  "contract": f.contract.code, "backfill": res})
                self.gaps = self.gaps[-50:]
        self.disconnected_since = None
        self._publish_status()

    # ---------------- events ----------------

    def _on_event(self, target: str, args: list) -> None:
        if len(args) < 2:
            return
        cid, data = str(args[0]), args[1]
        f = next((x for x in self.feeds.values() if x.contract_id == cid), None)
        if f is None:
            return
        now = self._now()
        f.last_market_msg = now
        if target == "GatewayQuote" and isinstance(data, dict):
            q = f.quote
            for src, dst in (("lastPrice", "last"), ("bestBid", "bid"), ("bestAsk", "ask")):
                if data.get(src) is not None:
                    q[dst] = float(data[src])
            q["exchange_ts"] = (_parse_ts(data.get("timestamp")) or _parse_ts(data.get("lastUpdated")) or now).isoformat()
            q["received_at"] = now.isoformat()
            self._maybe_publish(f)
        elif target == "GatewayTrade":
            for t in (data if isinstance(data, list) else [data]):
                if not isinstance(t, dict) or t.get("price") is None:
                    continue
                ts = _parse_ts(t.get("timestamp")) or now
                r = f.builder.add_trade(float(t["price"]), float(t.get("volume") or 0), ts, t.get("type"))
                if r["kind"] in ("new", "update", "revised") and ts.isoformat() >= (f.quote.get("trade_ts") or ""):
                    # the newest trade by EXCHANGE time sets the last price; a late print never moves it backwards
                    f.quote.update({"last": r["bar"]["close"] if r["bar"]["last_ts"] == ts else f.quote.get("last"),
                                    "trade_ts": ts.isoformat(), "received_at": now.isoformat()})
            self._maybe_publish(f)

    # ---------------- clock loop: bar closes, staleness, rollover ----------------

    async def _tick_loop(self) -> None:
        last_roll_check = 0.0
        while True:
            await asyncio.sleep(1)
            try:
                await self.tick()
                if time.monotonic() - last_roll_check > 60:
                    last_roll_check = time.monotonic()
                    await self.check_rollover()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("live stream tick failed")

    async def tick(self) -> list[tuple[str, dict]]:
        now = self._now()
        closed = []
        for f in self.feeds.values():
            for b in f.builder.close_due(now):
                closed.append((f.root, b))
                if self.broadcaster:
                    self.broadcaster.publish({"type": "futures_bar_closed", "data": {"root": f.root, "contract": f.contract.code,
                                                                                     "ts": b["ts"].isoformat(), "source": SOURCE}})
                if self.on_bar_close:
                    res = self.on_bar_close(f.root, b)
                    if asyncio.iscoroutine(res):
                        asyncio.create_task(res)
        return closed

    async def check_rollover(self) -> list[str]:
        """Switch a product to the new front contract after its roll date; reconnects so subscriptions follow."""
        today = self._now().astimezone(fc.CT).date()
        rolled = []
        for root, f in list(self.feeds.items()):
            if fc.front_contract(root, today).code != f.contract.code:
                old = f.contract.code
                nf = self._new_feed(root, today)
                rolled.append(f"{old}->{nf.contract.code}")
        if rolled and self._task:
            log.info("TopstepX stream rolled %s; reconnecting", rolled)
            if self._hub:
                await self._hub.close()                 # _run reconnects and subscribes to the new contracts
        return rolled

    # ---------------- status ----------------

    def status_of(self, root: str) -> dict:
        """Data-integrity status for one product: LIVE only when connected, subscribed and receiving data during the session."""
        f = self.feeds.get(root)
        now = self._now()
        if f is None:
            return {"status": "unavailable", "reason": f"{root} isn't streamed."}
        base = {"source": SOURCE, "contract": f.contract.code, "contract_id": f.contract_id, "price": f.quote.get("last"),
                "bid": f.quote.get("bid"), "ask": f.quote.get("ask"),
                "exchange_ts": max([t for t in (f.quote.get("exchange_ts"), f.quote.get("trade_ts")) if t], default=None),
                "trade_exchange_ts": f.quote.get("trade_ts"), "quote_exchange_ts": f.quote.get("exchange_ts"),
                "received_at": f.quote.get("received_at"), "stream_state": self.state, "stats": f.builder.stats.to_dict()}
        if self.state != "connected":
            return {**base, "status": "disconnected", "reason": self.state_reason}
        if f.subscribe_error:
            return {**base, "status": "disconnected", "reason": f"Subscription refused by TopstepX ({f.subscribe_error}). Check that your "
                                                                 "ProjectX API Access subscription includes market data."}
        if self.clock(root).window_at(now) is None:
            return {**base, "status": "historical", "reason": "Market closed. Connected to TopstepX; waiting for the next session."}
        silent = (now - f.last_market_msg).total_seconds() if f.last_market_msg else None
        if silent is None or silent > self.stale_seconds:
            return {**base, "status": "stale", "silent_seconds": round(silent) if silent is not None else None,
                    "reason": f"Connected, but no market data for {round(silent) if silent is not None else 'any'} seconds during the session."}
        return {**base, "status": "realtime", "silent_seconds": round(silent, 1), "reason": "Live from the TopstepX market hub."}

    def summary(self) -> dict:
        return {"state": self.state, "reason": self.state_reason, "connected_since": self.connected_since and self.connected_since.isoformat(),
                "reconnects": self.reconnects, "last_error": self.last_error, "gaps": self.gaps[-10:][::-1], "hub": self.hub_url,
                "feeds": {r: self.status_of(r) for r in self.feeds}}

    def _publish_status(self) -> None:
        if self.broadcaster:
            self.broadcaster.publish({"type": "futures_stream", "data": {"state": self.state, "reason": self.state_reason}})

    def _maybe_publish(self, f: RootFeed) -> None:
        if not self.broadcaster or time.monotonic() - f.last_publish < self.publish_interval:
            return
        f.last_publish = time.monotonic()
        bar = next(reversed(f.builder.bars.values())).to_dict() if f.builder.bars else None
        st = self.status_of(f.root)
        self.broadcaster.publish({"type": "futures_live", "data": {
            "root": f.root, "contract": f.contract.code, "source": SOURCE, "status": st["status"],
            "price": st["price"], "bid": st["bid"], "ask": st["ask"], "exchange_ts": st["exchange_ts"], "received_at": st["received_at"],
            "bar": {**bar, "ts": int(bar["ts"].timestamp())} if bar else None}})
