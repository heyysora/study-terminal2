"""Measure the chart pipeline, stage by stage, on repeatable input.

Run:  python -m research.latency_bench [--passes 30] [--image PATH] [--json OUT]

Why synthetic frames. The question "how long does Study Terminal take to notice a price change?" has two halves: how
long the picture takes to arrive, and how long the work on it takes. Only the first needs Windows and a real chart.
The second is the half that code changes can fix, and it can be measured anywhere -- so this feeds the real pipeline
a stream of chart images that change the way a real one does (the last candle grows, the price box moves) and times
each stage. It is the before/after ruler for every optimisation.

What it does NOT measure, and will not pretend to:
  * how long the market took to reach the screen (invisible to a screenshot, by definition);
  * how long Windows Graphics Capture takes on the user's PC (that needs their PC: scripts/acceptance-test.ps1);
  * whether a signal was any good.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.screen import vision                          # noqa: E402
from app.screen.chart_profile import ChartProfile      # noqa: E402
from app.screen.chart_reader import read_chart         # noqa: E402
from app.screen.latency import METER                   # noqa: E402
from app.screen.token_cache import TokenCache          # noqa: E402

W, H = 1180, 700
UP, DOWN, BG, INK = (120, 200, 120), (90, 90, 230), (18, 18, 22), (232, 234, 238)


_SERIES: np.ndarray | None = None
_SCALE: tuple[float, float] | None = None


def chart(seed: int, price: float, candles: int = 120, redraw: bool = False) -> np.ndarray:
    """A dark chart that looks like the real thing to the reader: header label, candles, price axis, price box.

    Two modes, because they measure different things and a benchmark that only does one of them misleads:
      quiet  (default) -- the candle history is fixed and only the newest candle and the price box move. This is what
                          a live chart does between two captures a second apart, and it is the case that decides
                          whether the app keeps up.
      redraw (--redraw) -- every candle is different, as after a scroll, a zoom or a timeframe change. The worst case.
    """
    global _SERIES
    rng = np.random.default_rng(seed if redraw else 7)
    img = np.full((H, W, 3), BG, dtype=np.uint8)
    cv2.putText(img, f"NQZ26 · Nasdaq · 1 O{price:,.2f} H{price + 4:,.2f} L{price - 4:,.2f} C{price:,.2f}",
                (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.52, INK, 1, cv2.LINE_AA)
    axis_x = W - 150
    # A real chart's price scale holds still for long stretches and only rescales when price leaves it. Recentring it
    # on every frame would make the price-axis numbers look like they change on every tick, which is not what a live
    # chart does -- and would quietly turn a cache-hit case into a cache-miss one, flattering nothing and misleading
    # the measurement.
    global _SCALE
    if redraw or _SCALE is None or not (_SCALE[0] + 12 < price < _SCALE[1] - 12):
        _SCALE = (price - 60, price + 60)
    lo, hi = _SCALE
    for i in range(9):                                   # price axis labels, which the reader calibrates from
        v = lo + (hi - lo) * i / 8
        y = int(H * 0.86 - (v - lo) / (hi - lo) * H * 0.80)
        cv2.putText(img, f"{v:,.2f}", (axis_x + 8, y + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 172, 178), 1, cv2.LINE_AA)
        cv2.line(img, (0, y), (axis_x - 2, y), (34, 34, 40), 1)
    step = (axis_x - 20) // candles
    if redraw or _SERIES is None or len(_SERIES) != candles:
        _SERIES = np.cumsum(rng.normal(0, 2.2, candles))
        _SERIES = _SERIES - _SERIES[-1]                  # the newest candle sits at the current price
    closes = price + _SERIES
    closes[-1] = price                                   # only the newest candle tracks the price, as on a real chart
    shape = np.random.default_rng(11).normal(0, 1.6, len(closes))       # fixed body/wick shape: only prices move
    wick = np.abs(np.random.default_rng(12).normal(0, 1.2, len(closes)))
    for i, c in enumerate(closes):
        o = c - shape[i]
        hi_i, lo_i = max(o, c) + wick[i], min(o, c) - wick[i]

        def ypx(v: float) -> int:
            return int(H * 0.86 - (v - lo) / (hi - lo) * H * 0.80)
        x = 14 + i * step
        col = UP if c >= o else DOWN
        cv2.line(img, (x + step // 2, ypx(hi_i)), (x + step // 2, ypx(lo_i)), col, 1)
        cv2.rectangle(img, (x + 1, ypx(max(o, c))), (x + step - 1, ypx(min(o, c))), col, -1)
    ylast = int(H * 0.86 - (price - lo) / (hi - lo) * H * 0.80)      # the price box, what the fast path reads
    cv2.rectangle(img, (axis_x + 2, ylast - 11), (W - 2, ylast + 11), (40, 120, 215), -1)
    cv2.putText(img, f"{price:,.2f}", (axis_x + 8, ylast + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    ys = sorted(xs)
    return ys[min(len(ys) - 1, max(0, int(round(p / 100 * len(ys) + 0.5)) - 1))]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=30)
    ap.add_argument("--image", help="a real chart screenshot to use instead of generated ones")
    ap.add_argument("--json", help="write the numbers here")
    ap.add_argument("--redraw", action="store_true", help="worst case: every candle changes each pass")
    a = ap.parse_args()

    prof = ChartProfile(id="bench", name="bench", root="auto", timeframe="auto",
                        window_title_contains="topstepx", region=[0, 0, 0, 0])
    real = cv2.imread(a.image) if a.image else None
    if a.image and real is None:
        print(f"could not read {a.image}")
        return 2

    print("warming up the text reader (first use loads its models)...", flush=True)
    t0 = time.perf_counter()
    vision.ocr(chart(0, 27_686.0)[:60, :400])
    warm_ms = (time.perf_counter() - t0) * 1000
    print(f"  first read: {warm_ms:,.0f} ms  <- paid once, at start-up, not per pass")

    METER.reset()
    cache = TokenCache(vision.ocr)
    stage: dict[str, list[float]] = {k: [] for k in ("change", "ocr", "parse", "price_box", "decide", "whole")}
    prev_grey = None
    sig = None
    axis = None
    price = 27_686.0

    for i in range(a.passes):
        price += 0.25 * ((i % 7) - 3)                     # moves like a quiet market: small, frequent
        img = real if real is not None else chart(i, price, redraw=a.redraw)
        t_pass = time.perf_counter()

        t = time.perf_counter()                            # has anything moved at all?
        grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _changed = prev_grey is None or prev_grey.shape != grey.shape or int((cv2.absdiff(grey, prev_grey) > 25).sum()) >= 3
        prev_grey = grey
        stage["change"].append((time.perf_counter() - t) * 1000)

        if axis is not None:                               # the fast path: price box only
            from app.screen.live_price import read_tag
            t = time.perf_counter()
            read_tag(img, axis, 0.25, price)
            stage["price_box"].append((time.perf_counter() - t) * 1000)

        t = time.perf_counter()                            # the words
        toks, _meta = cache.tokens(img, sig, title=f"NQZ26 ${price:,.2f} - Profile 1 - Microsoft Edge")
        stage["ocr"].append((time.perf_counter() - t) * 1000)

        t = time.perf_counter()                            # picture -> price, candles, levels
        reading = read_chart(img, prof, datetime.now(timezone.utc), tokens=toks)
        stage["parse"].append((time.perf_counter() - t) * 1000)
        sig = reading.signature
        if reading.axis:
            axis = reading.axis

        t = time.perf_counter()                            # is there a trade?
        from app.screen import visual_recommend as vr
        vr.quality_gates(reading, "screen_capture", "", prof)
        stage["decide"].append((time.perf_counter() - t) * 1000)

        stage["whole"].append((time.perf_counter() - t_pass) * 1000)
        if i == 0:
            print(f"  first pass {stage['whole'][0]:,.0f} ms (cold caches)", flush=True)

    kind = "your screenshot" if real is not None else ("redrawn charts (worst case)" if a.redraw else "a live chart (only the newest candle and the price move)")
    print(f"\n{a.passes} passes on {kind} ({img.shape[1]}x{img.shape[0]})\n")
    print(f"{'stage':<12}{'p50':>9}{'p95':>9}{'p99':>9}{'max':>9}   (ms)")
    out = {}
    for k in ("change", "price_box", "ocr", "parse", "decide", "whole"):
        xs = stage[k]
        if not xs:
            continue
        warm = xs[1:] or xs                                # the first pass pays for every cold cache
        out[k] = {"p50": round(pct(warm, 50), 1), "p95": round(pct(warm, 95), 1), "p99": round(pct(warm, 99), 1),
                  "max": round(max(warm), 1), "mean": round(statistics.fmean(warm), 1), "n": len(warm)}
        print(f"{k:<12}{out[k]['p50']:>9.1f}{out[k]['p95']:>9.1f}{out[k]['p99']:>9.1f}{out[k]['max']:>9.1f}")
    body = [k for k in out if k not in ("whole", "price_box")]
    slowest = max(body, key=lambda k: out[k]["p95"]) if body else None
    print(f"\nslowest working stage: {slowest} at p95 {out[slowest]['p95']:.0f} ms" if slowest else "")
    if "price_box" in out and "whole" in out:
        print(f"fast path vs full pass: {out['price_box']['p50']:.0f} ms vs {out['whole']['p50']:.0f} ms "
              f"({out['whole']['p50'] / max(out['price_box']['p50'], 0.01):.0f}x cheaper)")
    print("\nNot measured here: how long the market took to reach your screen, and how long Windows takes to hand\n"
          "over a picture of the window. Both need your PC -- scripts/acceptance-test.ps1 measures the second.")
    if a.json:
        Path(a.json).write_text(json.dumps({"stages": out, "warm_up_ms": round(warm_ms), "passes": a.passes,
                                            "image": a.image or ("generated-redraw" if a.redraw else "generated-quiet"), "at": datetime.now(timezone.utc).isoformat()}, indent=2))
        print(f"\nwritten to {a.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
