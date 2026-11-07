"""Every Stage 2-10 API through the real app, with a fake provider serving synthetic bars."""
import asyncio
import io
from datetime import date

import cv2
import httpx
import pytest

from app.main import create_app
from app.market_data.types import Timeframe

from .chart_image import render
from .fakes import FakeProvider, always_open_clock
from .synth import intraday


class BarProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        for i, s in enumerate(["SPY", "QQQ", "AAPL", "TSLA", "NVDA"]):
            self.history[s] = intraday(symbol=s, days=12, seed=20 + i, vol=0.003, start=date(2026, 8, 3))

    async def get_recent_bars(self, symbols):
        return {s: self.history[s][-3:] for s in symbols if s in self.history}

    async def get_bars(self, symbol, timeframe, start, end=None):
        bars, notes = await super().get_bars(symbol, timeframe, start, end)
        return [b.model_copy(update={"timeframe": timeframe.value}) for b in bars], notes


@pytest.fixture
async def client(settings):
    settings.anthropic_api_key = None
    prov = BarProvider()
    app = create_app(settings, provider=prov, clock=always_open_clock(), start_loops=False)
    async with app.router.lifespan_context(app):
        app.state.analysis._ttl = lambda tf: 3600
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=120, headers={"X-Study-Terminal": "1"}) as c:
            yield c, app, prov


async def test_analysis_signals_and_explain(client):
    c, app, _ = client
    a = (await c.get("/api/analysis/TSLA", params={"timeframes": "5Min"})).json()
    snap = a["snapshots"]["5Min"]
    assert snap["available"] and snap["session"]["vwap"] and a["chart"]["bars"] and "ema9" in a["chart"]["series"]
    sig = (await c.get("/api/signals/TSLA", params={"timeframe": "5Min"})).json()
    assert sig["symbol"] == "TSLA" and "action" in sig
    ex = (await c.get("/api/ai/explain/TSLA")).json()
    assert ex["sections"][0]["heading"] == "The big picture"


async def test_assistant_is_grounded_and_honest(client):
    c, app, prov = client
    r = (await c.post("/api/ai/ask", json={"question": "Why is this stock moving?", "symbol": "TSLA"})).json()
    assert "don't have a news feed" in r["answer"] and r["engine"].startswith("Built-in")
    r = (await c.post("/api/ai/ask", json={"question": "Should I buy this right now?"})).json()
    assert "won't guess" in r["answer"]  # no symbol, no screen -> refuses to guess
    r = (await c.post("/api/ai/ask", json={"question": "Should I sell?", "symbol": "AAPL"})).json()
    assert "no paper position" in r["answer"]


async def test_scanner_ranks_watchlist(client):
    c, app, _ = client
    res = (await c.post("/api/scanner/run", json={"sources": ["watchlist"], "min_market_cap": None})).json()
    assert res["results"] or res["rejected"]
    for r in res["results"]:
        assert "rank_components" in r and r["rank_score"] >= 0


async def test_backtest_walk_forward_calibrates_signals(client):
    c, app, _ = client
    bt = (await c.post("/api/backtest", json={"symbols": ["TSLA", "NVDA"], "mode": "backtest",
                                              "params": {"rvol_min": 0, "vol_ratio_min": 0}})).json()
    assert bt["metrics"]["trades"] >= 1 and "Survivorship" in " ".join(bt["notes"])
    wf = (await c.post("/api/backtest", json={"symbols": ["TSLA", "NVDA", "AAPL"], "mode": "walk_forward", "train_sessions": 6,
                                              "test_sessions": 3, "params": {"rvol_min": 0, "vol_ratio_min": 0},
                                              "grid": {"target_r": [2.0]}})).json()
    assert wf["out_of_sample"] is True
    cal = (await c.get("/api/calibration")).json()
    assert cal and all(k.endswith("|5Min") for k in cal)
    runs = (await c.get("/api/backtest/runs")).json()
    assert {r["kind"] for r in runs} >= {"backtest", "walk_forward"}
    ml = (await c.post("/api/ml/train")).json()
    assert ml["deployed"] is False  # small synthetic sample: the model must refuse to deploy


async def test_settings_apply_live_and_risk_limits(client):
    c, app, prov = client
    v = (await c.put("/api/settings", json={"risk.max_per_trade_pct": 1.0, "risk.max_consecutive_losses": 2})).json()["values"]
    assert v["risk.max_per_trade_pct"] == 1.0 and app.state.paper.risk.max_per_trade_pct == 1.0
    assert (await c.put("/api/settings", json={"risk.max_per_trade_pct": "lots"})).status_code == 422
    assert (await c.put("/api/settings", json={"nope": 1})).status_code == 422
    acct = (await c.get("/api/paper/account")).json()
    assert "week_pnl" in acct and acct["max_consecutive_losses"] == 2


async def test_alerts_dedupe(client):
    c, app, _ = client
    a = app.state.alerts
    assert a.emit("entry", "high", "t", "b", key="k", fingerprint="f1")
    assert not a.emit("entry", "high", "t", "b", key="k", fingerprint="f1")   # duplicate suppressed
    assert a.emit("entry", "high", "t", "b2", key="k", fingerprint="f2")      # material change
    hist = (await c.get("/api/alerts")).json()
    assert len(hist["alerts"]) == 2 and hist["suppressed_duplicates"] == 1


async def test_learning_flow(client):
    c, app, _ = client
    ls = (await c.get("/api/learn/lessons")).json()
    assert len(ls) >= 18 and any(l["module"] == "options" for l in ls)
    lesson = (await c.get("/api/learn/lessons/risk")).json()
    assert "answer" not in lesson["quiz"][0]  # answers aren't sent to the browser
    res = (await c.post("/api/learn/lessons/risk/quiz", json={"answers": [1, 0]})).json()
    assert res["score"] == 100 and res["passed"]
    prog = (await c.get("/api/learn/progress")).json()
    assert "risk" in prog["completed"] and "R" in prog["known_terms"]
    ex = (await c.post("/api/learn/exercise")).json()
    ans = (await c.post(f"/api/learn/exercise/{ex['id']}", json={"choice": ex["options"][0]["id"]})).json()
    assert "what_happened" in ans and ans["future"]
    assert "VWAP" in (await c.get("/api/learn/glossary", params={"q": "vwap"})).json()


async def test_monitoring_pause_resume(client):
    c, app, prov = client
    prov.stream.push("SPY", 600.0)
    s = (await c.post("/api/monitoring/pause")).json()
    assert s["monitoring_enabled"] is False
    spy = next(x for x in (await c.get("/api/market/live")).json()["symbols"] if x["symbol"] == "SPY")
    assert spy["label"]["status"] == "unavailable" and "paused" in spy["label"]["reason"]
    assert (await c.post("/api/monitoring/resume")).json()["monitoring_enabled"] is True


async def test_screen_requires_consent_and_analyzes_uploads(client):
    c, app, _ = client
    assert (await c.post("/api/screen/start", json={"target": {"kind": "monitor", "id": 1}})).status_code == 400
    img, _ = render(ticker="TSLA", tf="5")
    ok, png = cv2.imencode(".png", img)
    r = (await c.post("/api/screen/analyze-image", files={"file": ("c.png", io.BytesIO(png.tobytes()), "image/png")})).json()
    assert r["observation"]["ticker"] == "TSLA" and r["fusion"]["ticker"] == "TSLA"
    assert r["fusion"]["ticker_confirmed"] is True and "discrepancy" in r["fusion"]  # synthetic $359 vs synthetic market ~$100
    st = (await c.get("/api/screen/status")).json()
    assert st["state"] == "off" and "never saved" in st["privacy"]
