"""Reliability watchdog: one plain status per watched chart, the reason, and what to do.

  HEALTHY                 the chart is being read normally
  DEGRADED                still readable, but something is off (slow capture, price box often unreadable, the price scale
                          drifting, a fallback capture method). Prices are still used, with a warning.
  STALE                   no reliable reading recently, or the chart stopped changing while the market is open
  UNREADABLE              the window is there but can't be read (covered, another tab, blank, low confidence)
  DISCONNECTED            the window is gone or minimized, or the reading loop stopped
  REQUIRES_RECALIBRATION  the chart no longer matches its setup (different market or timeframe, layout or scale changed)
  OFF                     watching is turned off

Every status except HEALTHY, DEGRADED and OFF suspends price-based ideas: the chart reader's quality gates already refuse to
recommend anything unless the chart is readable, and an instrument or timeframe that doesn't match the setup is refused there too.
The watchdog never invents a substitute source; it only reports, alerts once per change, and restarts its own reading loop.
"""
from __future__ import annotations

import statistics
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from .plain import plain_reason

CODES = {
    "HEALTHY": ("Working", "ok", False),
    "DEGRADED": ("Working, with problems", "attention", False),
    "STALE": ("Chart isn't updating", "bad", True),
    "UNREADABLE": ("Can't read the chart", "bad", True),
    "DISCONNECTED": ("Can't find the chart", "bad", True),
    "REQUIRES_RECALIBRATION": ("Check chart settings", "bad", True),
    "OFF": ("Not watching", "off", False),
}
REJECT_RATE_DEGRADED = 0.5          # over the last 60 fast reads
FRAME_AGE_DEGRADED = 3.0            # seconds behind the window
DRIFT_TICKS = 2.0                   # median distance between the price box and where the scale puts it


def _result(code: str, reason: str, do: str = "", details: list[str] | None = None) -> dict:
    word, level, suspend = CODES[code]
    return {"code": code, "word": word, "level": level, "suspends_ideas": suspend, "reason": reason, "do": do,
            "details": details or []}


def mismatch(profile, reading) -> str | None:
    """The chart shows a different market or timeframe than the one it was set up for."""
    if reading is None:
        return None
    import re
    for prob in reading.problems or []:                 # the reader notices conflicts with the profile and lowers its confidence
        m = re.search(r"(Instrument|Timeframe) conflict: the chart shows (\S+) but this profile is set to (\S+?)\.?$", prob)
        if m:
            what = "market" if m.group(1) == "Instrument" else "timeframe"
            return f"The chart shows {m.group(2)}, but this chart was set up for the {m.group(3)} {what}." if what == "timeframe" \
                else f"The chart shows {m.group(2)}, but this chart was set up for {m.group(3)}."
    inst, tf = reading.instrument.value, reading.timeframe.value
    if profile is None:
        return None
    if profile.root not in (None, "", "auto") and inst and inst != profile.root and reading.instrument.confidence >= 0.6:
        return f"The chart shows {inst}, but this chart was set up for {profile.root}."
    if profile.timeframe not in (None, "", "auto") and tf and tf != profile.timeframe and reading.timeframe.confidence >= 0.6:
        return f"The chart shows the {tf} timeframe, but it was set up for {profile.timeframe}."
    return None


def assess(rt, *, running: bool, tick: float = 0.25, now_mono: float | None = None) -> dict:
    """Status for one chart runtime (see visual_monitor.Runtime)."""
    now_mono = now_mono if now_mono is not None else time.monotonic()
    if not running or rt.status in ("stopped", "paused"):
        return _result("OFF", "Watching is turned off." if rt.status != "paused" else "Watching is paused.", "Turn watching on.")
    p, r = rt.profile, rt.reading
    reason = rt.reason or ""
    if rt.status == "disconnected":
        w = plain_reason(f"DISCONNECTED: {reason}")
        return _result("DISCONNECTED", w["headline"], w["do"], [reason])
    if (r is not None and r.calibration_valid is False) or any(k in reason for k in ("Layout changed", "Recalibrate", "layout changed",
                                                                                     "capture region is outside")):
        return _result("REQUIRES_RECALIBRATION", "Your chart looks different from when it was set up.",
                       "Open My chart, choose Set up a chart, and select the chart area again.", [reason])
    mm = mismatch(p, r)
    if mm:
        return _result("REQUIRES_RECALIBRATION", mm, "Switch the TopstepX chart back, or set up a new chart for this market.", [mm])
    if rt.status == "stale":
        w = plain_reason(f"STALE: {reason}")
        return _result("STALE", w["headline"], w["do"], [reason])
    if rt.status == "unreadable":
        w = plain_reason(f"UNREADABLE: {reason}")
        return _result("UNREADABLE", w["headline"], w["do"], [reason])
    if rt.status != "screen_capture":
        return _result("STALE", "Starting up; no reading yet.", "Wait a few seconds.")
    problems = []
    tape = rt.tape
    if tape is not None:
        rate, n = tape.recent_reject_rate()
        if n >= 20 and rate >= REJECT_RATE_DEGRADED:
            common = [w for ok, w in tape.recent if not ok]
            top = max(set(common), key=common.count) if common else ""
            problems.append(("The quick price reads are failing often, so prices update more slowly.",
                             f"{rate:.0%} of the last {n} quick reads were rejected ({top})."))
        if len(tape.residuals) >= 10:
            med = statistics.median(abs(x) for x in tape.residuals)
            if med > DRIFT_TICKS * tick:
                problems.append(("The chart's price scale seems to be drifting from where it was measured.",
                                 f"Median gap between the price box and the scale: {med:g} (more than {DRIFT_TICKS:g} ticks)."))
    age = (rt.health or {}).get("frame_age_seconds")
    if age is not None and age > FRAME_AGE_DEGRADED:
        problems.append(("The screen capture is running behind the window.", f"The newest frame was {age:.1f} s old."))
    method = rt.capture_method or ""
    if method and method.startswith(("printwindow", "mss", "screen")):
        problems.append(("Using a slower backup capture method.", f"Capture method: {method} (Windows Graphics Capture wasn't used)."))
    if r is not None and r.confidence < 0.6:
        problems.append(("I'm only partly sure I'm reading the chart correctly.", f"Reading confidence {r.confidence:.2f}."))
    if problems:
        return _result("DEGRADED", problems[0][0], "Prices are still used. If this keeps happening, check chart settings.",
                       [d for _, d in problems])
    return _result("HEALTHY", f"Reading {p.name} normally.")


class Watchdog:
    """Keeps the newest status per chart, logs changes, alerts once per change, and restarts the reading loop if it stops."""

    def __init__(self, visual, alerts=None, data_dir: Path | None = None):
        self.visual, self.alerts = visual, alerts
        self.status: dict[str, dict] = {}
        self.events: deque = deque(maxlen=200)
        self.restarts = 0
        self.unclean_shutdown: dict | None = None
        self.marker = Path(data_dir) / "running.marker" if data_dir else None

    # ---- app-level: did the previous session end cleanly?
    def started(self) -> None:
        if not self.marker:
            return
        try:
            if self.marker.exists():
                prev = self.marker.read_text(encoding="utf-8").strip()
                self.unclean_shutdown = {"previous_start": prev or None, "found_at": datetime.now(timezone.utc).isoformat()}
                self._event(None, "app", "Study Terminal didn't close normally last time (crash, power loss or forced quit).")
            self.marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
        except OSError:
            pass

    def stopped(self) -> None:
        if self.marker:
            try:
                self.marker.unlink(missing_ok=True)
            except OSError:
                pass

    def _event(self, pid: str | None, kind: str, text: str) -> None:
        self.events.append({"at": datetime.now(timezone.utc).isoformat(), "chart": pid, "kind": kind, "text": text})

    def _loop_ok(self) -> bool:
        v = self.visual
        if v.state != "running":
            return True
        task = getattr(v, "_task", None)
        beat = getattr(v, "loop_at", None)
        return task is not None and not task.done() and (beat is None or time.monotonic() - beat < 15)

    def check(self, restart: bool = True) -> dict:
        v = self.visual
        running = v.state == "running"
        loop_ok = self._loop_ok()
        if running and not loop_ok and restart:
            import asyncio
            task = getattr(v, "_task", None)
            err = None
            if task is not None and task.done() and not task.cancelled():
                err = task.exception()
            try:
                v._task = asyncio.get_event_loop().create_task(v._loop())
                self.restarts += 1
                self._event(None, "restart", "The chart-reading loop had stopped and was restarted"
                            + (f" (it failed with {type(err).__name__})." if err else "."))
            except RuntimeError:
                pass
        out = {}
        for pid, rt in v.runtimes.items():
            tick = 0.25
            try:
                from .futures import contracts as fc
                root = rt.reading.instrument.value if rt.reading is not None and rt.reading.instrument.value else rt.profile.root
                tick = float(fc.get(root if root and root != "auto" else "MNQ").tick_size)
            except Exception:  # noqa: BLE001
                pass
            st = assess(rt, running=running, tick=tick)
            if running and not loop_ok:
                st = _result("DISCONNECTED", "The part of Study Terminal that reads your chart stopped.",
                             "It restarts by itself. If this keeps happening, quit Study Terminal and open it again.")
            st["chart"] = {"id": pid, "name": rt.profile.name}
            st["checked_at"] = datetime.now(timezone.utc).isoformat()
            prev = self.status.get(pid)
            if prev is None or prev["code"] != st["code"]:
                self._event(pid, "status", f"{rt.profile.name}: {prev['code'] if prev else 'start'} -> {st['code']}. {st['reason']}")
                if self.alerts is not None and prev is not None and st["level"] in ("bad", "attention") and st["code"] not in ("OFF",):
                    try:
                        self.alerts.emit("system", "high" if st["suspends_ideas"] else "medium", f"{rt.profile.name}: {st['word']}",
                                         f"{st['reason']} {st['do']}".strip(), key=f"watchdog|{pid}", fingerprint=st["code"] + st["reason"][:60])
                    except Exception:  # noqa: BLE001
                        pass
            out[pid] = st
        self.status = out
        return self.summary()

    def summary(self) -> dict:
        order = ["HEALTHY", "OFF", "DEGRADED", "STALE", "UNREADABLE", "REQUIRES_RECALIBRATION", "DISCONNECTED"]
        charts = list(self.status.values())
        worst = max(charts, key=lambda c: order.index(c["code"])) if charts else _result("OFF", "No chart is connected yet.",
                                                                                          "Connect your TopstepX chart.")
        return {"overall": {k: worst[k] for k in ("code", "word", "level", "suspends_ideas", "reason", "do")},
                "charts": self.status, "events": list(self.events)[-50:][::-1], "loop_restarts": self.restarts,
                "unclean_shutdown": self.unclean_shutdown}
