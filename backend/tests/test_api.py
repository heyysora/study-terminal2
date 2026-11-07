"""End-to-end: real FastAPI app, real SQLite, real monitor + paper simulator,
with the market data provider swapped for a hand-driven fake. No network, no keys."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import create_app
from app.market_data.types import Timeframe

from .fakes import FakeProvider, always_open_clock, bar


async def settle():
    await asyncio.sleep(0.05)


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_launches_without_any_brokerage_or_keys(settings):
    app = create_app(settings, provider=FakeProvider(), clock=always_open_clock())
    async with app.router.lifespan_context(app), client_for(app) as c:
        h = (await c.get("/api/health")).json()
        assert h["brokerage_connected"] is False and h["brokerage_required"] is False
        assert h["paper_account"]["equity"] == 25_000
        assert h["market_data"]["provider"]["requires_api_key"] is False
        wl = (await c.get("/api/watchlists")).json()
        assert wl[0]["symbols"] == ["SPY", "QQQ", "AAPL", "TSLA", "NVDA"]


async def test_stream_monitoring_labels_and_full_paper_trade(settings):
    prov = FakeProvider()
    app = create_app(settings, provider=prov, clock=always_open_clock())
    async with app.router.lifespan_context(app), client_for(app) as c:
        await settle()
        assert prov.stream.symbols == {"SPY", "QQQ", "AAPL", "TSLA", "NVDA"}

        spy = next(x for x in (await c.get("/api/market/live")).json()["symbols"] if x["symbol"] == "SPY")
        assert spy["label"]["status"] == "unavailable" and spy["signals"]["allowed"] is False

        prov.stream.push("SPY", 600.0, bid=599.98, ask=600.02)
        spy = next(x for x in (await c.get("/api/market/live")).json()["symbols"] if x["symbol"] == "SPY")
        assert spy["label"]["status"] == "near_realtime" and spy["signals"]["allowed"] is True
        assert spy["last"]["price"] == 600.0

        order = {"symbol": "SPY", "side": "buy", "qty": 41, "type": "market", "stop_loss": 597.0, "take_profit": 606.0}
        pv = (await c.post("/api/paper/orders/preview", json=order)).json()
        assert pv["preview"]["ok"] and pv["preview"]["reward_risk"] == pytest.approx(1.99, abs=0.02)
        assert pv["price"]["status"] == "near_realtime"

        r = await c.post("/api/paper/orders", json=order)
        assert r.status_code == 400 and "confirm" in r.json()["detail"]
        r = await c.post("/api/paper/orders", json={**order, "confirm": True})
        assert r.status_code == 201
        filled = r.json()["order"]
        assert filled["status"] == "filled" and filled["fill_price"] == 600.02  # bought at the ask

        pos = (await c.get("/api/paper/positions")).json()
        assert pos[0]["qty"] == 41 and pos[0]["stop_loss"] == 597.0 and pos[0]["take_profit"] == 606.0

        prov.stream.push("SPY", 598.0)
        acct = (await c.get("/api/paper/account")).json()
        assert acct["unrealized_pnl"] == pytest.approx((598.0 - 600.02) * 41, abs=0.01)

        prov.stream.push("SPY", 596.5)  # through the stop
        assert (await c.get("/api/paper/positions")).json() == []
        fills = (await c.get("/api/paper/fills")).json()
        assert fills[0]["role"] == "stop_loss" and fills[0]["price"] == 596.5
        assert fills[0]["price_basis"] == "near_realtime"
        acct = (await c.get("/api/paper/account")).json()
        assert acct["realized_pnl"] == pytest.approx((596.5 - 600.02) * 41, abs=0.01)
        orders = (await c.get("/api/paper/orders")).json()
        assert {o["status"] for o in orders} == {"filled", "canceled"}  # target canceled by OCO


async def test_rejections_are_explained(settings):
    prov = FakeProvider()
    app = create_app(settings, provider=prov, clock=always_open_clock())
    async with app.router.lifespan_context(app), client_for(app) as c:
        await settle()
        r = await c.post("/api/paper/orders", json={"symbol": "SPY", "side": "buy", "qty": 10, "confirm": True})
        assert r.status_code == 422  # no price yet and no stop
        detail = r.json()["detail"]["message"]
        assert "stop loss" in detail and "No usable price" in detail
        prov.stream.push("SPY", 600.0)
        r = await c.post("/api/paper/orders", json={"symbol": "SPY", "side": "buy", "qty": 500, "stop_loss": 590, "confirm": True})
        assert r.status_code == 422 and r.json()["detail"]["preview"]["suggested_qty"] == 12
        size = (await c.get("/api/paper/size", params={"entry": 600, "stop": 590})).json()
        assert size["shares"] == 12 and size["risk_dollars"] == 125.0


async def test_poll_only_mode_labels_polling_and_fills_from_bars(settings):
    settings.live_mode = "poll_only"
    prov = FakeProvider()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    prov.recent["TSLA"] = [bar("TSLA", now - timedelta(minutes=1), 400, 401, 399, 400.5)]
    app = create_app(settings, provider=prov, clock=always_open_clock())
    async with app.router.lifespan_context(app), client_for(app) as c:
        await settle()
        assert prov.stream is None
        tsla = next(x for x in (await c.get("/api/market/live")).json()["symbols"] if x["symbol"] == "TSLA")
        assert tsla["label"]["status"] == "polling" and tsla["signals"]["fastest_timeframe"] == "5Min"

        r = await c.post("/api/paper/orders", json={"symbol": "TSLA", "side": "buy", "qty": 20, "type": "limit",
                                                    "limit_price": 398.0, "stop_loss": 393.0, "confirm": True})
        assert r.json()["order"]["status"] == "open"
        # a new 1-min bar trades through the limit
        prov.recent["TSLA"].append(bar("TSLA", now + timedelta(minutes=1), 399, 399.5, 397.2, 397.8))
        await app.state.monitor.poll_once()
        pos = (await c.get("/api/paper/positions")).json()
        assert pos and pos[0]["avg_price"] == 398.0


async def test_paper_account_survives_restart(settings):
    prov = FakeProvider()
    app = create_app(settings, provider=prov, clock=always_open_clock())
    async with app.router.lifespan_context(app), client_for(app) as c:
        await settle()
        prov.stream.push("NVDA", 200.0)
        await c.post("/api/paper/orders", json={"symbol": "NVDA", "side": "sell", "qty": 50, "stop_loss": 202.5, "confirm": True})
    prov2 = FakeProvider()
    app2 = create_app(settings, provider=prov2, clock=always_open_clock())
    async with app2.router.lifespan_context(app2), client_for(app2) as c:
        await settle()
        pos = (await c.get("/api/paper/positions")).json()
        assert pos[0]["symbol"] == "NVDA" and pos[0]["qty"] == -50 and pos[0]["stop_loss"] == 202.5
        assert "NVDA" in prov2.stream.symbols  # positions are always monitored
        prov2.stream.push("NVDA", 203.0)  # stop still works after restart
        assert (await c.get("/api/paper/positions")).json() == []
        assert (await c.post("/api/paper/reset", json={})).status_code == 400
        acct = (await c.post("/api/paper/reset", json={"confirm": True, "starting_cash": 5000})).json()
        assert acct["equity"] == 5000 and (await c.get("/api/paper/fills")).json() == []


async def test_bars_quote_and_unknown_symbols(settings):
    prov = FakeProvider()
    t0 = datetime(2026, 11, 6, 14, 30, tzinfo=timezone.utc)
    prov.history["AMD"] = [bar("AMD", t0, 1, 2, 0.5, 1.5, tf=Timeframe.M5)]
    app = create_app(settings, provider=prov, clock=always_open_clock())
    async with app.router.lifespan_context(app), client_for(app) as c:
        r = (await c.get("/api/market/bars/AMD", params={"timeframe": "5Min", "days": 3})).json()
        assert r["count"] == 1 and r["label"]["status"] == "historical" and r["notes"] == ["fake note"]
        assert app.state.monitor.cached_bars("AMD", "5Min", t0 - timedelta(hours=1))
        assert (await c.get("/api/market/bars/NOPE")).status_code == 404
        assert (await c.get("/api/market/bars/bad symbol!")).status_code == 422
        q = (await c.get("/api/market/quote/ZZZ")).json()
        assert q["label"]["status"] == "unavailable"


def test_ws_hello_and_origin_check(settings):
    app = create_app(settings, provider=FakeProvider(), clock=always_open_clock())
    with TestClient(app) as c:
        with c.websocket_connect("/ws/market") as ws:
            hello = json.loads(ws.receive_text())
            assert hello["type"] == "hello" and hello["data"]["paper_account"]["equity"] == 25_000
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/market", headers={"origin": "https://evil.example"}) as ws:
                ws.receive_text()


def test_ws_accepts_its_own_served_origin(settings):
    app = create_app(settings, provider=FakeProvider(), clock=always_open_clock())
    with TestClient(app) as c:
        with c.websocket_connect("/ws/market", headers={"origin": "http://testserver"}) as ws:
            assert json.loads(ws.receive_text())["type"] == "hello"
