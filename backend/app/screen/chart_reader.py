"""Reads one captured chart region: instrument, timeframe, price, bid/ask, price axis, candles, volume bars, indicator lines and
horizontal levels. Pure function of the image + the chart profile; no network, nothing stored.

Every value is an Observation with a class:
  DIRECTLY_READ                read from on-screen text by OCR (the price tag, the ticker, bid/ask)
  CALCULATED_FROM_CALIBRATION  computed from the calibrated price axis (e.g. the price of a horizontal line)
  VISUALLY_ESTIMATED           estimated from pixels (candle OHLC, indicator lines, relative volume); never exact market data
  UNAVAILABLE                  not visible or not readable; the value is None, never guessed
plus a confidence (0-1) and the capture time. Overall confidence is the weakest of the values a recommendation depends on.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime

import cv2
import numpy as np

from ..futures import contracts as fc
from .chart_profile import ROOTS, ChartProfile
from .vision import AxisFit, Token, find_price_axis, last_price_tag, ocr, parse_number, tf_from_text

TEXT, CALCULATED, ESTIMATED, UNAVAILABLE = "DIRECTLY_READ", "CALCULATED_FROM_CALIBRATION", "VISUALLY_ESTIMATED", "UNAVAILABLE"


@dataclass
class Observation:
    value: object
    cls: str
    confidence: float
    source: str = ""

    def to_dict(self) -> dict:
        return {"value": self.value, "class": self.cls, "confidence": round(float(self.confidence), 2), "source": self.source}


def unavailable(why: str) -> Observation:
    return Observation(None, UNAVAILABLE, 0.0, why)


@dataclass
class Candle:
    x0: int
    x1: int
    open: float | None
    high: float
    low: float
    close: float | None
    direction: str               # up | down | doji | unknown
    confidence: float
    body_known: bool
    volume_rel: float | None = None

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class ChartReading:
    captured_at: str
    size: tuple[int, int]
    ok: bool = True
    problems: list[str] = field(default_factory=list)
    instrument: Observation = field(default_factory=lambda: unavailable("not read"))
    timeframe: Observation = field(default_factory=lambda: unavailable("not read"))
    price: Observation = field(default_factory=lambda: unavailable("not read"))
    bid: Observation = field(default_factory=lambda: unavailable("not displayed"))
    ask: Observation = field(default_factory=lambda: unavailable("not displayed"))
    axis: dict | None = None
    candles: list[Candle] = field(default_factory=list)
    candle_confidence: float = 0.0
    indicators: dict = field(default_factory=dict)      # name -> {"values": [price|None per candle], "class", "confidence"} or unavailable
    levels: list[dict] = field(default_factory=list)
    volume: Observation = field(default_factory=lambda: unavailable("not read"))
    plot: tuple[int, int, int, int] | None = None
    colors: dict = field(default_factory=dict)
    confidence: float = 0.0
    calibration_valid: bool = True
    signature: dict = field(default_factory=dict)
    thumb: object = None                                   # small grayscale image for change detection (not serialized)

    def to_dict(self, candles: int = 300) -> dict:
        d = {"captured_at": self.captured_at, "size": list(self.size), "ok": self.ok, "problems": self.problems,
             "instrument": self.instrument.to_dict(), "timeframe": self.timeframe.to_dict(), "price": self.price.to_dict(),
             "bid": self.bid.to_dict(), "ask": self.ask.to_dict(), "axis": self.axis, "volume": self.volume.to_dict(),
             "candle_confidence": round(self.candle_confidence, 2), "levels": self.levels, "plot": self.plot, "colors": self.colors,
             "confidence": round(self.confidence, 2), "signature": self.signature, "calibration_valid": self.calibration_valid,
             "indicators": {k: v for k, v in self.indicators.items()},
             "candles": [{**{k: v for k, v in asdict(c).items()}, "class": ESTIMATED} for c in self.candles[-candles:]]}
        return d


# ---------------- helpers ----------------

def _rgb_to_bgr(c):
    return np.array([c[2], c[1], c[0]], dtype=np.int16)


def color_mask(img: np.ndarray, rgb, tol: int) -> np.ndarray:
    d = np.abs(img.astype(np.int16) - _rgb_to_bgr(rgb)).max(axis=2)
    return d <= tol


def auto_candle_colors(img: np.ndarray) -> tuple[list[int] | None, list[int] | None]:
    """Most common strongly colored green-ish and red-ish pixels (typical candle colors)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    strong = (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 90)
    h = hsv[:, :, 0]
    out = []
    for sel in ((h >= 35) & (h <= 95), (h <= 12) | (h >= 165)):
        m = strong & sel
        if m.sum() < 30:
            out.append(None)
            continue
        px = img[m].reshape(-1, 3)
        # mode of quantized colors = the dominant shade
        q = (px // 8).astype(np.int32)
        keys = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
        vals, counts = np.unique(keys, return_counts=True)
        k = vals[counts.argmax()]
        sel_px = px[keys == k]
        b, g, r = np.median(sel_px, axis=0)
        out.append([int(r), int(g), int(b)])
    return out[0], out[1]


def snap(price: float, spec) -> float:
    t = float(spec.tick_size)
    return round(round(price / t) * t, 6)


def _header_tokens(tokens: list[Token], h: int) -> list[Token]:
    return [t for t in tokens if t.cy < max(60, 0.12 * h)]


def _header_words(text: str) -> list[str]:
    """Words of a header token. Some OCR versions read TopstepX's '·' separators as ':' ('ESZ6:5m:CME'), so ':' also splits,
    but only pieces with a letter are kept from it: a clock time like '10:15' must not turn into a '15 minute' timeframe."""
    out = []
    for word in re.split(r"[\s·•|,.]+", text.strip()):
        if ":" in word:
            out += [w for w in word.split(":") if re.search(r"[A-Za-z]", w)]
        elif word:
            out.append(word)
    return out


def read_instrument(tokens: list[Token], h: int, profile: ChartProfile) -> tuple[Observation, list[str]]:
    probs = []
    read = None
    for t in sorted(_header_tokens(tokens, h), key=lambda t: (t.cy, t.cx)):
        for word in _header_words(t.text):
            p = fc.parse_symbol(word.strip("/"), allow_bare_root=True)
            if p and p.root in ROOTS:
                read = (p.contract.code if p.contract else p.root, p.root, t.conf)
                break
        if read:
            break
    if profile.root != "auto":
        if read and read[1] != profile.root:
            probs.append(f"Instrument conflict: the chart shows {read[0]} but this profile is set to {profile.root}.")
            return Observation(profile.root, TEXT, 0.2, "profile setting contradicted by the chart"), probs
        if not read:   # can't confirm the chart is really this market: below the 0.6 an idea needs
            probs.append(f"Market name not readable on the chart; can't confirm it is {profile.root}.")
            return Observation(profile.root, CALCULATED, 0.5, "profile setting, not confirmed by the chart"), probs
        return Observation(profile.root, TEXT, 0.95, "chart text (matches profile)"), probs
    if not read:
        probs.append("Instrument not readable on the chart; set it in the chart profile.")
        return unavailable("no NQ/MNQ/ES/MES symbol found in the chart header"), probs
    return Observation(read[1], TEXT, min(0.95, 0.5 + 0.45 * float(read[2] or 0.8)), f"chart text '{read[0]}'"), probs


def read_timeframe(tokens: list[Token], h: int, profile: ChartProfile) -> tuple[Observation, list[str]]:
    probs = []
    seen = None
    for t in sorted(_header_tokens(tokens, h), key=lambda t: (t.cy, t.cx)):
        for word in _header_words(t.text):
            tf, note = tf_from_text(word)
            if tf is not None and note is None:
                seen = tf.value
                break
        if seen:
            break
    if profile.timeframe != "auto":
        if seen and seen != profile.timeframe:
            probs.append(f"Timeframe conflict: the chart shows {seen} but this profile is set to {profile.timeframe}.")
            return Observation(profile.timeframe, TEXT, 0.2, "profile setting contradicted by the chart"), probs
        if not seen:
            probs.append(f"Timeframe not readable on the chart; can't confirm it is {profile.timeframe}.")
            return Observation(profile.timeframe, CALCULATED, 0.5, "profile setting, not confirmed by the chart"), probs
        return Observation(profile.timeframe, TEXT, 0.95, "chart text (matches profile)"), probs
    if not seen:
        probs.append("Timeframe not readable on the chart; set it in the chart profile.")
        return unavailable("no timeframe found in the chart header"), probs
    return Observation(seen, TEXT, 0.85, "chart text"), probs


def gridline_rows(img: np.ndarray, x1: int) -> np.ndarray:
    """Rows that are faint full-width gridlines in the plot area (differ slightly but consistently from the background)."""
    g = cv2.cvtColor(img[:, : max(20, x1)], cv2.COLOR_BGR2GRAY).astype(np.int16)
    bg = int(np.median(g))
    near_bg = np.abs(g - bg) <= 40                    # ignore candles, text and lines: only look at background-ish pixels
    diff = np.where(near_bg, np.abs(g - bg), 0)
    share = (diff >= 3).mean(axis=1)                    # a gridline row is slightly off-background across most of the width
    return np.where(share > 0.55)[0]


def refine_axis(fit: AxisFit, axis_toks: list[Token], img: np.ndarray) -> AxisFit:
    """OCR boxes are a few pixels off the gridline a label belongs to. Where a gridline lies within 6 px of a label, use its
    row instead, and refit. Keeps the OCR fit if fewer than 3 labels have a gridline."""
    rows = gridline_rows(img, int(fit.x_left) - 8)
    if len(rows) == 0:
        return fit
    pts = []
    for t in axis_toks:
        v = parse_number(t.text)
        if v is None:
            continue
        d = np.abs(rows - t.cy)
        if d.min() <= 6:
            # a gridline can be 1-2 px thick: use the middle of the run of rows nearest the label
            r0 = rows[d.argmin()]
            run = rows[np.abs(rows - r0) <= 2]
            pts.append((float(run.mean()), v))
    if len(pts) < 3:
        return fit
    ys, vs = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    a, b = np.polyfit(ys, vs, 1)
    resid = np.abs(vs - (a * ys + b)).max() / np.median(np.abs(vs)) * 100
    if a >= 0 or resid > max(fit.max_resid_pct * 2, 0.01):
        return fit
    return AxisFit(float(a), float(b), len(pts), float(resid), fit.x_left)


class CalibrationInvalid(Exception):
    pass


def read_axis(tokens: list[Token], w: int, h: int, profile: ChartProfile, img: np.ndarray | None = None
              ) -> tuple[AxisFit | None, list[Token], dict | None, list[str]]:
    """Automatic axis: refitted from the labels on every capture, so zoom/scale/pan are followed. Manual axis: valid only while the
    chart keeps the scale and size it had when you calibrated; any sign it changed raises CalibrationInvalid (analysis pauses)."""
    probs = []
    auto, axis_toks = find_price_axis(tokens, w, h)
    if auto is not None and img is not None:
        auto = refine_axis(auto, axis_toks, img)
    manual = None
    if profile.axis_mode == "manual":
        (y1, p1), (y2, p2) = profile.axis_points
        a = (p2 - p1) / (y2 - y1)
        manual = AxisFit(float(a), float(p1 - a * y1), 2, 0.0, float(profile.axis_x if profile.axis_x is not None else w * 0.9))
    unverified = False
    if manual is not None:
        if profile.axis_size and (abs(profile.axis_size[0] - w) > 2 or abs(profile.axis_size[1] - h) > 2):
            raise CalibrationInvalid(f"The chart region is {w}x{h} now but was {profile.axis_size[0]}x{profile.axis_size[1]} when you "
                                     "calibrated (window resized).")
        if auto is not None:
            if profile.axis_x is None:
                manual.x_left = auto.x_left                 # where the axis column starts, from its labels
            mid = h / 2
            diff = abs(manual.price_at(mid) - auto.price_at(mid))
            span = abs(auto.slope) * h
            if diff > 0.01 * span or abs(manual.slope - auto.slope) > 0.02 * abs(auto.slope):
                raise CalibrationInvalid("The chart was zoomed, rescaled or panned since you calibrated: the price labels no longer "
                                         "match the calibration.")
        else:
            unverified = True
            probs.append("Manual calibration can't be checked (no readable price labels); zoom or pan changes won't be detected.")
    fit = manual or auto
    if fit is None:
        probs.append("Price axis not found: no readable price labels and no manual calibration.")
        return None, [], None, probs
    if fit.slope >= 0:
        probs.append("Price axis is inverted or invalid.")
        return None, [], None, probs
    conf = (0.6 if unverified else 0.9) if manual else min(0.95, 0.55 + 0.08 * fit.n) * (1.0 if fit.max_resid_pct < 0.05 else 0.6)
    info = {"mode": "manual" if manual else "auto", "verified": not unverified, "slope": fit.slope, "intercept": fit.intercept, "labels": fit.n,
            "max_residual_pct": round(fit.max_resid_pct, 4), "x_left": round(fit.x_left, 1), "class": CALCULATED, "confidence": round(conf, 2),
            "price_per_pixel": round(abs(fit.slope), 6)}
    return fit, axis_toks, info, probs


def read_bid_ask(tokens: list[Token]) -> tuple[Observation, Observation]:
    out = {}
    for key in ("bid", "ask"):
        lab = [t for t in tokens if re.fullmatch(rf"{key}:?", t.text.strip().lower())]
        best = None
        for L in lab:
            nums = [t for t in tokens if abs(t.cy - L.cy) < 10 and L.x1 - 2 <= t.x0 <= L.x1 + 140 and parse_number(t.text) is not None]
            if nums:
                n = min(nums, key=lambda t: t.x0)
                best = Observation(parse_number(n.text), TEXT, round(0.6 + 0.3 * float(n.conf or 0.8), 2), f"OCR next to '{L.text}'")
                break
        if best is None:
            for t in tokens:
                m = re.search(rf"(?i)(?<![a-z]){key}\s*:?\s*([\d,]+\.?\d*)", t.text)
                if m and (v := parse_number(m.group(1))) is not None:
                    best = Observation(v, TEXT, 0.75, f"OCR '{t.text.strip()[:30]}'")
                    break
        out[key] = best or unavailable("bid/ask not displayed")
    return out["bid"], out["ask"]


def extract_candles(img: np.ndarray, plot: tuple[int, int, int, int], up_rgb, down_rgb, tol: int,
                    exclude: np.ndarray | None = None) -> tuple[list[dict], dict]:
    """Candles in pixel coordinates. Returns (list of {x0,x1,y_high,y_low,y_open,y_close,dir,body_known,merged}, stats)."""
    x0, y0, x1, y1 = plot
    roi = img[y0:y1, x0:x1]
    up = color_mask(roi, up_rgb, tol)
    dn = color_mask(roi, down_rgb, tol)
    if exclude is not None:
        ex = exclude[y0:y1, x0:x1]
        up &= ~ex
        dn &= ~ex
    anym = up | dn
    W = anym.shape[1]
    # remove horizontal lines in candle colors (drawn levels, price line): rows covered over a third of the width
    rows = anym.sum(axis=1)
    line_rows = rows > 0.33 * W
    anym[line_rows] = False
    up[line_rows] = False
    dn[line_rows] = False
    cols = anym.sum(axis=0)
    segs, s = [], None
    for x in range(W):
        if cols[x] > 0 and s is None:
            s = x
        elif cols[x] == 0 and s is not None:
            segs.append((s, x - 1))
            s = None
    if s is not None:
        segs.append((s, W - 1))
    stats = {"segments": len(segs)}
    if not segs:
        return [], stats
    widths = np.array([b - a + 1 for a, b in segs])
    med = float(np.median(widths))
    out = []
    for a, b in segs:
        wseg = b - a + 1
        parts = [(a, b)]
        merged = False
        if wseg > 1.8 * med and med >= 2:                    # touching candles: split by the typical width
            k = int(round(wseg / med))
            edges = np.linspace(a, b + 1, k + 1).astype(int)
            parts = [(edges[i], edges[i + 1] - 1) for i in range(k)]
            merged = True
        for pa, pb in parts:
            sub = anym[:, pa:pb + 1]
            ys = np.where(sub.any(axis=1))[0]
            if len(ys) == 0:
                continue
            width = pb - pa + 1
            cnt = sub.sum(axis=1)
            thr = max(2, int(np.ceil(0.6 * width))) if width >= 3 else None
            nu, nd = int(up[:, pa:pb + 1].sum()), int(dn[:, pa:pb + 1].sum())
            direction = "up" if nu > nd else "down" if nd > nu else "unknown"
            yh, yl = int(ys.min()), int(ys.max())
            body_known = False
            yo = yc = None
            if thr is not None:
                body = np.where(cnt >= thr)[0]
                if len(body):
                    bt, bb = int(body.min()), int(body.max())
                    body_known = True
                    if bb - bt <= 1:
                        direction = "doji" if direction == "unknown" else direction
                    yo, yc = (bb, bt) if direction == "up" else (bt, bb)
            out.append({"x0": pa + x0, "x1": pb + x0, "y_high": yh + y0, "y_low": yl + y0,
                        "y_open": None if yo is None else yo + y0, "y_close": None if yc is None else yc + y0,
                        "dir": direction, "body_known": body_known, "merged": merged})
    stats.update({"median_width": med, "candles": len(out), "merged": sum(1 for c in out if c["merged"])})
    return out, stats


def volume_heights(img: np.ndarray, pane: tuple[int, int, int, int], centers: list[float]) -> list[float | None]:
    """Relative volume bar heights at each candle center (0-1). Bars = pixels that differ clearly from the pane background."""
    x0, y0, x1, y1 = pane
    roi = img[y0:y1, x0:x1].astype(np.int16)
    if roi.size == 0 or y1 - y0 < 8:
        return [None] * len(centers)
    bg = np.median(roi.reshape(-1, 3), axis=0)
    diff = np.abs(roi - bg).max(axis=2) > 28
    H = y1 - y0
    out = []
    for cx in centers:
        x = int(round(cx)) - x0
        if not 0 <= x < roi.shape[1]:
            out.append(None)
            continue
        col = diff[:, max(0, x - 1):x + 2].any(axis=1)
        # contiguous run up from the bottom
        n = 0
        for yy in range(H - 1, -1, -1):
            if col[yy]:
                n += 1
            elif n:
                break
        out.append(float(n))
    m = max([v for v in out if v], default=0)
    return [None if v is None else (v / m if m else 0.0) for v in out]


def line_values(img: np.ndarray, plot: tuple[int, int, int, int], rgb, tol: int, centers: list[float]) -> list[float | None]:
    """Y (pixel) of a colored indicator line at each candle center, or None where the line isn't visible."""
    x0, y0, x1, y1 = plot
    m = color_mask(img[y0:y1, x0:x1], rgb, tol)
    out = []
    for cx in centers:
        x = int(round(cx)) - x0
        if not 0 <= x < m.shape[1]:
            out.append(None)
            continue
        ys = np.where(m[:, max(0, x - 1):x + 2].any(axis=1))[0]
        out.append(float(np.median(ys)) + y0 if len(ys) else None)
    return out


# ---------------- main ----------------

def read_chart(img: np.ndarray, profile: ChartProfile, captured_at: datetime, tokens: list[Token] | None = None,
               title: str = "") -> ChartReading:
    h, w = img.shape[:2]
    r = ChartReading(captured_at=captured_at.isoformat(), size=(w, h))
    small = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (96, 54), interpolation=cv2.INTER_AREA) if w > 0 and h > 0 else None
    r.thumb = small
    if w < 120 or h < 100:
        r.ok, r.problems = False, ["The capture region is too small to read a chart (at least 120 x 100 pixels)."]
        return r
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if float(gray.std()) < 4:
        r.ok, r.problems = False, ["Blank capture: the region is a single flat color (window minimized, covered, or not rendered)."]
        return r
    tokens = ocr(img) if tokens is None else tokens
    from .vision import detect_auth_screen
    auth = detect_auth_screen(title, tokens)
    if auth:
        r.ok, r.problems = False, [f"Possible login/sensitive screen ('{auth}'); nothing is read or kept."]
        return r
    r.instrument, p1 = read_instrument(tokens, h, profile)
    from .platforms import topstepx_title
    tab = topstepx_title(title)                # TopstepX names its browser tab after the contract: exact text, no picture-reading needed
    if tab and tab["root"] in ROOTS:
        weak = r.instrument.value is None or r.instrument.cls != TEXT or r.instrument.confidence < 0.6
        if weak and (profile.root == "auto" or profile.root == tab["root"]):
            r.instrument, p1 = Observation(tab["root"], TEXT, 0.9, f"browser tab title '{tab['contract']}'"), []
        elif r.instrument.value is not None and r.instrument.value != tab["root"]:
            p1 = p1 + [f"Instrument conflict: the chart reads {r.instrument.value} but the browser tab is titled {tab['contract']}."]
            r.instrument = Observation(r.instrument.value, r.instrument.cls, min(r.instrument.confidence, 0.2), r.instrument.source + " (contradicted by the tab title)")
    r.timeframe, p2 = read_timeframe(tokens, h, profile)
    r.problems += p1 + p2
    try:
        fit, axis_toks, axis_info, p3 = read_axis(tokens, w, h, profile, img)
    except CalibrationInvalid as e:
        # pause everything that depends on the axis; text values (price tag) are still read and shown
        r.calibration_valid = False
        r.problems.append(f"Calibration invalid: {e} Price-dependent analysis is paused until you recalibrate "
                          "(Live Visual Monitor > Set up a chart > Recalibrate) or switch the profile to automatic axis.")
        v, _ = last_price_tag(img, tokens, w)
        r.price = Observation(v, TEXT, 0.6, "price tag text (axis calibration invalid)") if v is not None else unavailable("not readable")
        r.bid, r.ask = read_bid_ask(tokens)
        r.ok, r.confidence = False, 0.0
        r.signature = {"size": [w, h], "axis_left": -1, "header_h": -1}
        return r
    r.problems += p3
    r.axis = axis_info
    spec = fc.get(r.instrument.value) if r.instrument.value in ROOTS else None
    r.bid, r.ask = read_bid_ask(tokens)
    # price tag (text) checked against the axis and the tick grid
    if fit is not None:
        v, ty = last_price_tag(img, tokens, w, fit, axis_toks or None)
        if v is not None:
            conf, src = 0.9, "price tag text on the axis"
            if abs(fit.price_at(ty) - v) > max(3 * abs(fit.slope) * 12, 0.003 * abs(v)):
                conf, src = 0.5, "price tag text (disagrees with the axis position; possible misread)"
            if spec is not None and abs(snap(v, spec) - v) > 1e-6:
                conf, src = min(conf, 0.3), "price tag text is off the tick grid (likely misread)"
            r.price = Observation(v, TEXT, conf, src)
        else:
            r.problems.append("Current price tag not readable on the price axis.")
            r.price = unavailable("no price tag found on the axis")
    # plot area
    header_h = int(max([t.y1 for t in _header_tokens(tokens, h)], default=0.05 * h)) + 4
    axis_left = int(profile.axis_x) if profile.axis_x is not None else int(fit.x_left - 10) if fit is not None else int(w * 0.9)
    plot = (0, header_h, max(axis_left, 20), int(h * float(profile.plot_bottom)))
    r.plot = plot
    r.signature = {"size": [w, h], "axis_left": axis_left, "header_h": header_h}
    if fit is None:
        r.ok = False
        r.confidence = 0.0
        return r
    # candles
    up_rgb, dn_rgb = profile.up_color, profile.down_color
    if up_rgb is None or dn_rgb is None:
        a_up, a_dn = auto_candle_colors(img[plot[1]:plot[3], plot[0]:plot[2]])
        up_rgb, dn_rgb = up_rgb or a_up, dn_rgb or a_dn
    r.colors = {"up": up_rgb, "down": dn_rgb, "source": "profile" if profile.up_color else "detected"}
    if up_rgb is None or dn_rgb is None:
        r.problems.append("Candle colors not found; set them in the chart profile.")
        r.ok = False
        return r
    exclude = None
    line_cols = [c for c in [profile.vwap_color, *profile.ema_colors.values()] if c]
    if line_cols:
        exclude = np.zeros(img.shape[:2], bool)
        for c in line_cols:
            exclude |= color_mask(img, c, 18)
    raw, stats = extract_candles(img, plot, up_rgb, dn_rgb, profile.color_tolerance, exclude)
    tick = float(spec.tick_size) if spec else None
    ticks_per_px = abs(fit.slope) / tick if tick else None
    base_conf = 0.85 if ticks_per_px is None else float(np.clip(1.0 - 0.12 * ticks_per_px, 0.25, 0.9))
    if stats.get("median_width", 9) < 3:
        base_conf *= 0.5
        r.problems.append("Candles are very narrow (zoomed out): candle bodies can't be separated reliably. Zoom in.")
    candles = []
    for c in raw:
        sp = (lambda y: snap(fit.price_at(y), spec)) if spec else (lambda y: round(fit.price_at(y), 4))
        conf = base_conf * (0.6 if c["merged"] else 1.0) * (1.0 if c["body_known"] else 0.6)
        candles.append(Candle(c["x0"], c["x1"], sp(c["y_open"]) if c["y_open"] is not None else None, sp(c["y_high"]), sp(c["y_low"]),
                              sp(c["y_close"]) if c["y_close"] is not None else None, c["dir"], round(conf, 2), c["body_known"]))
    # the right-most candle is the forming one; its close should agree with the price tag
    if candles and r.price.value is not None and candles[-1].close is not None:
        tol = 4 * abs(fit.slope) + (tick or 0)
        if abs(candles[-1].close - r.price.value) > max(tol, 3 * (tick or 0.25)):
            r.problems.append("The last candle doesn't end at the price tag; the newest candle may be hidden or the reading is off.")
            candles[-1].confidence = round(candles[-1].confidence * 0.5, 2)
    r.candles = candles
    r.candle_confidence = float(np.median([c.confidence for c in candles])) if candles else 0.0
    if len(candles) < 10:
        r.problems.append(f"Only {len(candles)} candles readable; at least 10 are needed for structure.")
    # volume
    centers = [c.cx for c in candles]
    if profile.plot_bottom < 0.97 and candles:
        pane = (0, int(h * profile.plot_bottom) + 2, plot[2], h - 2)
        vols = volume_heights(img, pane, centers)
        found = sum(1 for v in vols if v)
        if found >= 0.5 * len(candles):
            for c, v in zip(candles, vols, strict=True):
                c.volume_rel = None if v is None else round(v, 4)
            r.volume = Observation("relative bar heights", ESTIMATED, 0.6, "volume pane (relative size only, no contract counts)")
        else:
            r.volume = unavailable("no volume bars found in the volume pane")
    else:
        r.volume = unavailable("no volume pane configured")
    # indicator lines (named only by the colors you assigned)
    named = {"VWAP": profile.vwap_color, **{f"EMA {k}": v for k, v in profile.ema_colors.items()}}
    for name, col in named.items():
        if not col:
            r.indicators[name] = unavailable("color not assigned in the chart profile").to_dict()
            continue
        ys = line_values(img, plot, col, 22, centers)
        seen = [y for y in ys if y is not None]
        if len(seen) < 0.3 * max(1, len(centers)):
            r.indicators[name] = unavailable(f"no line in the assigned color found ({len(seen)}/{len(centers)} candles)").to_dict()
            continue
        vals = [None if y is None else (snap(fit.price_at(y), spec) if spec else round(fit.price_at(y), 4)) for y in ys]
        r.indicators[name] = {"values": vals, "class": ESTIMATED, "confidence": round(base_conf * len(seen) / max(1, len(centers)), 2),
                              "last": next((v for v in reversed(vals) if v is not None), None), "source": "line pixels in the assigned color"}
    # horizontal levels (B: price from the calibrated axis); labelled by nearby text when there is one
    from .vision import horizontal_lines
    for y in horizontal_lines(img, plot):
        name = None
        near = [t for t in tokens if abs(t.cy - y) < 10 and t.cx < plot[2] and re.search(r"[A-Za-z]{2,}", t.text)]
        if near:
            name = near[0].text.strip()[:24]
        pv = snap(fit.price_at(y), spec) if spec else round(fit.price_at(y), 4)
        r.levels.append({"price": pv, "y": round(y, 1), "label": name, "class": CALCULATED, "confidence": round(base_conf, 2),
                         "source": "visible horizontal line"})
    # overall confidence = the weakest input a recommendation needs
    parts = [r.price.confidence, axis_info["confidence"] if axis_info else 0, r.instrument.confidence, r.timeframe.confidence,
             r.candle_confidence]
    r.confidence = float(min(parts))
    if r.confidence < 0.4:
        r.problems.append(f"Overall reading confidence is low ({r.confidence:.2f}).")
    r.ok = bool(candles) and r.price.value is not None
    return r
