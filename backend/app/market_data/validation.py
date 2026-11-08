"""Bar validation. Every bar from any provider passes through here before it is used.

What happens to bad data (nothing is silently "fixed" in a way that changes prices):
  dropped   impossible bars: non-finite or non-positive prices, high < low,
            open/close far outside the bar's own high-low range, duplicate timestamps (last kept)
  repaired  tiny rounding inconsistencies only: open/close a hair outside high/low
            (<= 0.05%), where high/low are widened to include them; negative volume -> 0
  flagged   suspicious but possible: a single bar whose range is many times the local norm
            and that reverts immediately (classic bad print). Kept, marked `suspect`, and the
            signal engine refuses to trigger off it.
  gaps      missing 1-minute..1-hour candles inside the regular session (09:30-16:00 ET)

The report travels with the data so the UI can show it next to the chart.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..core.market_clock import ET
from .types import Bar

REPAIR_TOL = 0.0005        # 0.05%: rounding noise we'll widen high/low for
SPIKE_RANGE_X = 8.0        # bar range vs median range of its neighbours
SPIKE_MIN_PCT = 0.02       # and at least 2% of price, so normal volatility never trips it


@dataclass
class QualityReport:
    checked: int = 0
    dropped: list[dict] = field(default_factory=list)
    repaired: int = 0
    suspect: list[str] = field(default_factory=list)       # ISO timestamps of flagged bars
    gaps: list[dict] = field(default_factory=list)         # {"after": iso, "missing": n}
    missing_candles: int = 0
    expected_candles: int = 0

    @property
    def ok(self) -> bool:
        return not self.dropped and not self.suspect and self.gap_ratio < 0.02

    @property
    def gap_ratio(self) -> float:
        return self.missing_candles / self.expected_candles if self.expected_candles else 0.0

    def summary(self) -> str:
        parts = []
        if self.dropped:
            parts.append(f"{len(self.dropped)} invalid bar(s) removed")
        if self.repaired:
            parts.append(f"{self.repaired} bar(s) with rounding fixed")
        if self.suspect:
            parts.append(f"{len(self.suspect)} suspicious spike(s) flagged")
        if self.missing_candles:
            parts.append(f"{self.missing_candles} missing candle(s) in regular hours ({100 * self.gap_ratio:.1f}%)")
        return "; ".join(parts) if parts else "No problems found"

    def to_dict(self) -> dict:
        return {"ok": self.ok, "checked": self.checked, "dropped": self.dropped[:20], "dropped_count": len(self.dropped),
                "repaired": self.repaired, "suspect": self.suspect[-20:], "suspect_count": len(self.suspect),
                "gaps": self.gaps[-20:], "missing_candles": self.missing_candles, "expected_candles": self.expected_candles,
                "gap_ratio": round(self.gap_ratio, 4), "summary": self.summary()}


def _finite_pos(*xs: float) -> bool:
    return all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in xs)


def validate_bars(bars: list[Bar], bar_seconds: int | None = None) -> tuple[list[Bar], QualityReport]:
    rep = QualityReport(checked=len(bars))
    if not bars:
        return [], rep
    by_ts: dict[datetime, Bar] = {}
    for b in bars:
        if b.ts in by_ts:
            rep.dropped.append({"ts": b.ts.isoformat(), "reason": "duplicate timestamp (kept the later copy)"})
        by_ts[b.ts] = b
    clean: list[Bar] = []
    for ts in sorted(by_ts):
        b = by_ts[ts]
        o, h, lo, c = b.open, b.high, b.low, b.close
        if not _finite_pos(o, h, lo, c):
            rep.dropped.append({"ts": ts.isoformat(), "reason": "missing, zero or negative price"})
            continue
        if h < lo:
            rep.dropped.append({"ts": ts.isoformat(), "reason": f"high {h} below low {lo}"})
            continue
        top, bot = max(o, c), min(o, c)
        if top > h * (1 + REPAIR_TOL) or bot < lo * (1 - REPAIR_TOL):
            rep.dropped.append({"ts": ts.isoformat(), "reason": "open/close outside the bar's high-low range"})
            continue
        upd = {}
        if top > h:
            upd["high"] = top
        if bot < lo:
            upd["low"] = bot
        if b.volume is not None and b.volume < 0:
            upd["volume"] = 0.0
        if upd:
            rep.repaired += 1
            b = b.model_copy(update=upd)
        clean.append(b)
    if bar_seconds and bar_seconds <= 3600:
        # Intraday: judge spikes against regular-session neighbours only. Pre/after-hours prints are
        # thin by nature, and the opening bar's range always dwarfs the premarket's.
        reg = [b for b in clean if _regular_minute(b.ts) is not None]
        by_day: dict = {}
        for b in reg:
            by_day.setdefault(b.ts.astimezone(ET).date(), []).append(b)
        for day in by_day.values():
            _flag_spikes(day, rep, skip_first=1)
        _find_gaps(clean, bar_seconds, rep)
    else:
        _flag_spikes(clean, rep)
    return clean, rep


def _flag_spikes(bars: list[Bar], rep: QualityReport, window: int = 10, skip_first: int = 0) -> None:
    n = len(bars)
    if n < 5:
        return
    ranges = [b.high - b.low for b in bars]
    for i in range(max(1, skip_first + 1), n - 1):
        lo_i, hi_i = max(0, i - window), min(n, i + window + 1)
        neigh = sorted(ranges[j] for j in range(lo_i, hi_i) if j != i)
        med = neigh[len(neigh) // 2] if neigh else 0
        b, prev, nxt = bars[i], bars[i - 1], bars[i + 1]
        if med <= 0 or ranges[i] < SPIKE_RANGE_X * med or ranges[i] < SPIKE_MIN_PCT * b.close:
            continue
        # reverts: the next bar trades back near where the previous bar was (a real move holds)
        ref = prev.close
        far = max(abs(b.high - ref), abs(b.low - ref))
        if abs(nxt.close - ref) < 0.3 * far:
            rep.suspect.append(b.ts.isoformat())


def _regular_minute(ts: datetime) -> int | None:
    t = ts.astimezone(ET)
    m = t.hour * 60 + t.minute
    return m if 570 <= m < 960 else None


def _find_gaps(bars: list[Bar], bar_seconds: int, rep: QualityReport) -> None:
    step = timedelta(seconds=bar_seconds)
    reg = [b for b in bars if _regular_minute(b.ts) is not None]
    days: dict = {}
    for b in reg:
        days.setdefault(b.ts.astimezone(ET).date(), []).append(b)
    for day_bars in days.values():
        first, last = day_bars[0].ts, day_bars[-1].ts
        expected = int((last - first) / step) + 1
        rep.expected_candles += expected
        for a, b in zip(day_bars, day_bars[1:], strict=False):
            missing = int((b.ts - a.ts) / step) - 1
            if missing > 0:
                rep.missing_candles += missing
                rep.gaps.append({"after": a.ts.isoformat(), "missing": missing})


def suspect_set(rep: QualityReport | None) -> set[str]:
    return set(rep.suspect) if rep else set()
