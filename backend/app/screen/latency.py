"""Where the time actually goes, measured rather than guessed.

Study Terminal watches a chart by taking pictures of it, so there is a floor on how fast it can notice a price
change, and several places where time quietly disappears. This records how long each stage of one pass takes, keeps
the recent history, and reports the distribution -- median, 95th, 99th, worst -- because an average hides exactly the
stalls that make an alert arrive after the move.

Rules this file follows, because getting them wrong would make the numbers lies:

* One monotonic clock for every duration. Wall-clock time can jump; a jump would read as a stall or a negative.
* Durations are measured around the real work, not around a scheduling decision. "Waiting for the next turn" is
  recorded separately from "doing the work", since they have different cures: one is an interval setting, the other
  is code.
* Nothing here is allowed to be slow itself. Recording a stage is an append to a bounded deque.
* What is not measurable is named, not estimated. How long the market took to reach the screen cannot be seen from
  a screenshot, so it is never folded into a total and never implied.
"""
from __future__ import annotations

import os
import sys
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

KEEP = 400                      # recent passes kept per stage; a few minutes of monitoring at normal intervals

# The pipeline, in the order a pass goes through it. The description is what the user reads on the page.
STAGES: dict[str, str] = {
    "wait": "Waiting for the next turn (your capture interval, not work)",
    "capture": "Taking the picture of the window",
    "change": "Deciding whether the picture changed at all",
    "price_box": "Reading the price box only (the fast path)",
    "ocr": "Reading the words on the chart",
    "parse": "Turning the picture into price, candles and levels",
    "analyse": "Indicators and market structure",
    "decide": "Working out whether there is a trade",
    "notify": "Sending the alert",
    "pass": "One whole pass, start to finish",
    "to_decision": "Picture taken to decision ready",
}


@dataclass
class Series:
    """Recent durations for one stage, in milliseconds."""

    name: str
    ms: deque[float] = field(default_factory=lambda: deque(maxlen=KEEP))
    total: int = 0
    worst: float = 0.0

    def add(self, v: float) -> None:
        self.ms.append(v)
        self.total += 1
        self.worst = max(self.worst, v)

    def stats(self) -> dict | None:
        if not self.ms:
            return None
        xs = sorted(self.ms)
        n = len(xs)

        def pct(p: float) -> float:
            # Nearest-rank: with 20 samples the "99th percentile" is the worst one, and saying so is honest.
            return xs[min(n - 1, max(0, int(round(p / 100 * n + 0.5)) - 1))]
        return {"name": self.name, "what": STAGES.get(self.name, self.name), "n": n, "seen": self.total,
                "p50": round(pct(50), 1), "p95": round(pct(95), 1), "p99": round(pct(99), 1),
                "max": round(max(xs), 1), "worst_ever": round(self.worst, 1),
                "mean": round(sum(xs) / n, 1), "last": round(self.ms[-1], 1)}


class Latency:
    """Every stage, plus the counters that say whether the picture stream is keeping up."""

    def __init__(self) -> None:
        self.series: dict[str, Series] = {}
        self.started = time.monotonic()
        self.skipped = 0            # turns that came due while the previous pass was still running
        self.unchanged = 0          # passes where the picture was identical, so there was nothing to read
        self.failed = 0             # passes that produced no usable reading
        self.passes = 0
        self._last_pass_at: float | None = None
        self.gap_ms: Series = Series("gap")   # real time between passes, which is what the user actually feels

    def record(self, stage: str, ms: float) -> None:
        s = self.series.get(stage)
        if s is None:
            s = self.series[stage] = Series(stage)
        s.add(ms)

    @contextmanager
    def time(self, stage: str) -> Iterator[None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.record(stage, (time.perf_counter() - t0) * 1000.0)

    def pass_done(self, *, changed: bool, ok: bool) -> None:
        now = time.monotonic()
        if self._last_pass_at is not None:
            self.gap_ms.add((now - self._last_pass_at) * 1000.0)
        self._last_pass_at = now
        self.passes += 1
        if not changed:
            self.unchanged += 1
        if not ok:
            self.failed += 1

    def skip(self) -> None:
        """A turn came due before the last one finished. Not a dropped frame -- there is no frame queue, the next
        picture is simply taken later -- but it does mean the interval you asked for is not the interval you get."""
        self.skipped += 1

    def bottleneck(self) -> dict | None:
        """The slowest stage that is actual work. Waiting for the next turn is an interval setting, not a bottleneck,
        and 'one whole pass' is the sum, so neither can be the answer."""
        cand = [s.stats() for k, s in self.series.items() if k not in ("wait", "pass", "to_decision") and s.ms]
        cand = [c for c in cand if c]
        if not cand:
            return None
        worst = max(cand, key=lambda c: c["p95"])
        return {"stage": worst["name"], "what": worst["what"], "p95": worst["p95"]}

    def report(self) -> dict:
        up = time.monotonic() - self.started
        stages = [s for s in (self.series[k].stats() for k in STAGES if k in self.series) if s]
        gap = self.gap_ms.stats()
        return {
            "stages": stages,
            "between_passes": gap,
            "passes": self.passes, "unchanged": self.unchanged, "failed": self.failed, "behind": self.skipped,
            "uptime_s": round(up, 1),
            "passes_per_second": round(self.passes / up, 2) if up > 1 else None,
            "bottleneck": self.bottleneck(),
            "resources": resources(),
            "not_measurable": "How long the market itself took to reach your screen. A screenshot cannot show when "
                              "TopstepX received a price, only when it was drawn. Every number here is from the "
                              "moment Study Terminal took the picture onwards.",
        }

    def reset(self) -> None:
        self.series.clear()
        self.gap_ms = Series("gap")
        self.started = time.monotonic()
        self.skipped = self.unchanged = self.failed = self.passes = 0
        self._last_pass_at = None


def resources() -> dict:
    """This process's CPU time and memory, without adding a dependency for it."""
    out: dict = {}
    try:
        t = os.times()
        out["cpu_seconds"] = round(t.user + t.system, 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class _MEM(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
            m = _MEM()
            m.cb = ctypes.sizeof(_MEM)
            if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(m), m.cb):
                out["memory_mb"] = round(m.WorkingSetSize / 1_048_576, 1)
                out["memory_peak_mb"] = round(m.PeakWorkingSetSize / 1_048_576, 1)
        else:
            with open("/proc/self/statm", encoding="utf-8") as fh:
                out["memory_mb"] = round(int(fh.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 1_048_576, 1)
    except Exception:  # noqa: BLE001
        pass
    return out


# One recorder for the whole app. The monitor writes to it; the Health page and the benchmark read it.
METER = Latency()
