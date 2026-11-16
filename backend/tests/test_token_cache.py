"""Reading the words on a chart is ~97% of the cost of reading the chart; the words barely change. These pin down
both halves of that bargain: that the saving is real, and that cached words never pass for a fresh observation.

Measured on a real 1919x1074 TopstepX capture: a full read was 6296 ms, of which 6140 ms was OCR; with the cache
warm the same read was ~150 ms and produced an identical reading.
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from app.screen.token_cache import BODY_SECONDS, CEILING_SECONDS, TokenCache
from app.screen.vision import Token


class FakeOcr:
    """Counts how often it is asked to read, and where."""

    def __init__(self):
        self.calls: list[tuple[int, int, int, int]] = []

    def __call__(self, img, offset=(0, 0), **kw):
        h, w = img.shape[:2]
        self.calls.append((offset[0], offset[1], w, h))
        return [Token(text=f"r{offset[1]}c{offset[0]}", conf=0.9,
                      x0=offset[0], y0=offset[1], x1=offset[0] + 40, y1=offset[1] + 14)]

    @property
    def n(self) -> int:
        return len(self.calls)


def chart(w: int = 1200, h: int = 800, seed: int = 0) -> np.ndarray:
    """A chart-shaped picture: dark, a header band, candles in the middle, a price axis on the right."""
    rng = np.random.default_rng(seed)
    img = np.full((h, w, 3), 18, dtype=np.uint8)
    cv2.putText(img, "NQZ26 Nasdaq 1", (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (235, 235, 235), 2)
    for i in range(40):                                        # candles
        x = 60 + i * 25
        top, bot = int(rng.integers(200, 400)), int(rng.integers(450, 700))
        cv2.rectangle(img, (x, top), (x + 14, bot), (90, 200, 120), -1)
    for i in range(8):                                         # price-scale numbers
        cv2.putText(img, f"27,{600 + i * 20}", (w - 110, 160 + i * 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return img


def move_candles(img: np.ndarray) -> np.ndarray:
    """What a tick looks like: the newest candle grows, nothing else moves."""
    out = img.copy()
    cv2.rectangle(out, (1000, 300), (1014, 640), (90, 200, 120), -1)
    return out


def move_price_box(img: np.ndarray, y: int) -> np.ndarray:
    """The coloured last-price box on the axis, at a new height."""
    out = img.copy()
    cv2.rectangle(out, (out.shape[1] - 120, y), (out.shape[1] - 4, y + 22), (40, 190, 240), -1)
    return out


# ---------------------------------------------------------------- the saving

def test_the_first_read_covers_the_whole_picture_in_one_pass():
    """Three separate passes cost more than one. A cold cache reads everything once and splits the words up."""
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    toks, meta = tc.tokens(chart())
    assert ocr.n == 1, "a cold start must not pay for three passes"
    assert meta["regions_read"] == ["whole chart"] and meta["ocr_passes"] == 1
    assert toks, "the words from that pass are kept"


def test_an_unchanged_chart_is_never_read_again():
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    tc.tokens(img)
    before = ocr.n
    for _ in range(10):
        toks, meta = tc.tokens(img)
        assert meta["regions_read"] == [], "nothing moved, so nothing should be read again"
    assert ocr.n == before, f"{ocr.n - before} needless OCR passes"
    assert tc.stats()["avoided"] >= 30


def test_moving_candles_alone_do_not_trigger_any_reading():
    """The whole point. Candles change on every tick and carry no text; re-reading on their account is what made a
    chart read take six seconds."""
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    tc.tokens(img)
    before = ocr.n
    for _ in range(5):
        _, meta = tc.tokens(move_candles(img))
        assert meta["regions_read"] == [], f"candles moving caused a re-read of {meta['regions_read']}"
    assert ocr.n == before


def test_a_moving_price_box_is_read_again_but_the_price_scale_is_not():
    """The box carries the current price, so when it moves it MUST be read again -- a cached price is a stale price.
    The grey scale numbers behind it have not changed, so they must not be."""
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    tc.tokens(img)
    for y in (200, 300, 400, 500):
        _, meta = tc.tokens(move_price_box(img, y))
        assert "tag" in meta["regions_read"], f"the price box moved to y={y} and its new price was not read"
        assert "axis" not in meta["regions_read"], f"the price box at y={y} caused the price scale to be read again"


def test_a_price_that_changes_without_the_box_moving_is_still_read_again():
    """A price can tick while the box stays exactly where it is. Comparing only the box's position would serve the
    old number; the digits inside it are compared too."""
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = move_price_box(chart(), 300)
    tc.tokens(img)
    same_place_new_digits = img.copy()
    cv2.putText(same_place_new_digits, "27,701", (img.shape[1] - 112, 318), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (10, 10, 10), 1)
    _, meta = tc.tokens(same_place_new_digits)
    assert "tag" in meta["regions_read"], "the digits in the price box changed and were not read again"


def test_only_the_box_that_moved_is_read_again():
    """Charts show several coloured boxes (last price, an alert, a position marker). Re-reading all of them every
    time any one moves costs more than it saves."""
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = move_price_box(move_price_box(chart(), 200), 600)     # two boxes, far apart
    tc.tokens(img)
    before = ocr.n
    moved = move_price_box(move_price_box(chart(), 200), 640)    # only the lower one moves
    tc.tokens(moved)
    assert ocr.n - before <= 2, f"{ocr.n - before} boxes were read when one moved"


# ---------------------------------------------------------------- the honesty

def test_changed_text_is_read_again():
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    tc.tokens(img)
    changed = img.copy()
    cv2.putText(changed, "ESH26 CME 5", (16, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (10, 10, 10), 3)   # paint over it
    _, meta = tc.tokens(changed)
    assert "header" in meta["regions_read"], "the market name changed and was not read again"


def test_a_changed_price_scale_is_read_again():
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    tc.tokens(img)
    rescaled = img.copy()
    for i in range(8):                                        # the chart rescaled: different numbers down the axis
        cv2.rectangle(rescaled, (rescaled.shape[1] - 120, 140 + i * 80), (rescaled.shape[1] - 4, 175 + i * 80), (18, 18, 18), -1)
        cv2.putText(rescaled, f"28,{100 + i * 50}", (rescaled.shape[1] - 110, 160 + i * 80), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    _, meta = tc.tokens(rescaled)
    assert "axis" in meta["regions_read"], "the price scale changed and was not read again"


def test_every_region_is_read_again_at_least_once_a_minute(monkeypatch):
    """Pixels are not the only way text goes wrong. A ceiling means the oldest possible word is one minute old."""
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    tc.tokens(img)
    before = ocr.n
    t0 = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: t0 + CEILING_SECONDS + 1)
    _, meta = tc.tokens(img)
    assert {"header", "axis"} <= set(meta["regions_read"]), meta["regions_read"]
    assert ocr.n > before


def test_the_body_is_refreshed_on_a_timer_not_on_pixels(monkeypatch):
    """Body text (labels on lines you drew) sits on top of candles that always move, so a pixel comparison would say
    "changed" every single time and save nothing. Time is the only honest rule there."""
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    tc.tokens(img)
    _, meta = tc.tokens(move_candles(img))
    assert "body" not in meta["regions_read"]
    t0 = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: t0 + BODY_SECONDS + 1)
    _, meta = tc.tokens(img)
    assert "body" in meta["regions_read"]


def test_every_result_says_how_old_its_words_are(monkeypatch):
    """A reading must be able to say that its text was observed a moment ago, or twenty seconds ago. Cached words
    that cannot report their age are stale data wearing a fresh label."""
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    tc.tokens(img)
    t0 = time.monotonic()
    # Six seconds: inside every region's timer, so nothing is re-read and the ages are purely what was kept.
    # (The chart's label has its own, shorter timer -- see HEADER_SECONDS -- so twelve would re-read it and the
    # point being made here is about reporting age, not about when a region expires.)
    monkeypatch.setattr(time, "monotonic", lambda: t0 + 6.0)
    _, meta = tc.tokens(img)
    assert meta["oldest_text_seconds"] >= 6.0
    assert set(meta["age_seconds"]) == {"header", "axis", "tag", "body"}
    assert meta["reused"] and not meta["regions_read"]


def test_the_chart_label_is_re_read_on_its_own_timer(monkeypatch):
    """The label is not watched by pixels when the window title names the contract, so the timer is the only thing
    bounding how long a timeframe change can go unnoticed. If that timer ever stops working, nothing else catches it."""
    from app.screen.token_cache import HEADER_SECONDS
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    title = "NQZ26 $27,686.00 - Profile 1 - Microsoft Edge"
    tc.tokens(img, title=title)
    t0 = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: t0 + HEADER_SECONDS - 1)
    _, meta = tc.tokens(img, title=title)
    assert "header" not in meta["regions_read"], "re-read too eagerly; this is the expensive one"
    monkeypatch.setattr(time, "monotonic", lambda: t0 + HEADER_SECONDS + 1)
    _, meta = tc.tokens(img, title=title)
    assert "header" in meta["regions_read"], "the timer is the only bound on a missed timeframe change"


def test_a_different_contract_in_the_window_title_re_reads_the_label_at_once(monkeypatch):
    """Switching market must not wait for a timer: the tab title names the contract, so it is noticed immediately."""
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    tc.tokens(img, title="NQZ26 $27,686.00 - Profile 1 - Microsoft Edge")
    t0 = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: t0 + 1.0)
    _, meta = tc.tokens(img, title="NQZ26 $27,999.75 - Profile 1 - Microsoft Edge")
    assert "header" not in meta["regions_read"], "same contract, only the price moved: not a reason to re-read"
    _, meta = tc.tokens(img, title="ESZ26 $6,120.25 - Profile 1 - Microsoft Edge")
    assert "header" in meta["regions_read"], "a different contract must be noticed at once, not in eight seconds"


def test_forgetting_makes_the_next_read_complete():
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    tc.tokens(img)
    tc.forget()
    _, meta = tc.tokens(img)
    assert meta["regions_read"] == ["whole chart"], "after forgetting, everything must be read again"
    assert meta["oldest_text_seconds"] == 0.0


def test_a_resized_window_is_read_again():
    """A different picture size invalidates every stored comparison."""
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    tc.tokens(chart(1200, 800))
    _, meta = tc.tokens(chart(1000, 700, seed=1))
    assert meta["regions_read"], "a resized window must not reuse words measured against the old size"


def test_the_words_carry_their_place_on_the_full_picture():
    """Each region is read from a crop, so the coordinates have to be mapped back or every position is wrong."""
    ocr = FakeOcr()
    tc = TokenCache(ocr)
    img = chart()
    tc.tokens(img)
    tc.forget()
    tc.header.ever = True                                   # force the per-region path rather than the priming pass
    tc.header.read_at = time.monotonic()
    toks, meta = tc.tokens(img)
    axis_left = meta["bounds"]["axis_left"]
    assert any(t.x0 >= axis_left for t in toks), "axis words must carry their real x position"
    assert any(t.y0 >= meta["bounds"]["header_h"] for t in toks), "body words must carry their real y position"
