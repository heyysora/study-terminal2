"""SYNTHETIC futures chart screenshots with exact ground truth, in a dark TopstepX-like layout. They test the reader's logic only;
they are not TopstepX screenshots and prove nothing about accuracy on real TopstepX charts (see docs/VISUAL_MONITOR.md)."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

UP, DOWN = (38, 166, 154), (239, 83, 80)
VWAP, EMA9, EMA20 = (255, 152, 0), (41, 98, 255), (186, 104, 200)


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def walk(n=70, start=25000.0, tick=0.25, seed=1, sd=6.0):
    rng = np.random.default_rng(seed)
    out, px = [], start
    for _ in range(n):
        o = px
        c = round((o + rng.normal(0, sd)) / tick) * tick
        hi = round((max(o, c) + abs(rng.normal(0, sd / 2))) / tick) * tick
        lo = round((min(o, c) - abs(rng.normal(0, sd / 2))) / tick) * tick
        v = int(rng.integers(200, 2000))
        out.append({"open": o, "high": hi, "low": lo, "close": c, "volume": v})
        px = c
    return out


def ema(vals, n):
    k, e, out = 2 / (n + 1), None, []
    for v in vals:
        e = v if e is None else e + k * (v - e)
        out.append(e)
    return out


def render(candles=None, symbol="MNQZ6", tf_text="5m", w=1400, h=820, step=10.0, lines_on_top=False, bid_ask=True,
           tag=True, indicators=True, decimals=2, header_extra="CME", spacing=15, bw=9):
    candles = candles or walk()
    img = Image.new("RGB", (w, h), (13, 17, 23))
    d = ImageDraw.Draw(img)
    f, fs = font(22), font(17)
    d.text((14, 12), f"{symbol}  ·  {tf_text}  ·  {header_extra}", fill=(225, 225, 225), font=f)
    if bid_ask:
        d.text((560, 14), f"Bid {candles[-1]['close'] - 0.25:.{decimals}f}", fill=(200, 200, 200), font=fs)
        d.text((760, 14), f"Ask {candles[-1]['close']:.{decimals}f}", fill=(200, 200, 200), font=fs)
    axis_x = w - 120
    top, plot_bottom = 70, int(h * 0.78)
    pmin = min(c["low"] for c in candles) - 3 * step / 2
    pmax = max(c["high"] for c in candles) + 3 * step / 2
    y_of = lambda p: top + (pmax - p) / (pmax - pmin) * (plot_bottom - 20 - top)  # noqa: E731
    first = np.ceil(pmin / step) * step
    for p in np.arange(first, pmax, step):
        y = y_of(p)
        d.line([(0, y), (axis_x, y)], fill=(24, 29, 38))
        d.text((axis_x + 12, y), f"{p:.{decimals}f}", fill=(170, 174, 182), font=fs, anchor="lm")
    x = 30
    xs = []
    for _ in candles:
        xs.append(x + bw / 2)
        x += spacing
    closes = [c["close"] for c in candles]
    tp = [(c["high"] + c["low"] + c["close"]) / 3 for c in candles]
    vw = np.cumsum([t * c["volume"] for t, c in zip(tp, candles, strict=True)]) / np.cumsum([c["volume"] for c in candles])
    lines = {"VWAP": (VWAP, list(vw)), "EMA 9": (EMA9, ema(closes, 9)), "EMA 20": (EMA20, ema(closes, 20))} if indicators else {}

    def draw_lines():
        for col, vals in lines.values():
            d.line([(xx, y_of(v)) for xx, v in zip(xs, vals, strict=True)], fill=col, width=2)

    if not lines_on_top:
        draw_lines()
    for xx, c in zip(xs, candles, strict=True):
        col = UP if c["close"] >= c["open"] else DOWN
        x0 = int(xx - bw / 2)
        d.line([(x0 + bw // 2, y_of(c["high"])), (x0 + bw // 2, y_of(c["low"]))], fill=col, width=1)
        y_top, y_bot = y_of(max(c["open"], c["close"])), y_of(min(c["open"], c["close"]))
        d.rectangle([x0, y_top, x0 + bw - 1, max(y_bot, y_top + 1)], fill=col)
    if lines_on_top:
        draw_lines()
    # volume pane
    vmax = max(c["volume"] for c in candles)
    vb = h - 30
    for xx, c in zip(xs, candles, strict=True):
        col = (25, 90, 86) if c["close"] >= c["open"] else (120, 48, 48)
        x0 = int(xx - bw / 2)
        d.rectangle([x0, vb - 120 * c["volume"] / vmax, x0 + bw - 1, vb], fill=col)
    if tag:
        ty = y_of(candles[-1]["close"])
        col = UP if candles[-1]["close"] >= candles[-1]["open"] else DOWN
        d.rectangle([axis_x + 4, ty - 12, w - 6, ty + 12], fill=col)
        d.text((axis_x + 12, ty), f"{candles[-1]['close']:.{decimals}f}", fill=(255, 255, 255), font=fs, anchor="lm")
    arr = np.asarray(img)[:, :, ::-1].copy()
    truth = {"candles": candles, "xs": xs, "lines": {k: v[1] for k, v in lines.items()}, "price": candles[-1]["close"],
             "price_per_px": (pmax - pmin) / (plot_bottom - 20 - top), "symbol": symbol, "plot_bottom_frac": plot_bottom / h,
             "bid": candles[-1]["close"] - 0.25, "ask": candles[-1]["close"]}
    return arr, truth
