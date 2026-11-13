"""Live price from the chart on your screen: a fast read of the price box plus a tape of accepted prices.

Fast read (about 20 ms): find the colored price box in the price-axis column found by the last full chart read, and run text
recognition on that box only. A value is accepted only when every check passes:
  1. it parses as a number and the recognizer is confident,
  2. it sits on the instrument's tick grid,
  3. it agrees with where the box sits on the price scale (the axis fitted by the full read),
  4. it isn't a sudden jump: a move bigger than JUMP_TICKS ticks is held until the next read confirms it.
Anything else is rejected and the caller falls back to a full chart read. Nothing is guessed: no price, no point on the tape.

The tape keeps accepted prices (and gaps when the chart can't be read) per chart profile, in memory and in
<data dir>/live_prices/<YYYY-MM-DD>_<profile>.csv, for the current day and the previous 13 days.
"""
from __future__ import annotations

import csv
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
MIN_REC_CONF = 0.70                 # older OCR models score correct reads ~0.75-0.9; the scale/step/jump checks do the real work
JUMP_TICKS = 40
CONFIRM_TICKS = 4
KEEP_DAYS = 14


@dataclass
class TagRead:
    value: float | None
    confidence: float
    why: str = ""
    candidates: int = 0


def _blobs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Row ranges where at least 35% of the column is strongly colored (price boxes)."""
    rows = mask.mean(axis=1) > 0.35
    out, start = [], None
    for i, on in enumerate(rows):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start >= 8:
                out.append((start, i))
            start = None
    if start is not None and len(rows) - start >= 8:
        out.append((start, len(rows)))
    return out


def _recognize(crop: np.ndarray) -> tuple[str, float]:
    import cv2

    from . import vision
    if vision._OCR is None:
        vision.ocr(np.full((40, 120, 3), 255, np.uint8))      # loads the local OCR model once
    base = 255 - crop if float(crop.mean()) < 110 else crop
    eng = vision._OCR
    rec = getattr(eng, "text_rec", None) or getattr(eng, "text_recognizer", None)   # 1.4+ / 1.2 name for the text recognizer
    if rec is None:
        return "", 0.0
    reads: list[tuple[str, float]] = []
    for fx in (1, 3):                                   # two sizes: models differ in which they read best
        work = base if fx == 1 else cv2.resize(base, None, fx=fx, fy=fx, interpolation=cv2.INTER_CUBIC)
        work = cv2.copyMakeBorder(work, 4 * fx, 4 * fx, 4 * fx, 4 * fx, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        try:
            try:
                out = rec([work], False)                # 1.4+: (images, return_word_box)
            except TypeError:
                out = rec([work])                       # 1.2: (images)
            res = out[0] if isinstance(out, tuple) else out
            reads.append((str(res[0][0]).strip(), float(res[0][1])))
        except (TypeError, IndexError, ValueError, AttributeError):
            continue
    if not reads:
        return "", 0.0
    texts = {t for t, _ in reads}
    if len(texts) == 1:                                 # both sizes agree: as confident as the better read
        return reads[0][0], max(c for _, c in reads)
    t, c = max(reads, key=lambda r: r[1])               # they disagree: take the better one, with less confidence
    return t, c * 0.8


def read_tag(img: np.ndarray, axis: dict | None, tick: float, last: float | None, recognize=_recognize) -> TagRead:
    """The current price from the price box only. `axis` is the full read's axis (x_left, slope, intercept)."""
    import cv2

    from .vision import parse_number
    if not axis or axis.get("x_left") is None or not axis.get("slope"):
        return TagRead(None, 0.0, "no price scale from a full read yet")
    h, w = img.shape[:2]
    x0 = int(max(0, min(w - 10, float(axis["x_left"]) - 6)))
    col = img[:, x0:]
    hsv = cv2.cvtColor(col, cv2.COLOR_BGR2HSV)
    mask = (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 70)
    found = []
    for y0, y1 in _blobs(mask):
        cols = np.where(mask[y0:y1].mean(axis=0) > 0.5)[0]
        if len(cols) < 20:
            continue
        crop = col[y0:y1, cols.min():cols.max() + 1]
        text, conf = recognize(crop)
        v = parse_number(text)
        if v is None:
            continue
        cy = (y0 + y1) / 2
        found.append((v, conf, cy))
    if not found:
        return TagRead(None, 0.0, "no price box found on the price scale")
    slope, icpt = float(axis["slope"]), float(axis["intercept"])
    tol = max(4 * tick, abs(slope) * 12)
    good = []
    for v, conf, cy in found:
        if conf < MIN_REC_CONF:
            continue
        if abs(v / tick - round(v / tick)) > 1e-6:
            continue
        if abs((slope * cy + icpt) - v) > tol:
            continue
        good.append((v, conf, cy))
    if not good:
        return TagRead(None, 0.0, "the price box didn't pass the checks (confidence, price step or price scale)", len(found))
    if len(good) > 1:
        if last is None:
            return TagRead(None, 0.0, "more than one price box on the scale and no earlier price to tell them apart", len(found))
        good.sort(key=lambda g: abs(g[0] - last))
        if abs(good[0][0] - last) * 2 > abs(good[1][0] - last):     # not clearly closer: don't guess
            return TagRead(None, 0.0, "two price boxes are about equally close to the last price", len(found))
    v, conf, _ = good[0]
    return TagRead(v, round(conf, 3), "", len(found))


def session_start(now: datetime) -> datetime:
    """Start of the current CME equity-index trading day: 6:00 PM New York time on the previous evening."""
    n = now.astimezone(ET)
    start = n.replace(hour=18, minute=0, second=0, microsecond=0)
    if n < start:
        start -= timedelta(days=1)
    return start.astimezone(timezone.utc)


@dataclass
class PriceTape:
    """Accepted prices for one chart profile. Points are (epoch seconds, price or None for a gap, method)."""
    pid: str
    folder: Path | None = None
    points: deque = field(default_factory=lambda: deque(maxlen=120_000))
    pending: tuple | None = None                 # (t, price) of a big jump waiting for confirmation
    accepted: int = 0
    rejected: int = 0
    last_reject: str = ""
    _buf: list = field(default_factory=list)
    _flushed: float = 0.0

    def __post_init__(self):
        if self.folder:
            self.folder.mkdir(parents=True, exist_ok=True)
            self._load_recent()
            self._prune()

    def _file(self, t: float) -> Path:
        day = datetime.fromtimestamp(t, ET).strftime("%Y-%m-%d")
        return self.folder / f"{day}_{self.pid}.csv"

    def _load_recent(self) -> None:
        now = time.time()
        for back in (1, 0):
            p = self._file(now - back * 86400)
            if not p.exists():
                continue
            try:
                with p.open(newline="", encoding="utf-8") as f:
                    for row in csv.reader(f):
                        if len(row) >= 2:
                            self.points.append((float(row[0]), float(row[1]) if row[1] else None, row[2] if len(row) > 2 else "saved"))
            except (OSError, ValueError):
                log.warning("couldn't read %s", p)

    def _prune(self) -> None:
        cutoff = (datetime.now(ET) - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
        for p in self.folder.glob(f"*_{self.pid}.csv"):
            if p.name[:10] < cutoff:
                p.unlink(missing_ok=True)

    def last(self) -> tuple | None:
        for pt in reversed(self.points):
            if pt[1] is not None:
                return pt
        return None

    def _append(self, t: float, price: float | None, method: str) -> None:
        self.points.append((t, price, method))
        self._buf.append((t, price, method))
        if self.folder and (time.monotonic() - self._flushed > 5 or len(self._buf) > 200):
            self.flush()

    def flush(self) -> None:
        if not (self.folder and self._buf):
            return
        try:
            by_file: dict[Path, list] = {}
            for t, p, m in self._buf:
                by_file.setdefault(self._file(t), []).append((f"{t:.3f}", "" if p is None else repr(p), m))
            for path, rows in by_file.items():
                with path.open("a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerows(rows)
            self._buf.clear()
            self._flushed = time.monotonic()
        except OSError:
            log.exception("couldn't save live prices")

    def offer(self, t: float, price: float, tick: float, method: str) -> bool:
        """Add a price that passed the reading checks. A sudden jump waits for one confirming read."""
        last = self.last()
        if last is not None and last[1] is not None and t - last[0] < 120:
            jump = abs(price - last[1])
            if jump > JUMP_TICKS * tick:
                if self.pending and abs(self.pending[1] - price) <= CONFIRM_TICKS * tick and t - self.pending[0] < 5:
                    self.pending = None                      # confirmed by a second read: accept
                else:
                    self.pending = (t, price)
                    self.rejected += 1
                    self.last_reject = f"price jumped {jump:g} from {last[1]:g}; waiting for the next read to confirm it"
                    return False
        self.pending = None
        if last is not None and last[1] == price and t - last[0] < 1.0:
            return True                                      # same price within a second: nothing new to draw
        self._append(t, price, method)
        self.accepted += 1
        return True

    def gap(self, t: float) -> None:
        if self.points and self.points[-1][1] is None:
            return
        self._append(t, None, "gap")

    def reject(self, why: str) -> None:
        self.rejected += 1
        self.last_reject = why

    def series(self, since: float, max_points: int = 1500) -> list[list]:
        """Points since `since`, thinned evenly by time when there are many. Gaps (None) are always kept."""
        pts = [p for p in self.points if p[0] >= since]
        if len(pts) <= max_points:
            return [[round(p[0], 3), p[1]] for p in pts]
        span = (pts[-1][0] - pts[0][0]) or 1
        step = span / max_points
        out, bucket_end, last_kept = [], pts[0][0], None
        for p in pts:
            if p[1] is None or p[0] >= bucket_end or p is pts[-1]:
                out.append([round(p[0], 3), p[1]])
                bucket_end = p[0] + step
                last_kept = p
        if last_kept is not pts[-1]:
            out.append([round(pts[-1][0], 3), pts[-1][1]])
        return out

    def session_reference(self, now: datetime) -> tuple[float | None, float | None]:
        s = session_start(now).timestamp()
        for p in self.points:
            if p[0] >= s and p[1] is not None:
                return p[0], p[1]
        return None, None
