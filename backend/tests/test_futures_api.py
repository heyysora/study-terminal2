"""Futures API through the real app (fake provider serving real ES bars)."""
import io
from pathlib import Path

import cv2
import httpx
import pandas as pd
import pytest

from app.main import create_app
from app.market_data.types import Bar

from .fakes import FakeProvider, always_open_clock
from .test_futures_screen import es_chart

FIX = Path(__file__).parent / "fixtures" / "es_5m_2026-10-25_11-06.csv"


class FutProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        df = pd.read_csv(FIX, index_col=0, parse_dates=True)
        bars = [Bar(symbol="X", timeframe="5Min", ts=t.to_pydatetime(), open=r.Open, high=r.High, low=r.Low, close=r.Close, volume=r.Volume,
                    provider="fake", source="fixture") for t, r in df.iterrows()]
        for s in ("MESZ26.CME", "ESZ26.CME", "ES=F", "MES=F"):
            self.history[s] = bars


@pytest.fixture
async def client(settings):
    settings.anthropic_api_key = None
    app = create_app(settings, provider=FutProvider(), clock=always_open_clock(), start_loops=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=120,
                                     headers={"X-Study-Terminal": "1"}) as c:
            yield c, app


async def test_info_contract_and_analysis(client):
    c, app = client
    info = (await c.get("/api/futures/info")).json()
    assert {p["root"] for p in info["products"]} >= {"ES", "MES", "NQ", "MNQ", "YM", "MYM", "RTY", "CL", "GC"}
    assert info["prop"]["confirmed"] is False and "cannot enforce" in info["sim_only_note"]
    assert info["projectx_configured"] is False
    ci = (await c.get("/api/futures/contract/MES")).json()
    assert ci["spec"]["tick_value"] == 1.25 and ci["front"]["code"].startswith("MES")
    a = (await c.get("/api/futures/analysis/MESZ26")).json()
    assert a["contract"]["code"] == "MESZ26" and a["levels"]["prev_day_high"] is not None
    # Yahoo-style data is never treated as live: no LONG/SHORT
    assert a["data"]["status"] in ("delayed", "stale", "historical") and a["signal"]["action"] == "NO TRADE"
    assert (await c.get("/api/futures/analysis/AAPL")).status_code == 404


async def test_risk_profile_round_trip_and_confirmation(client):
    c, _ = client
    r = (await c.post("/api/futures/risk/preset", json={"preset_id": "topstep_tc_100k"})).json()
    assert r["max_loss_limit"] == 3000 and r["confirmed"] is False
    r = (await c.put("/api/futures/risk/prop", json={"values": {"daily_loss_limit": 2000}, "confirm": True})).json()
    assert r["daily_loss_limit"] == 2000 and r["confirmed"] is True and r["confirmed_at"]
    p = (await c.put("/api/futures/risk/personal", json={"max_daily_loss_usd": 400})).json()
    assert p["max_daily_loss_usd"] == 400
    info = (await c.get("/api/futures/info")).json()
    assert info["prop"]["daily_loss_limit"] == 2000 and info["personal"]["max_daily_loss_usd"] == 400
    assert (await c.post("/api/futures/risk/preset", json={"preset_id": "nope"})).status_code == 404


async def test_paper_orders_need_confirmation_and_reset_needs_confirm(client):
    c, _ = client
    body = {"contract": "MESZ26", "side": 1, "qty": 1, "type": "market", "bracket": {"stop": 7390.0, "targets": []}}
    assert (await c.post("/api/futures/paper/orders", json=body)).status_code == 403
    pv = (await c.post("/api/futures/paper/preview", json=body)).json()
    assert pv["ok"] is False and pv["problems"]          # delayed/closed data: the simulator refuses live fills
    assert (await c.post("/api/futures/paper/reset", json={})).status_code == 400
    assert (await c.post("/api/futures/paper/reset", json={"confirm": True})).json()["ok"]
    j = (await c.get("/api/futures/journal")).json()
    assert j["summary"]["trades"] == 0


async def test_screen_upload_routes_futures_to_futures_fusion(client):
    c, app = client
    img, _ = es_chart(ticker="MESZ6", price=7402.25)
    ok, png = cv2.imencode(".png", img)
    r = await c.post("/api/screen/analyze-image", files={"file": ("c.png", io.BytesIO(png.tobytes()), "image/png")},
                     data={"title": "TopstepX", "platform": "topstepx"})
    j = r.json()
    assert j["observation"]["platform"] == "topstepx" and j["observation"]["asset_class"] == "futures"
    fu = j["fusion"]
    assert fu["contract"] == "MESZ26" and fu["asset_class"] == "futures"
    assert any(ch["check"] == "price on the tick grid" and ch["ok"] for ch in fu["checks"])
    assert "can't place" in fu["sim_only_note"]
    plats = (await c.get("/api/screen/platforms")).json()
    assert {p["id"] for p in plats["platforms"]} == {"auto", "topstepx", "tradingview", "generic"}


async def test_projectx_not_configured_and_account_reading_gated(client):
    c, _ = client
    assert (await c.get("/api/futures/projectx/check")).json()["ok"] is False
    assert (await c.get("/api/futures/projectx/accounts")).status_code == 400


async def test_mentor_answers_futures_questions_with_futures_facts(client):
    c, _ = client
    r = (await c.post("/api/ai/ask", json={"question": "Should I go long here?", "symbol": "MESZ26"})).json()
    assert "MESZ26 data" in r["answer"] and "tick 0.25 = $1.25" in r["answer"]
    assert "can't see or change your real Topstep account" in r["answer"]
    assert "futures" in r["grounded_in"]
