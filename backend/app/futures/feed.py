"""Futures feed hygiene: bar validation, missing-candle counts, per-contract health with backoff, and downtime gaps.

Rules:
  * Bad bars are dropped, never "fixed" by guessing: duplicate timestamps (newest copy kept), out-of-order bars
    (re-sorted), impossible OHLC, non-positive prices, timestamps in the future.
  * Prices off the contract's tick grid and outsized one-bar spikes are flagged, not dropped (a real spike is real).
  * Missing candles are counted inside each session window, so the UI can say "12 of 390 one-minute bars missing".
  * A failing source backs off exponentially. While it's down the last good bars are served labeled CACHED, never as
    live, so signals and simulator entries stop until fresh data returns.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .contracts import ProductSpec, round_to_tick
from .sessions import FuturesClock

STATUS_TEXT = {"realtime": "REAL-TIME", "near_realtime": "NEAR REAL-TIME", "polling": "POLLING (live, pulled on a timer)",
               "delayed": "DELAYED", "historical": "HISTORICAL", "replay": "REPLAY", "cached": "CACHED", "stale": "STALE",
               "unavailable": "UNAVAILABLE", "reconcile": "RECONCILED AFTER DOWNTIME"}


def validate_bars(bars: list[dict], tf_seconds: int, spec: ProductSpec, clock: FuturesClock, now: datetime | None = None) -> tuple[list[dict], dict]:
    now = now or datetime.now(timezone.utc)
    rep = {"received": len(bars), "duplicates": 0, "out_of_order": 0, "impossible": 0, "future": 0, "off_tick": 0, "spikes": [],
           "missing_by_session": {}, "missing_total": 0}
    seen: dict = {}
    prev_ts = None
    for b in bars:
        ts = b["ts"]
        if prev_ts is not None and ts < prev_ts:
            rep["out_of_order"] += 1
        prev_ts = ts
        if ts in seen:
            rep["duplicates"] += 1
        vals = [b["open"], b["high"], b["low"], b["close"]]
        if any(v is None or (isinstance(v, float) and math.isnan(v)) or v <= 0 for v in vals) or \
                b["high"] < max(b["open"], b["close"]) - 1e-9 or b["low"] > min(b["open"], b["close"]) + 1e-9 or b["high"] < b["low"]:
            rep["impossible"] += 1
            continue
        if ts > now + timedelta(seconds=tf_seconds):
            rep["future"] += 1
            continue
        seen[ts] = b
    clean = [seen[k] for k in sorted(seen)]
    tick = float(spec.tick)
    ranges = sorted(b["high"] - b["low"] for b in clean) or [0]
    med = ranges[len(ranges) // 2] or tick
    for b in clean:
        if any(abs(round_to_tick(v, spec) - v) > tick / 100 for v in (b["open"], b["high"], b["low"], b["close"])):
            rep["off_tick"] += 1
        if b["high"] - b["low"] > 15 * med and len(rep["spikes"]) < 10:
            rep["spikes"].append({"ts": b["ts"].isoformat(), "range": round(b["high"] - b["low"], 4), "median_range": round(med, 4)})
    # missing candles inside each session window (up to now)
    step = timedelta(seconds=tf_seconds)
    by_td: dict = {}
    for b in clean:
        w = clock.window_at(b["ts"])
        if w:
            by_td.setdefault(w.trade_date, (w, []))[1].append(b["ts"])
    for td, (w, stamps) in by_td.items():
        end = min(w.close, now)
        start = max(w.open, stamps[0])            # count from the first bar we have: older history isn't "missing"
        expected = max(0, int((end - start) / step))
        have = len({s for s in stamps if start <= s < end})
        miss = max(0, expected - have)
        rep["missing_by_session"][td.isoformat()] = {"expected": expected, "have": have, "missing": miss}
        rep["missing_total"] += miss
    rep["kept"] = len(clean)
    rep["ok"] = rep["impossible"] == 0 and rep["future"] == 0
    rep["summary"] = (f"{rep['kept']} bars kept of {rep['received']}"
                      + (f"; dropped {rep['duplicates']} duplicate, {rep['impossible']} impossible, {rep['future']} future-dated"
                         if rep["duplicates"] or rep["impossible"] or rep["future"] else "")
                      + (f"; {rep['out_of_order']} were out of order (re-sorted)" if rep["out_of_order"] else "")
                      + (f"; {rep['off_tick']} off the tick grid" if rep["off_tick"] else "")
                      + (f"; {len(rep['spikes'])} unusually large bars flagged" if rep["spikes"] else ""))
    return clean, rep


@dataclass
class SourceHealth:
    key: str
    last_success: float | None = None          # monotonic
    last_success_wall: str | None = None
    last_error: str | None = None
    failures: int = 0
    next_retry: float = 0.0

    def ok(self) -> None:
        self.last_success, self.last_success_wall = time.monotonic(), datetime.now(timezone.utc).isoformat()
        self.failures, self.last_error, self.next_retry = 0, None, 0.0

    def fail(self, err: str) -> None:
        self.failures += 1
        self.last_error = err
        self.next_retry = time.monotonic() + min(600, 15 * 2 ** min(self.failures, 6))   # 30 s, 60 s ... 10 min

    @property
    def backing_off(self) -> bool:
        return time.monotonic() < self.next_retry

    def to_dict(self) -> dict:
        return {"last_success": self.last_success_wall, "last_error": self.last_error, "consecutive_failures": self.failures,
                "retry_in_seconds": max(0, round(self.next_retry - time.monotonic())) if self.backing_off else 0}


@dataclass
class DowntimeTracker:
    """Detects that the process wasn't running its loop (sleep, suspend, crash) from wall-clock jumps."""
    expected_interval: float = 20.0
    last_tick_wall: datetime | None = None
    gaps: list[dict] = field(default_factory=list)

    def tick(self, now: datetime | None = None) -> dict | None:
        now = now or datetime.now(timezone.utc)
        gap = None
        if self.last_tick_wall is not None:
            secs = (now - self.last_tick_wall).total_seconds()
            if secs > max(90.0, 4 * self.expected_interval):
                gap = {"from": self.last_tick_wall.isoformat(), "to": now.isoformat(), "seconds": round(secs)}
                self.gaps = (self.gaps + [gap])[-50:]
        self.last_tick_wall = now
        return gap
