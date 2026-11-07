"""OCR + chart computer vision + platform parsing. Pure functions on images: no capture, no I/O.

What it can recognize reliably: ticker and timeframe (from the window title and header text),
printed prices on the price axis, and the highlighted last-price tag.
What it estimates (always labeled as visual estimates): horizontal lines you drew (as prices),
recent candle colors, visible indicator names, and position info on screen.
When it can't recognize something, it says so instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from ..market_data.types import Timeframe

# ---------------- OCR ----------------

_OCR = None


@dataclass
class Token:
    text: str
    conf: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2


def ocr(img: np.ndarray, offset: tuple[int, int] = (0, 0), scale: float = 1.0, pad: int = 64, _retry: bool = True) -> list[Token]:
    """RapidOCR (local, CPU, no network). The text detector needs margin around text and dark
    themes need inverting, so each region is inverted if dark, padded white, and upscaled.
    Coordinates are mapped back to the full image."""
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR = RapidOCR()
    if img.size == 0:
        return []
    work = 255 - img if float(img.mean()) < 110 else img
    work = cv2.copyMakeBorder(work, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    if scale != 1.0:
        work = cv2.resize(work, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    res, _ = _OCR(work)
    out = []
    for box, text, conf in res or []:
        xs = [p[0] / scale - pad + offset[0] for p in box]
        ys = [p[1] / scale - pad + offset[1] for p in box]
        out.append(Token(text.strip(), float(conf), min(xs), min(ys), max(xs), max(ys)))
    if not out and _retry:  # the detector is sensitive to canvas size; one retry with different geometry
        return ocr(img, offset, 1.5, 96, _retry=False)
    return out


# ---------------- parsing ----------------

UI_WORDS = {"USD", "NYSE", "NASDAQ", "AMEX", "ARCA", "BATS", "OTC", "CBOE", "VOL", "VOLUME", "RSI", "EMA", "SMA", "MA", "VWAP",
            "MACD", "BB", "BUY", "SELL", "LONG", "SHORT", "CLOSE", "OPEN", "HIGH", "LOW", "QTY", "AVG", "P&L", "PNL", "D", "W", "M",
            "H", "L", "O", "C", "ALERT", "TRADE", "CHART", "LIVE", "DELAYED", "ET", "EST", "EDT", "AM", "PM", "LOG", "AUTO",
            "ADJ", "EXT", "REG", "MKT", "LMT", "STP", "DAY", "GTC", "IN", "ON", "OF", "THE", "AND", "TO", "A", "I", "STOCH", "ATR",
            "OBV", "ROC", "ADD", "UTC", "NEW", "YES", "NO", "OK", "ALL", "TV", "IBKR", "TOS", "TRADINGVIEW", "WEBULL", "UNNAMED",
            "INDICATORS", "SAVE", "SHARE", "PUBLISH", "REPLAY", "GOOGLE", "CHROME", "EDGE", "FIREFOX"}

TF_PATTERNS = [
    (re.compile(r"^(\d{1,3})\s?(m|min|mins|minute|minutes)$", re.I), lambda m: int(m.group(1))),
    (re.compile(r"^(\d{1,2})\s?(h|hr|hour|hours)$", re.I), lambda m: int(m.group(1)) * 60),
    (re.compile(r"^(1\s?)?(d|day|daily)$", re.I), lambda m: 1440),
    (re.compile(r"^(1\s?)?(w|wk|week|weekly)$", re.I), lambda m: 10080),
]
SUPPORTED_MIN = {1: Timeframe.M1, 2: Timeframe.M2, 5: Timeframe.M5, 15: Timeframe.M15, 30: Timeframe.M30, 60: Timeframe.H1,
                 240: Timeframe.H4, 1440: Timeframe.D1}
NUM = re.compile(r"^[\$]?-?\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^[\$]?-?\d+(?:\.\d+)?$")
AUTH_WORDS = re.compile(r"password|passcode|sign[\s-]?in|log[\s-]?in|two[\s-]?factor|2fa|verification code|one[\s-]?time code|"
                        r"security question|social security|routing number|card number|cvv", re.I)
INDICATOR_WORDS = {"VWAP": "VWAP", "EMA": "EMA", "SMA": "SMA", "RSI": "RSI", "MACD": "MACD", "VOL": "Volume", "VOLUME": "Volume",
                   "BB": "Bollinger Bands", "BOLLINGER": "Bollinger Bands", "STOCH": "Stochastic", "ATR": "ATR", "OBV": "OBV"}


def tf_from_text(s: str) -> tuple[Timeframe | None, str | None]:
    s = s.strip().strip("·|•,()[]").strip()
    m0 = re.match(r"^([\dOo]+)(.*)$", s)
    if m0 and any(c.isdigit() for c in m0.group(1)):
        s = m0.group(1).replace("O", "0").replace("o", "0") + m0.group(2)  # OCR reads '30' as '3O'
    minutes = None
    if s.isdigit() and int(s) in (1, 2, 3, 5, 10, 15, 30, 45, 60, 120, 240):
        minutes = int(s)  # TradingView's bare-number intervals are minutes
    for pat, fn in TF_PATTERNS:
        m = pat.match(s)
        if m:
            minutes = fn(m)
            break
    if minutes is None:
        return None, None
    if minutes in SUPPORTED_MIN:
        return SUPPORTED_MIN[minutes], None
    nearest = min(SUPPORTED_MIN, key=lambda k: abs(k - minutes))
    return SUPPORTED_MIN[nearest], f"Chart is {s}; analyzing the nearest supported timeframe {SUPPORTED_MIN[nearest].value}."


def parse_number(s: str) -> float | None:
    s = s.replace(" ", "").replace("O", "0") if re.fullmatch(r"[\dO.,$]+", s.replace(" ", "")) else s.replace(" ", "")
    if not NUM.match(s):
        return None
    try:
        return float(s.replace("$", "").replace(",", ""))
    except ValueError:
        return None


TITLE_PATTERNS = [
    # TradingView tab: "TSLA 359.40 ▲ +4.61% Unnamed - Google Chrome" ; "NASDAQ:TSLA ..."
    ("tradingview", re.compile(r"^(?:[A-Z]+:)?([A-Z][A-Z0-9.\-]{0,9})\s+([\d,]+\.\d+)\s*[▲▼+\-−]")),
    # generic "TSLA - something" or "TSLA | ..."
    ("generic", re.compile(r"^(?:[A-Z]+:)?([A-Z][A-Z0-9.\-]{0,5})\s*[\-|·:]\s")),
]


def guess_platform(title: str, process: str | None) -> str:
    t, p = (title or "").lower(), (process or "").lower()
    if "tradingview" in t or "tradingview" in p or "unnamed" in t:
        return "tradingview"
    if "thinkorswim" in t or "thinkorswim" in p:
        return "thinkorswim"
    if "webull" in t or "webull" in p:
        return "webull"
    if p.startswith("tws") or "trader workstation" in t or "interactive brokers" in t:
        return "ibkr"
    return "generic"


BROWSER_PROCESSES = ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi", "arc")
TRADING_TITLE_WORDS = ("tradingview", "thinkorswim", "webull", "trader workstation", "interactive brokers",
                       "charles schwab", "schwab", "td ameritrade", "tradestation", "e*trade", "fidelity active trader",
                       "finviz", "yahoo finance", "study terminal")


def is_browser(process: str | None) -> bool:
    p = (process or "").lower()
    return any(b in p for b in BROWSER_PROCESSES)


def title_looks_like_trading(title: str, process: str | None) -> bool:
    """Privacy guard for browser windows: a browser window can switch tabs to email or a bank.
    Only titles that look like a chart/trading page are analyzed."""
    t = (title or "").strip()
    low = t.lower()
    if any(w in low for w in TRADING_TITLE_WORDS) or guess_platform(t, None) != "generic":
        return True
    return any(pat.match(t) for name, pat in TITLE_PATTERNS if name == "tradingview")


@dataclass
class Recognition:
    ticker: str | None = None
    ticker_confidence: float = 0.0
    ticker_source: str | None = None
    ticker_candidates: list[str] = field(default_factory=list)
    timeframe: Timeframe | None = None
    timeframe_note: str | None = None
    timeframe_source: str | None = None
    title_price: float | None = None


def recognize(title: str, header_tokens: list[Token], platform: str) -> Recognition:
    r = Recognition()
    for name, pat in TITLE_PATTERNS:
        m = pat.match(title or "")
        if m and m.group(1) not in UI_WORDS:
            r.ticker, r.ticker_confidence, r.ticker_source = m.group(1), 0.95 if name == "tradingview" else 0.6, f"window title ({name})"
            if name == "tradingview":
                r.title_price = parse_number(m.group(2))
            break
    # timeframe + ticker from header text
    texts = []
    for t in header_tokens:
        txt = re.sub(r"(?<=[A-Za-z])\.(?=\d)|(?<=\d)\.(?=[A-Za-z])|(?:^|\s)\.|\.(?:\s|$)", " ", t.text)  # 'AMD.3 .NASDAQ' (OCR'd middle dots)
        for x in re.split(r"[\s·•|,;:]+", txt):
            x = x.strip(".")
            if x:
                texts.append(x)
    for i, x in enumerate(texts):
        tf, note = tf_from_text(x)
        if tf and r.timeframe is None:
            r.timeframe, r.timeframe_note, r.timeframe_source = tf, note, "on-screen text"
    cands = []
    for x in texts:
        x2 = x.split(":")[-1].strip("·|,()").upper() if ":" in x else x.strip("·|,()")
        if re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", x2) and x2 not in UI_WORDS:
            cands.append(x2)
    r.ticker_candidates = list(dict.fromkeys(cands))[:5]
    if r.ticker is None and r.ticker_candidates:
        r.ticker, r.ticker_confidence, r.ticker_source = r.ticker_candidates[0], 0.5, "on-screen text (needs market-data confirmation)"
    return r


def detect_auth_screen(title: str, tokens: list[Token]) -> str | None:
    blob = " ".join([title or ""] + [t.text for t in tokens])
    m = AUTH_WORDS.search(blob)
    return m.group(0) if m else None


# ---------------- chart geometry ----------------

@dataclass
class AxisFit:
    slope: float
    intercept: float
    n: int
    max_resid_pct: float
    x_left: float

    def price_at(self, y: float) -> float:
        return self.slope * y + self.intercept

    def y_at(self, price: float) -> float:
        return (price - self.intercept) / self.slope


def fit_price_axis(tokens: list[Token], width: int) -> AxisFit | None:
    """Price = a*y + b from numeric labels on the right-hand price axis (robust Theil-Sen fit)."""
    pts = [(t.cy, v, t) for t in tokens if t.cx > width * 0.8 and (v := parse_number(t.text)) is not None]
    if len(pts) < 3:
        return None
    pts.sort()
    ys, vs = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    slopes = [(vs[j] - vs[i]) / (ys[j] - ys[i]) for i in range(len(ys)) for j in range(i + 1, len(ys)) if abs(ys[j] - ys[i]) > 3]
    if not slopes:
        return None
    a = float(np.median(slopes))
    b = float(np.median(vs - a * ys))
    resid = np.abs(vs - (a * ys + b))
    inliers = resid <= max(0.002 * np.median(np.abs(vs)), 1e-6)
    if inliers.sum() < 3 or a >= 0:  # prices must rise going up the screen
        return None
    ys, vs = ys[inliers], vs[inliers]
    a, b = np.polyfit(ys, vs, 1)
    resid = np.abs(vs - (a * ys + b))
    return AxisFit(float(a), float(b), int(len(ys)), float(100 * resid.max() / np.median(np.abs(vs))),
                   float(min(p[2].x0 for p in pts)))


def last_price_tag(img: np.ndarray, tokens: list[Token], width: int) -> tuple[float | None, float | None]:
    """The colored box on the price axis holding the current price (green/red/blue background)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    best, best_s = None, 0.0
    for t in tokens:
        if t.cx <= width * 0.8:
            continue
        v = parse_number(t.text)
        if v is None:
            continue
        y0, y1, x0, x1 = int(max(t.y0 - 2, 0)), int(t.y1 + 2), int(max(t.x0 - 4, 0)), int(min(t.x1 + 4, width))
        patch = hsv[y0:y1, x0:x1]
        if patch.size == 0:
            continue
        sat = float(np.percentile(patch[:, :, 1], 75))
        if sat > 90 and sat > best_s:
            best, best_s = (v, t.cy), sat
    return best if best else (None, None)


def chart_area(img: np.ndarray, axis: AxisFit | None, header_h: int) -> tuple[int, int, int, int]:
    h, w = img.shape[:2]
    x1 = int(axis.x_left - 4) if axis else int(w * 0.9)
    return 0, header_h, max(x1, 10), int(h * 0.92)


def horizontal_lines(img: np.ndarray, area: tuple[int, int, int, int]) -> list[float]:
    """Y positions of long, distinctly colored horizontal lines (user-drawn levels), excluding faint gridlines."""
    x0, y0, x1, y1 = area
    roi = img[y0:y1, x0:x1]
    if roi.size == 0:
        return []
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    bg = np.median(hsv[:, :, 2])
    strong = ((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 80)) | (np.abs(hsv[:, :, 2].astype(int) - bg) > 90)
    mask = strong.astype(np.uint8) * 255
    width = x1 - x0
    rows = (mask > 0).sum(axis=1)
    ys = np.where(rows > 0.45 * width)[0]
    out, last = [], -10
    for y in ys:
        if y - last > 3:
            out.append(float(y + y0))
        last = y
    return out


def candle_colors(img: np.ndarray, area: tuple[int, int, int, int], n: int = 5) -> list[str]:
    """Colors of the right-most candles (approximate): 'up' (green) / 'down' (red)."""
    x0, y0, x1, y1 = area
    hsv = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    green = ((hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 95) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 70)).sum(axis=0)
    red = (((hsv[:, :, 0] <= 10) | (hsv[:, :, 0] >= 165)) & (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 70)).sum(axis=0)
    h = y1 - y0
    col = np.where((green >= 1) & (green < 0.4 * h), 1, np.where((red >= 1) & (red < 0.4 * h), -1, 0))  # skip full-height lines
    runs, cur, start = [], 0, 0
    for i, c in enumerate(list(col) + [0]):
        if c != cur:
            if cur != 0 and i - start >= 2:
                runs.append("up" if cur == 1 else "down")
            cur, start = c, i
    return runs[-n:]


INDICATOR_RE = re.compile(r"[VW]WAP|EMA|SMA|RSI|MACD|BOLLINGER|\bBB\b|STOCH|ATR|OBV|VOLUME|\bVOL\b")


def indicators_visible(tokens: list[Token]) -> list[str]:
    """OCR often glues legend words together ('VWAPEMA9RSI14'), so match substrings."""
    found = []
    for t in tokens:
        for m in INDICATOR_RE.finditer(t.text.upper()):
            key = "VWAP" if m.group(0).endswith("WAP") else m.group(0).strip()
            name = INDICATOR_WORDS.get(key, key.title())
            if name not in found:
                found.append(name)
    return found


def position_info(tokens: list[Token]) -> dict | None:
    """Best-effort: numbers next to 'Qty'/'Position'/'Avg'/'P&L' labels. Always flagged as unverified."""
    out = {}
    labels = {"qty": "quantity", "position": "quantity", "shares": "quantity", "avg": "avg_price", "p&l": "pnl", "pnl": "pnl",
              "unrealized": "pnl"}
    for i, t in enumerate(tokens):
        key = labels.get(t.text.lower().strip(":"))
        if not key:
            continue
        near = sorted((o for o in tokens if o is not t and abs(o.cy - t.cy) < 12 and o.x0 > t.x0), key=lambda o: o.x0)
        for o in near[:2]:
            v = parse_number(o.text)
            if v is not None:
                out[key] = v
                break
    return {**out, "verified": False, "note": "Read from your screen by OCR; not verified."} if out else None


# OCR text detection on small legend text is sensitive to canvas geometry (and varies slightly across
# machines), so the header is retried with a few geometries; the one that worked last is tried first.
_HEADER_GEOMS = [(1.0, 64), (2.0, 64), (2.0, 32), (1.5, 96)]


def _header_cascade(region: np.ndarray, header: list[Token], title: str, platform: str) -> list[Token]:
    def complete(tokens):
        r = recognize(title, tokens, platform)
        return bool(r.ticker and r.timeframe and indicators_visible(tokens))

    if complete(header):
        return header
    for i, (scale, pad) in enumerate(list(_HEADER_GEOMS)):
        header = header + ocr(region, (0, 0), scale=scale, pad=pad, _retry=False)
        if complete(header):
            _HEADER_GEOMS.insert(0, _HEADER_GEOMS.pop(i))  # remember what works on this machine
            break
    return header


def analyze_image(img: np.ndarray, title: str = "", process: str | None = None) -> dict:
    """Full pipeline on one frame."""
    h, w = img.shape[:2]
    platform = guess_platform(title, process)
    header_h = max(int(h * 0.14), 40)
    scale = min(1.0, 1600 / w)  # one full-frame OCR pass; big screens are downscaled for speed
    tokens = ocr(img, (0, 0), scale=scale, pad=16, _retry=False)
    auth = detect_auth_screen(title, tokens)
    if auth:
        return {"blocked": True, "reason": f"Possible login/sensitive screen detected ('{auth}'). Analysis paused for this frame; nothing was kept."}
    # dedicated header pass: small legend text needs more canvas than the full-frame pass gives it
    header = [t for t in tokens if t.cy < header_h]
    header = _header_cascade(img[:header_h], header, title, platform)
    axis_x = int(w * 0.8)
    axis_tokens = [t for t in tokens if t.cx > axis_x]
    if fit_price_axis(axis_tokens, w) is None:  # retry the axis strip on its own
        axis_tokens = ocr(img[:, axis_x:], (axis_x, 0), pad=32)
    rec = recognize(title, header, platform)
    axis = fit_price_axis(axis_tokens, w)
    tag_price, tag_y = last_price_tag(img, axis_tokens, w)
    visible_price, price_source = tag_price, "price-axis tag"
    if visible_price is None and rec.title_price is not None:
        visible_price, price_source = rec.title_price, "window title"
    area = chart_area(img, axis, header_h)
    lines = []
    if axis:
        for y in horizontal_lines(img, area):
            if tag_y is not None and abs(y - tag_y) < 6:
                continue  # the current-price line itself
            lines.append({"y": round(y, 1), "price_estimate": round(axis.price_at(y), 2)})
    unknown = []
    if not rec.ticker:
        unknown.append("ticker")
    if not rec.timeframe:
        unknown.append("timeframe")
    if visible_price is None:
        unknown.append("visible price")
    if not axis:
        unknown.append("price axis (log scale, hidden axis, or unreadable)")
    return {
        "blocked": False, "platform": platform, "title": title,
        "ticker": rec.ticker, "ticker_confidence": rec.ticker_confidence, "ticker_source": rec.ticker_source,
        "ticker_candidates": rec.ticker_candidates,
        "timeframe": rec.timeframe.value if rec.timeframe else None, "timeframe_note": rec.timeframe_note,
        "visible_price": visible_price, "visible_price_source": price_source if visible_price is not None else None,
        "price_axis": {"points": axis.n, "max_error_pct": round(axis.max_resid_pct, 3)} if axis else None,
        "drawn_levels": lines[:8], "recent_candles": candle_colors(img, area) if axis else [],
        "indicators_visible": indicators_visible(header + axis_tokens),
        "position_on_screen": position_info(tokens),
        "could_not_recognize": unknown,
        "note": "Drawn levels and candle colors are visual estimates. Trading levels always come from market data.",
    }
