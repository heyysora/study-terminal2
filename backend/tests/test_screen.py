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


async def test_browser_tab_switch_stops_capture(monkeypatch):
    """H2: a consented browser window that switches to a non-chart tab is not captured or read."""
    import numpy as np

    from app.screen import capture as cap
    from app.screen.service import ScreenService
    from app.screen.vision import title_looks_like_trading

    class _Mon:
        def _event(self, *a):
            pass

        async def quote(self, sym):
            return {"last": None, "label": {}}

    class _Settings:
        def get(self, k, d=None):
            return d

    class _B:
        def publish(self, e):
            pass

    titles = iter(["Inbox (3) - you@example.com - Gmail - Google Chrome", "TSLA 359.40 ▲ +4.61% Unnamed - Google Chrome"])
    captured = []
    monkeypatch.setattr(cap, "window_title", lambda hwnd: next(titles))
    monkeypatch.setattr(cap, "capture", lambda t: (captured.append(1), (np.zeros((40, 40, 3), np.uint8), "test"))[1])
    svc = ScreenService(_Mon(), None, _Settings(), _B())
    svc.target = cap.Target(kind="window", id=1, title="TSLA chart - Google Chrome", process="chrome.exe")
    svc.state = "running"
    await svc.tick()
    assert svc.holding and not captured and "doesn't look like a chart" in svc.state_reason
    await svc.tick()
    assert not svc.holding and captured == [1]
    # desktop trading apps aren't subject to the browser rule; obvious non-trading titles are rejected
    assert title_looks_like_trading("thinkorswim [build 1985]", "thinkorswim.exe")
    assert not title_looks_like_trading("Chase Online - Account Summary - Google Chrome", "chrome.exe")


# ---------- regressions found on real TradingView screenshots (Phase 6) ----------
import numpy as np  # noqa: E402

from app.screen.vision import find_price_axis, last_price_tag  # noqa: E402


def _tok(text, cx, cy, w=50, h=14):
    return Token(text, 0.9, cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def test_unicode_digits_from_ocr_do_not_crash():
    assert tf_from_text("①") == (None, None)


def test_price_axis_found_in_the_middle_with_a_watchlist_to_its_right():
    # TradingView: axis at x~1210 of 1600, watchlist numbers further right
    axis = [_tok(f"{350 - k:.2f}", 1210, 60 + 37 * k) for k in range(15)]
    watch = [_tok(t, 1395, y) for t, y in (("7,376.86", 175), ("26,989.9", 205), ("25.64", 265), ("342.37", 361), ("63.41", 421))]
    fit, col = find_price_axis(axis + watch, 1600, 900)
    assert fit is not None and len(col) == 15 and all(t.cx == 1210 for t in col)
    assert abs(fit.price_at(60 + 37 * 4) - 346.0) < 0.01


def test_watchlist_alone_is_not_mistaken_for_an_axis():
    watch = [_tok(t, 1395, y) for t, y in (("7,376.86", 175), ("26,989.9", 205), ("25.64", 265), ("342.37", 361), ("63.41", 421))]
    assert find_price_axis(watch, 1600, 900)[0] is None


def test_price_tag_must_agree_with_axis():
    img = np.full((900, 1600, 3), 255, np.uint8)
    axis = [_tok(f"{350 - k:.2f}", 1210, 60 + 37 * k) for k in range(15)]
    fit, col = find_price_axis(axis, 1600, 900)
    # a red volume tag far from where its number would sit on the axis, and the real price tag
    vol, real = _tok("138.26", 1210, 787), _tok("342.35", 1210, 60 + 37 * 7.65)
    for t in (vol, real):
        img[int(t.y0) - 2:int(t.y1) + 2, int(t.x0) - 4:int(t.x1) + 4] = (60, 60, 230)
    price, _ = last_price_tag(img, axis + [vol, real], 1600, fit, col)
    assert price == 342.35


def test_legend_timeframe_beats_toolbar_buttons_and_ambiguity_is_unknown():
    toks = [_tok(x, 100 + 40 * i, 20) for i, x in enumerate(["AAPL", "1m", "30m", "1h", "5m"])]
    legend = [_tok(x, 100 + 60 * i, 56) for i, x in enumerate(["Apple", "Inc", "5", "Cboe", "One"])]
    r = recognize("", toks + legend, "tradingview")
    assert r.timeframe.value == "5Min" and r.timeframe_source == "chart legend"
    r2 = recognize("", toks, "tradingview")
    assert r2.timeframe is None and "can't tell" in r2.timeframe_note


def test_single_letter_ocr_noise_ranks_after_real_tickers():
    r = recognize("", [_tok("Q", 20, 20), _tok("AAPL", 80, 20)], "tradingview")
    assert r.ticker == "AAPL" and r.ticker_candidates == ["AAPL", "Q"]
