"""Phase 9: Chrome extension bridge. Off by default, token-protected, TradingView tabs only."""
import asyncio

import httpx
import pytest

from app.api.routes_extension import parse_tab
from app.main import create_app

from .fakes import FakeProvider, always_open_clock


def test_parse_tradingview_tab():
    o = parse_tab("AAPL 342.37 ▼ −0.52%", "https://www.tradingview.com/chart/abc123/?symbol=NASDAQ%3AAAPL&interval=5")
    assert (o["ticker"], o["visible_price"], o["timeframe"]) == ("AAPL", 342.37, "5Min")
    o = parse_tab("Apple Inc chart", "https://www.tradingview.com/chart/?symbol=NASDAQ%3AAAPL")
    assert o["ticker"] == "AAPL" and o["timeframe"] is None and "doesn't include the chart interval" in o["timeframe_note"]
    o = parse_tab("TSLA 359.40 ▲ +4.61%", "https://www.tradingview.com/chart/?interval=D")
    assert o["timeframe"] == "1Day"


@pytest.mark.parametrize("url", ["https://mail.google.com/mail/u/0/", "https://www.tradingview.com/accounts/settings/",
                                 "http://www.tradingview.com/chart/", "https://evil.example/chart/?symbol=AAPL",
                                 "https://tradingview.com.evil.example/chart/"])
def test_only_tradingview_chart_pages(url):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        parse_tab("AAPL 342.37 ▼ −0.52%", url)


async def test_bridge_is_off_by_default_and_needs_the_token(settings):
    prov = FakeProvider()
    app = create_app(settings, provider=prov, clock=always_open_clock())
    async with app.router.lifespan_context(app):
        tr = httpx.ASGITransport(app=app)
        ui = httpx.AsyncClient(transport=tr, base_url="http://127.0.0.1:8765", headers={"X-Study-Terminal": "1"})
        await asyncio.sleep(0.05)
        tab = {"title": "AAPL 200.05 ▲ +1.00%", "url": "https://www.tradingview.com/chart/?symbol=NASDAQ%3AAAPL&interval=5"}
        tok = (await ui.get("/api/extension/pairing")).json()["token"]
        assert len(tok) >= 30
        ext = httpx.AsyncClient(transport=tr, base_url="http://127.0.0.1:8765", headers={"X-Study-Token": tok})
        assert (await ext.post("/api/extension/context", json=tab)).status_code == 403          # off by default
        await ui.put("/api/settings", json={"extension.enabled": True})
        bad = httpx.AsyncClient(transport=tr, base_url="http://127.0.0.1:8765", headers={"X-Study-Token": "nope"})
        assert (await bad.post("/api/extension/context", json=tab)).status_code == 401
        prov.stream.push("AAPL", 200.0)
        r = await ext.post("/api/extension/context", json=tab)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["symbol"] == "AAPL" and b["tab_price"] == 200.05 and b["market_price"] == 200.0 and b["timeframe"] == "5Min"
        assert (await ext.get("/api/extension/status")).json()["symbol"] == "AAPL"
        new = (await ui.post("/api/extension/pairing/rotate")).json()["token"]
        assert new != tok and (await ext.get("/api/extension/status")).status_code == 401   # old token is dead
        # a web page on another site can't even send the request without the custom header
        anon = httpx.AsyncClient(transport=tr, base_url="http://127.0.0.1:8765")
        assert (await anon.post("/api/extension/context", json=tab)).status_code == 403
        for c in (ui, ext, bad, anon):
            await c.aclose()
