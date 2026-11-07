"""Screen intelligence on rendered chart screenshots with known ground truth."""
import pytest

from app.screen.capture import frame_change
from app.screen.vision import analyze_image, fit_price_axis, recognize, tf_from_text, Token

from .chart_image import render


@pytest.mark.parametrize("ticker,tf,expected_tf", [("TSLA", "5", "5Min"), ("NVDA", "15", "15Min"), ("AAPL", "1h", "1Hour"),
                                                    ("SPY", "D", "1Day"), ("META", "30", "30Min")])
def test_reads_ticker_timeframe_price_levels(ticker, tf, expected_tf):
    img, cols = render(ticker=ticker, tf=tf, price=359.40, line_price=362.0, seed=3)
    r = analyze_image(img, title="Some Browser", process="chrome.exe")
    assert r["ticker"] == ticker and r["timeframe"] == expected_tf
    assert r["visible_price"] == pytest.approx(359.40)
    assert len(r["drawn_levels"]) == 1 and r["drawn_levels"][0]["price_estimate"] == pytest.approx(362.0, abs=0.2)
    assert r["recent_candles"] == cols[-5:]
    assert set(r["indicators_visible"]) >= {"VWAP", "RSI"}
    assert r["could_not_recognize"] == []


def test_title_beats_ocr_for_tradingview():
    img, _ = render(ticker="XXXX", tf="5")
    r = analyze_image(img, title="TSLA 359.40 ▲ +4.61% Unnamed - Google Chrome", process="chrome.exe")
    assert r["platform"] == "tradingview" and r["ticker"] == "TSLA" and r["ticker_confidence"] >= 0.9


def test_reports_what_it_cannot_read():
    import numpy as np
    blank = np.full((600, 1000, 3), 20, np.uint8)
    r = analyze_image(blank, title="Notepad")
    assert r["ticker"] is None and "ticker" in r["could_not_recognize"] and "visible price" in r["could_not_recognize"]


def test_login_screen_is_blocked():
    img, _ = render(body_text="Enter your password to sign in")
    r = analyze_image(img, title="Broker")
    assert r["blocked"] and "nothing was kept" in r["reason"]


def test_timeframe_parsing_and_nearest():
    assert tf_from_text("5m")[0].value == "5Min" and tf_from_text("1H")[0].value == "1Hour"
    assert tf_from_text("3O")[0].value == "30Min"  # OCR O/0 confusion
    tf, note = tf_from_text("3")
    assert tf.value == "2Min" and "nearest" in note
    assert tf_from_text("RSI")[0] is None


def test_axis_fit_rejects_inverted_or_sparse():
    toks = [Token("100", 1, 950, y, 990, y + 10) for y in (100, 200)]
    assert fit_price_axis(toks, 1000) is None  # too few labels
    up = [Token(str(100 + i), 1, 950, 100 + 50 * i, 990, 110 + 50 * i) for i in range(4)]
    assert fit_price_axis(up, 1000) is None     # price rising downward = not a price axis


def test_change_detector():
    a, _ = render(seed=1)
    b, _ = render(seed=1)
    c, _ = render(seed=2)
    assert frame_change(a, b) == 0 and frame_change(a, c) > 1.5 and frame_change(None, a) == 255
