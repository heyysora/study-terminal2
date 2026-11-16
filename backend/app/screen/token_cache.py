"""Read the text on a chart only when that text has actually changed.

Measured on a real 1919x1074 TopstepX capture, a full chart read cost 6296 ms, of which 6140 ms was OCR. Everything
else -- fitting the price scale, finding 219 candles, indicators, levels -- came to 156 ms. So the chart reader spent
97.5% of its time re-reading words that had not changed since the last time it read them.

The useful thing about a trading chart is that its moving part and its text are in different places. The candles
change on every tick and carry almost no text; the market name, the timeframe and the price-scale numbers are text
and barely change at all. So this splits the picture into three regions and re-reads each only when it has reason to:

  header   the top band -- market, timeframe, the chart's own label.  Re-read when its pixels change.
  axis     the right-hand strip -- the price-scale numbers.           Re-read when the grey numbers change (a rescale).
  tag      the coloured last-price box on that strip.                 Re-read when the coloured pixels change, which is
                                                                      exactly when the price changes. The current price
                                                                      comes from this box, so it is never allowed to be
                                                                      reused while it is moving.
  body     everything else -- labels on lines you drew, position text. Re-read on a slow timer; this text is static
                                                                      and sits on top of candles that always change,
                                                                      so pixel change says nothing useful about it.

Rules that keep this honest, because cached text must never pass for something just observed:
  * A region's words are reused only while that region's pixels are unchanged. Change means re-read, every time.
  * Every region is re-read at least once a minute whatever the pixels say.
  * Any failed or low-confidence reading throws the whole cache away.
  * Each result carries the age of the oldest words in it, so a reading can say how old its text is.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import cv2
import numpy as np

log = logging.getLogger(__name__)

CEILING_SECONDS = 60.0          # re-read every region at least this often, whatever the pixels say
BODY_SECONDS = 30.0             # the body's text is static but sits on moving candles: time, not pixels, decides
HEADER_SECONDS = 8.0            # ceiling on how long a timeframe change can go unnoticed (see the header note below)
DIFF_LEVEL = 25                 # per-pixel difference that counts as a change (same threshold the monitor uses)
DIFF_PIXELS = 3                 # how many changed pixels make a region dirty


@dataclass
class _Region:
    tokens: list = field(default_factory=list)
    grey: np.ndarray | None = None
    read_at: float = 0.0        # monotonic
    ever: bool = False


def _title_key(title: str | None) -> str | None:
    """What in the window title would mean a different chart. TopstepX names the tab after the contract AND its live
    price ("NQZ26 $27,686.25 ▼ -1.24% …"), so the raw string changes on every tick and is useless as a signal. The
    contract on its own is the part that means the chart changed."""
    if title is None:
        return None
    from .platforms import topstepx_title
    parsed = topstepx_title(title)
    return parsed["contract"] if parsed else title


def _dirty(prev: np.ndarray | None, now: np.ndarray, mask: np.ndarray | None = None) -> bool:
    if prev is None or prev.shape != now.shape:
        return True
    d = cv2.absdiff(now, prev) > DIFF_LEVEL
    if mask is not None:
        d = d & mask
    return int(d.sum()) >= DIFF_PIXELS


class TokenCache:
    """Per-chart. Not thread-safe: call it from one place (the monitor calls it inside a worker thread)."""

    def __init__(self, ocr):
        self.ocr = ocr
        self.header = _Region()
        self.axis = _Region()
        self.tag = _Region()
        self.body = _Region()
        self.box_rows: list[tuple[int, int]] = []        # where the coloured boxes sat last time
        self.boxes: dict[tuple[int, int], tuple] = {}    # (rows) -> (how it looked, the words in it)
        self.title: str | None = None                    # the window title the header was last read against
        self.reads = 0           # how many OCR passes were actually run
        self.skips = 0           # how many were avoided

    def forget(self) -> None:
        """Throw everything away: next call re-reads the whole picture. Used whenever a reading can't be trusted."""
        self.header, self.axis, self.tag, self.body = _Region(), _Region(), _Region(), _Region()
        self.box_rows, self.boxes, self.title = [], {}, None

    @staticmethod
    def _box_spans(strip: np.ndarray) -> list[tuple[int, int]]:
        """Each coloured box on the price scale, as a row span with a small margin.

        A chart has more than one: the last-price box, and often an alert line, a position marker or a bid/ask tag.
        They are separate runs of rows, so they are kept separate -- taking the whole range from the first to the
        last would swallow a third of the scale and re-read it every time any of them moved.

        Rows, not pixels: the digits printed inside a box are white, so a pixel test would call them "not the box"
        and every price change would then look like a change to the price scale behind it."""
        hsv = cv2.cvtColor(strip, cv2.COLOR_BGR2HSV)
        hot = (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 70)
        rows = np.where(hot.mean(axis=1) > 0.35)[0]
        if len(rows) == 0:
            return []
        spans, start, prev = [], int(rows[0]), int(rows[0])
        for r in rows[1:]:
            r = int(r)
            if r - prev > 4:                               # a gap: a different box
                spans.append((start, prev))
                start = r
            prev = r
        spans.append((start, prev))
        h = strip.shape[0]
        return [(max(0, a - 6), min(h, b + 7)) for a, b in spans]

    def _bounds(self, img: np.ndarray, signature: dict | None) -> tuple[int, int]:
        """(header height, axis left edge) in region coordinates, from the last good reading when there is one."""
        h, w = img.shape[:2]
        header_h = int(max(60, min(0.25 * h, (signature or {}).get("header_h") or 0.14 * h)))
        axis_left = int((signature or {}).get("axis_left") or 0)
        if not (0 < axis_left < w):
            axis_left = int(w * 0.90)
        axis_left = max(int(w * 0.5), min(w - 20, axis_left - 8))     # a little margin, never more than half the width
        return header_h, axis_left

    def _prime(self, img: np.ndarray, grey: np.ndarray, header_h: int, axis_left: int, now: float,
               title_key: str | None = None) -> None:
        """First read of a chart: one pass over the whole picture, then split the words between the three regions by
        where they sit. One pass costs less than three, and the regions start out warm."""
        every = self.ocr(img, offset=(0, 0))
        self.header.tokens = [t for t in every if t.cy < header_h]
        self.axis.tokens = [t for t in every if t.cy >= header_h and t.cx >= axis_left]
        self.body.tokens = [t for t in every if t.cy >= header_h and t.cx < axis_left]
        self.tag.tokens = []                      # the priming pass already read the box; its words are in axis
        self.header.grey, self.header.read_at, self.header.ever = grey[:header_h, :], now, True
        self.axis.grey, self.axis.read_at, self.axis.ever = grey[:, axis_left:], now, True
        self.box_rows = self._box_spans(img[:, axis_left:])
        gs = grey[:, axis_left:]
        # The priming pass already read these boxes as part of the whole picture; remember their look so the first
        # tick only re-reads the one that moves.
        self.boxes = {(a, b): (gs[a:b, :], [t for t in self.axis.tokens if a <= t.cy <= b]) for a, b in self.box_rows}
        self.tag.read_at, self.tag.ever = now, True
        self.body.grey, self.body.read_at, self.body.ever = None, now, True
        self.title = title_key          # what the window was called when this label was read; a change re-reads it
        self.reads += 1

    def tokens(self, img: np.ndarray, signature: dict | None = None, force: bool = False,
               title: str | None = None) -> tuple[list, dict]:
        """All the words on the chart, re-reading only what has changed. Returns (tokens, meta).

        `title` is the window's own title. TopstepX puts the contract and its live price there, so a change of
        contract shows up in it immediately and forces the header band to be read again."""
        now = time.monotonic()
        h, w = img.shape[:2]
        header_h, axis_left = self._bounds(img, signature)
        grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if not (self.header.ever or self.axis.ever or self.tag.ever or self.body.ever):
            self._prime(img, grey, header_h, axis_left, now, _title_key(title))
            return (self.header.tokens + self.axis.tokens + self.body.tokens,
                    {"regions_read": ["whole chart"], "reused": [], "oldest_text_seconds": 0.0,
                     "age_seconds": {"header": 0.0, "axis": 0.0, "body": 0.0}, "ocr_passes": 1,
                     "bounds": {"header_h": header_h, "axis_left": axis_left}})
        out: list = []
        fresh: list[str] = []
        ages: dict[str, float] = {}

        # --- header: the market, the timeframe, the chart's label
        # Pixels are the wrong trigger here, and this is the most expensive of the three regions. TopstepX writes the
        # live open/high/low/close into the same line as the chart's name ("NQZ26 · Nasdaq · 1  O27,688.00 H…"), so
        # those digits change on every tick -- and at a real 1920-wide capture, re-reading this band cost about a
        # second each time, to be told the same market and the same timeframe it reported a second earlier.
        # Three things can actually change the answer, and each gets a trigger of its own:
        #   the contract      -- the window title carries it and TopstepX updates that on every tick, so watch it;
        #   the layout        -- a resize or zoom changes the band's shape, which is checked directly;
        #   a timeframe change-- no cheap signal exists, so the band is re-read on a timer. That timer is the hard
        #                        ceiling on how long such a change can go unnoticed, and until the band is re-read
        #                        the reading still carries the age of this text, so nothing passes for fresher than
        #                        it is. The quality gates refuse to act on a timeframe they can't stand behind.
        g = grey[:header_h, :]
        key = _title_key(title)
        title_changed = key is not None and self.title is not None and key != self.title
        shape_changed = self.header.grey is None or self.header.grey.shape != g.shape
        # Pixels are the fallback, not the rule. When the window title names the contract, that is an exact and free
        # signal for the thing that matters, so the band's own pixels -- which change on every tick because the live
        # OHLC is printed in them -- are ignored. With no title to trust (a window that doesn't name its contract),
        # there is no cheap signal, so watch the pixels as before and pay for it.
        pixels_changed = key is None and _dirty(self.header.grey, g)
        if (force or not self.header.ever or now - self.header.read_at > HEADER_SECONDS
                or title_changed or shape_changed or pixels_changed):
            self.header.tokens = self.ocr(img[:header_h, :], offset=(0, 0))
            self.header.grey, self.header.read_at, self.header.ever = g, now, True
            self.title = key if key is not None else self.title
            self.reads += 1
            fresh.append("header")
        else:
            self.skips += 1
        out += self.header.tokens
        ages["header"] = now - self.header.read_at

        # --- axis: the price-scale numbers. The coloured last-price box moves on every tick and is read by the fast
        #     path, so it is masked out of the comparison: only the grey scale numbers decide whether to re-read.
        strip = img[:, axis_left:]
        g = grey[:, axis_left:]
        box_now = self._box_spans(strip)
        # Compare only the rows no coloured box is on now and none was on last time. A box slides up and down the
        # scale on every tick and uncovers different numbers as it goes; without excluding where it has just been,
        # every price change would also force a re-read of the whole price scale.
        quiet = np.ones(g.shape, dtype=bool)
        for a, b in list(box_now) + list(self.box_rows):
            quiet[a:b, :] = False
        if force or not self.axis.ever or now - self.axis.read_at > CEILING_SECONDS or _dirty(self.axis.grey, g, quiet):
            self.axis.tokens = self.ocr(strip, offset=(axis_left, 0))
            self.axis.grey, self.axis.read_at, self.axis.ever = g, now, True
            self.reads += 1
            fresh.append("axis")
        else:
            self.skips += 1
        ages["axis"] = now - self.axis.read_at

        # --- tag: the coloured last-price box. THE PRICE COMES FROM HERE, so it is re-read whenever its coloured
        #     pixels move, which is exactly when the price changes. A cached price would be a stale price.
        # Dirty when the box has moved OR when what is printed inside it has changed: a price can tick without the
        # box moving a pixel, and serving that from the cache would be serving a stale price.
        # Box by box: only the one that moved or changed its digits is read again. A chart often shows three or four
        # of these (last price, an alert, a position marker) and reading all of them on every tick would cost more
        # than it saves.
        expired = force or not self.tag.ever or now - self.tag.read_at > CEILING_SECONDS
        boxes, toks, re_read = {}, [], 0
        for a, b in box_now:
            crop = g[a:b, :]
            was = self.boxes.get((a, b))
            if not expired and was is not None and not _dirty(was[0], crop):
                boxes[(a, b)] = was                              # same box, same digits: its words still stand
            else:
                boxes[(a, b)] = (crop, self.ocr(strip[a:b, :], offset=(axis_left, a)))
                re_read += 1
            toks += boxes[(a, b)][1]
        self.boxes = boxes
        self.tag.tokens = toks
        if re_read or expired or box_now != self.box_rows:
            self.tag.read_at, self.tag.ever = now, True
            self.reads += max(1, re_read)
            fresh.append("tag")
        else:
            self.skips += 1
        self.box_rows = box_now
        ages["tag"] = now - self.tag.read_at
        # cached axis words that now sit under the coloured box are dropped: the fresh tag words replace them, so a
        # price can never be served from a picture of the box taken earlier.
        if box_now and self.tag.tokens:
            out += [t for t in self.axis.tokens if not any(a - 4 <= t.cy <= b + 4 for a, b in box_now)]
        else:
            out += self.axis.tokens
        out += self.tag.tokens

        # --- body: labels on lines you drew, position text. Static text over constantly moving candles, so a pixel
        #     comparison would always say "changed" and tell us nothing. A slow timer is the honest rule here.
        if force or not self.body.ever or now - self.body.read_at > BODY_SECONDS:
            self.body.tokens = self.ocr(img[header_h:, :axis_left], offset=(0, header_h))
            self.body.grey, self.body.read_at, self.body.ever = None, now, True
            self.reads += 1
            fresh.append("body")
        else:
            self.skips += 1
        out += self.body.tokens
        ages["body"] = now - self.body.read_at

        meta = {"regions_read": fresh, "reused": [k for k in ("header", "axis", "tag", "body") if k not in fresh],
                "oldest_text_seconds": round(max(ages.values()), 1) if ages else 0.0,
                "age_seconds": {k: round(v, 1) for k, v in ages.items()},
                "ocr_passes": len(fresh), "bounds": {"header_h": header_h, "axis_left": axis_left}}
        return out, meta

    def stats(self) -> dict:
        total = self.reads + self.skips
        return {"ocr_passes": self.reads, "avoided": self.skips,
                "avoided_share": round(self.skips / total, 3) if total else 0.0}
