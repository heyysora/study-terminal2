"""Renders a TradingView-style chart screenshot with known ground truth (for vision tests)."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # very old Pillow
        return ImageFont.load_default()


def render(ticker="TSLA", tf="5", price=359.40, line_price=362.0, w=1400, h=800, seed=0, header_extra="VWAP  EMA 9  RSI 14",
           tag_rgb=(8, 153, 129), body_text=None, exchange="NASDAQ", pmin=352.0, pmax=366.0, step=2.0, decimals=2,
           extra_text=None) -> np.ndarray:
    rng = np.random.default_rng(seed)
    img = Image.new("RGB", (w, h), (19, 23, 34))
    d = ImageDraw.Draw(img)
    f, fs = font(22), font(18)
    d.text((14, 12), f"{ticker}  ·  {tf}  ·  {exchange}", fill=(220, 220, 220), font=f)
    d.text((14, 48), f"C{price:.{decimals}f}   {header_extra}", fill=(180, 180, 180), font=fs)
    axis_x = w - 110
    top, bottom = 110, h - 70
    y_of = lambda p: top + (pmax - p) / (pmax - pmin) * (bottom - top)  # noqa: E731
    for p in np.arange(pmin + step, pmax, step):
        y = y_of(p)
        d.line([(0, y), (axis_x, y)], fill=(32, 37, 50))           # faint gridline
        d.text((axis_x + 12, y - 9), f"{p:.{decimals}f}", fill=(178, 181, 190), font=fs)
    d.line([(0, y_of(line_price)), (axis_x, y_of(line_price))], fill=(255, 152, 0), width=2)  # user-drawn level
    x, prev = 40, pmin + 0.36 * (pmax - pmin)
    sd = 0.043 * (pmax - pmin)
    cols = []
    while x < axis_x - 30:
        o = prev
        c = o + rng.normal(0, sd)
        c = min(max(c, pmin + 0.07 * (pmax - pmin)), pmax - 0.07 * (pmax - pmin))
        up = c >= o
        col = (38, 166, 154) if up else (239, 83, 80)
        cols.append("up" if up else "down")
        hi, lo = max(o, c) + abs(rng.normal(0, sd / 3)), min(o, c) - abs(rng.normal(0, sd / 3))
        d.line([(x + 4, y_of(hi)), (x + 4, y_of(lo))], fill=col)
        d.rectangle([x, y_of(max(o, c)), x + 8, max(y_of(min(o, c)), y_of(max(o, c)) + 1)], fill=col)
        prev, x = c, x + 14
    ty = y_of(price)
    d.rectangle([axis_x + 4, ty - 12, w - 6, ty + 12], fill=tag_rgb)
    d.text((axis_x + 12, ty - 9), f"{price:.{decimals}f}", fill=(255, 255, 255), font=fs)
    if extra_text:
        for (tx, ty_, txt) in extra_text:
            d.text((tx, ty_), txt, fill=(200, 200, 200), font=fs)
    if body_text:
        d.text((300, 300), body_text, fill=(255, 255, 255), font=f)
    arr = np.asarray(img)[:, :, ::-1].copy()  # RGB -> BGR like a real capture
    return arr, cols
