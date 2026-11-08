"""Optional Chrome extension bridge.

The extension sends only the active TradingView tab's title and URL (no screenshots, no page contents,
no cookies). From those the app reads the symbol, price and (when the URL has it) the interval, then
runs the same market-data check and signal analysis as the screen copilot.

Security: off by default. When enabled, every request must carry the pairing token you copy from
Settings (X-Study-Token), compared in constant time. Only tradingview.com chart/symbol pages are accepted.
"""
from __future__ import annotations

import hmac
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import parse_qs, unquote, urlparse

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ..screen.vision import TITLE_PATTERNS, parse_number, tf_from_text

router = APIRouter(prefix="/api/extension", tags=["extension"])
ALLOWED_HOSTS = {"www.tradingview.com", "tradingview.com", "in.tradingview.com", "uk.tradingview.com", "ca.tradingview.com"}
ALLOWED_PATHS = re.compile(r"^/(chart|symbols)(/|$)")


def _store(request: Request):
    return request.app.state.settings_store


def _check(request: Request, token: str | None) -> None:
    st = _store(request)
    if not st.get("extension.enabled", False):
        raise HTTPException(403, "The Chrome extension bridge is turned off. Turn it on in Study Terminal > Settings.")
    want = st.get("extension.token", "") or ""
    if not want or not token or not hmac.compare_digest(want.encode(), token.encode()):
        raise HTTPException(401, "Wrong or missing pairing token. Copy it from Study Terminal > Settings > Chrome extension.")


@router.get("/pairing")
def pairing(request: Request):
    """For the app's own Settings page (same-origin only; other sites can't read this response)."""
    st = _store(request)
    if not st.get("extension.token"):
        st.update({"extension.token": secrets.token_urlsafe(24)})
    return {"enabled": bool(st.get("extension.enabled", False)), "token": st.get("extension.token"),
            "port": request.app.state.settings.port}


@router.post("/pairing/rotate")
def rotate(request: Request):
    _store(request).update({"extension.token": secrets.token_urlsafe(24)})
    return pairing(request)


class TabIn(BaseModel):
    title: str = Field(max_length=300)
    url: str = Field(max_length=2000)


def parse_tab(title: str, url: str) -> dict:
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS or not ALLOWED_PATHS.match(u.path or ""):
        raise HTTPException(400, "Only TradingView chart or symbol pages are accepted.")
    q = parse_qs(u.query)
    ticker = price = None
    for name, pat in TITLE_PATTERNS:
        m = pat.match(title.strip())
        if m and name == "tradingview":
            ticker, price = m.group(1), parse_number(m.group(2))
            break
    if ticker is None and q.get("symbol"):
        ticker = unquote(q["symbol"][0]).split(":")[-1].upper()
    if ticker is None:
        m = re.match(r"^/symbols/(?:[A-Z]+-)?([A-Z][A-Z0-9.\-]{0,9})/?", u.path or "")
        ticker = m.group(1) if m else None
    tf, note = (None, None)
    if q.get("interval"):
        iv = q["interval"][0]
        tf, note = tf_from_text({"D": "1D", "1D": "1D", "W": "1W"}.get(iv, iv))
    obs = {"ticker": ticker, "ticker_confidence": 0.95 if ticker else 0.0, "ticker_source": "Chrome extension (TradingView tab)",
           "ticker_candidates": [ticker] if ticker else [], "timeframe": tf.value if tf else None,
           "timeframe_note": note or (None if tf else "The tab's address doesn't include the chart interval; using your default timeframe."),
           "visible_price": price, "visible_price_source": "tab title" if price is not None else None, "drawn_levels": [],
           "platform": "tradingview", "source": "chrome-extension"}
    return obs


@router.post("/context")
async def context(body: TabIn, request: Request, x_study_token: str | None = Header(None)):
    _check(request, x_study_token)
    obs = parse_tab(body.title, body.url)
    s = request.app.state
    out = {"received_at": datetime.now(timezone.utc).isoformat(), "observation": obs}
    if obs["ticker"]:
        fusion = await s.screen.fuse(obs, None)
        out["fusion"] = fusion
    else:
        out["fusion"] = {"status": "Couldn't read a symbol from this tab."}
    s.extension_context = out
    s.monitor.broadcaster.publish({"type": "extension", "data": _brief(out)})
    return _brief(out)


@router.get("/status")
def status(request: Request, x_study_token: str | None = Header(None)):
    _check(request, x_study_token)
    ctx = getattr(request.app.state, "extension_context", None)
    return _brief(ctx) if ctx else {"connected": True, "note": "No TradingView tab seen yet."}


@router.get("/latest")
def latest(request: Request):
    """For the app's own UI (Copilot page)."""
    ctx = getattr(request.app.state, "extension_context", None)
    return _brief(ctx) if ctx else None


def _brief(ctx: dict) -> dict:
    f, o = ctx.get("fusion") or {}, ctx.get("observation") or {}
    b = f.get("best_signal") or {}
    return {"connected": True, "received_at": ctx.get("received_at"), "symbol": f.get("ticker") or o.get("ticker"),
            "timeframe": f.get("analysis_timeframe") or o.get("timeframe"), "timeframe_note": o.get("timeframe_note"),
            "tab_price": o.get("visible_price"), "market_price": f.get("market_price"), "price_diff_pct": f.get("price_diff_pct"),
            "data_status": (f.get("market_label") or {}).get("status"), "discrepancy": f.get("discrepancy"),
            "action": f.get("action"), "setup": b.get("setup_name"), "state": b.get("state"), "tradeable": b.get("tradeable"),
            "reasons": (f.get("reasons") or [])[:2], "status": f.get("status")}
