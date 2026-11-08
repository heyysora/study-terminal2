"""Screen recognition for futures charts (TopstepX and futures on TradingView), on synthetic chart images.
Real TopstepX screenshots were not available while building this; see docs/TOPSTEPX.md."""
import pytest

from app.screen.platforms import ADAPTERS, futures_candidates, pick
from app.screen.vision import analyze_image, guess_platform, title_looks_like_trading

from .chart_image import render


def es_chart(ticker="MESZ6", price=7402.25, **kw):
    return render(ticker=ticker, tf="5", price=price, line_price=7410.0, exchange="CME", pmin=7380.0, pmax=7420.0, step=5.0,
                  header_extra="VWAP  Volume", **kw)


def test_platform_pick_prefers_topstepx_over_tradingview():
    assert pick("TopstepX - Google Chrome", "chrome.exe").id == "topstepx"
    assert pick("MESZ2026 7,402.25 ▼ −0.5% Unnamed - TradingView", "chrome.exe").id == "tradingview"
    assert pick("anything", None, "topstepx").id == "topstepx"          # your explicit choice wins
    assert guess_platform("TopstepX", None) == "topstepx"
    assert title_looks_like_trading("TopstepX | Trade", "msedge.exe")      # privacy guard lets the TopstepX tab through


def test_futures_candidates_ignore_stock_tickers():
    tv = ADAPTERS["tradingview"]
    c = futures_candidates(["AAPL", "MNQZ6", "/ES", "VWAP"], tv)
    assert [x.contract.code if x.contract else x.root for x in c] == ["MNQZ26", "ES"]
    assert futures_candidates(["ES", "TSLA"], tv) == []                   # bare 'ES' is also a stock; never assumed


@pytest.mark.parametrize("ticker,code", [("MESZ6", "MESZ26"), ("ESZ2026", "ESZ26"), ("/MNQ", None)])
def test_topstepx_chart_reads_contract_timeframe_and_price(ticker, code):
    img, _ = es_chart(ticker=ticker)
    r = analyze_image(img, title="TopstepX - Google Chrome", process="chrome.exe")
    assert r["platform"] == "topstepx" and r["asset_class"] == "futures"
    assert (r["futures"]["contract"] == code) if code else (r["futures"]["continuous"] and r["futures"]["root"] == "MNQ")
    assert r["timeframe"] == "5Min"
    assert r["visible_price"] == pytest.approx(7402.25)
    assert r["position_on_screen"] is None                                # account reading is off by default


def test_topstepx_never_falls_back_to_a_stock_ticker():
    img, _ = es_chart(ticker="Chart")
    r = analyze_image(img, title="TopstepX", process="chrome.exe")
    assert r["ticker"] is None and "ticker" in r["could_not_recognize"]


def test_account_panel_only_read_when_enabled():
    img, _ = es_chart(extra_text=[(400, 700, "Position"), (520, 700, "2"), (650, 700, "P&L"), (740, 700, "125.00")])
    off = analyze_image(img, title="TopstepX", process="chrome.exe")
    on = analyze_image(img, title="TopstepX", process="chrome.exe", read_account=True)
    assert off["position_on_screen"] is None
    assert on["position_on_screen"] and on["position_on_screen"]["verified"] is False


def test_equity_tradingview_unchanged():
    img, _ = render(ticker="TSLA", tf="5", price=359.40, line_price=362.0, seed=3)
    r = analyze_image(img, title="TSLA 359.40 ▲ +4.61% Unnamed - Google Chrome", process="chrome.exe")
    assert r["ticker"] == "TSLA" and r["asset_class"] == "equities" and r["futures"] is None
