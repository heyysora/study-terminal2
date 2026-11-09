"""Edge capture source, calibration invalidation/recovery, reconnection and stale handling.
SCREENSHOT-BASED tests (synthetic recorded screenshots + fake capture backends). They are not live-market or real-Edge validation."""
from datetime import timedelta

import numpy as np
import pytest

from app.api.routes_visual import edge_first
from app.screen.capture_sources import CaptureManager, frame_problem
from app.screen.chart_profile import ChartProfile

from .test_visual_monitor import T_RTH, Clock, FakeAlerts, fixture, fut, make_monitor  # noqa: F401 - fut fixture


def real():
    return fixture("mnq_5m_basic")[0]


# ---------------- frame checks and capture chain ----------------

def test_frame_problems():
    assert frame_problem(None) == "no image"
    assert "blank" in frame_problem(np.full((400, 600, 3), 30, np.uint8))
    half = real().copy()
    half[: int(half.shape[0] * 0.6)] = 0                                             # typical partial GPU capture
    assert "pure black" in frame_problem(half)
    assert frame_problem(real()) is None


class FakeWGC:
    def __init__(self, frame):
        self._f = frame
        self.closed = False

    def __call__(self, hwnd):
        return self

    def start(self):
        pass

    def latest(self):
        return (self._f, 0.4) if self._f is not None else (None, None)

    def stop(self):
        pass


def test_auto_prefers_wgc_and_falls_back_when_blank():
    good = real()
    m = CaptureManager(wgc_factory=FakeWGC(good), printwindow=lambda h: None, screen=lambda h: None)
    r = m.capture(1)
    assert r.ok and r.method == "wgc" and r.frame_age == 0.4
    m2 = CaptureManager(wgc_factory=FakeWGC(np.zeros((500, 800, 3), np.uint8)), printwindow=lambda h: good, screen=lambda h: None)
    r2 = m2.capture(1)
    assert r2.method == "printwindow" and r2.tried[0]["method"] == "wgc" and "blank" in r2.tried[0]["error"]
    m3 = CaptureManager(wgc_factory=FakeWGC(None), printwindow=lambda h: np.zeros((500, 800, 3), np.uint8), screen=lambda h: good)
    assert m3.capture(1).method == "screen"
    # screen grab of a covered window is refused (it would show the window on top)
    r4 = m3.capture(1, obscured=lambda h: True)
    assert not r4.ok and any("covered" in (t["error"] or "") for t in r4.tried)
    # a pinned method is used alone: no silent switch to a source with different geometry
    r5 = m2.capture(1, "wgc")
    assert not r5.ok and [t["method"] for t in r5.tried] == ["wgc"]
    with pytest.raises(ValueError):
        m.capture(1, "devtools")


def test_edge_windows_listed_first():
    targets = [{"kind": "monitor", "id": 1, "title": "Screen 1", "process": None},
               {"kind": "window", "id": 2, "title": "Notepad", "process": "notepad.exe"},
               {"kind": "window", "id": 3, "title": "TopstepX - Google Chrome", "process": "chrome.exe"},
               {"kind": "window", "id": 4, "title": "News - Microsoft Edge", "process": "msedge.exe"},
               {"kind": "window", "id": 5, "title": "TopstepX and 2 more pages - Personal - Microsoft Edge", "process": "msedge.exe"}]
    w = edge_first(targets)["windows"]
    assert [x["id"] for x in w] == [5, 4, 3, 2] and w[0]["is_edge"] and w[0]["looks_like_topstepx"]
    p = ChartProfile(window_title_contains="TopstepX", window_process="msedge.exe")
    assert p.matches(targets[4]["title"], "msedge.exe") and not p.matches(targets[2]["title"], "chrome.exe")
    with pytest.raises(ValueError):
        ChartProfile(capture_method="network").validate()


# ---------------- monitor: calibration invalidation, recovery, reconnection, stale ----------------

WIN = {"kind": "window", "id": 42, "title": "TopstepX - Personal - Microsoft Edge", "process": "msedge.exe"}


async def test_zoom_invalidates_manual_calibration_until_recalibrated(fut):  # noqa: F811
    img = real()
    clock = Clock(T_RTH)
    alerts = FakeAlerts()
    m, rt, _ = make_monitor(fut, lambda t: (img, "wgc"), [WIN], clock, alerts)
    await m.tick(rt)                                                                  # automatic axis first
    a, b = rt.reading.axis["slope"], rt.reading.axis["intercept"]
    good = [[100.0, a * 100 + b], [500.0, a * 500 + b]]
    rt.profile.axis_mode, rt.profile.axis_points, rt.profile.axis_size = "manual", good, [1400, 820]
    rt.thumb = None
    clock.t += timedelta(seconds=2)
    await m.tick(rt)
    assert rt.status == "screen_capture" and rt.reading.axis["mode"] == "manual"
    # the user zooms the price scale in TopstepX: labels no longer match the calibration
    rt.profile.axis_points = [[100.0, good[0][1] + 25], [500.0, good[1][1] - 25]]
    rt.thumb = None
    clock.t += timedelta(seconds=2)
    await m.tick(rt)
    assert rt.status == "unreadable" and "Calibration invalid" in rt.reason and rt.recommendation["action"] == "NO TRADE"
    assert rt.reading.candles == [] and len([x for x in alerts.sent if "calibration_invalid" in x[0]]) == 1
    rt.thumb = None
    clock.t += timedelta(seconds=2)
    await m.tick(rt)
    assert len([x for x in alerts.sent if "calibration_invalid" in x[0]]) == 1        # not repeated
    rt.profile.axis_points = good                                                     # recalibrated
    rt.thumb = None
    clock.t += timedelta(seconds=2)
    await m.tick(rt)
    assert rt.status == "screen_capture" and rt.reading.calibration_valid


async def test_reconnection_and_recovery(fut):  # noqa: F811
    img = real()
    clock = Clock(T_RTH)
    wins = []
    m, rt, _ = make_monitor(fut, lambda t: (img, "wgc"), wins, clock)
    m.list_fn = lambda: list(wins)
    await m.tick(rt)
    assert rt.status == "disconnected" and "Microsoft Edge" in rt.reason
    wins.append(WIN)                                                                  # Edge/TopstepX opened again
    clock.t += timedelta(seconds=2)
    await m.tick(rt)
    assert rt.status == "screen_capture"
    assert rt.health["method"] == "wgc" and rt.recommendation["captured_at"] == clock.t.isoformat()


async def test_failed_captures_become_stale(fut):  # noqa: F811
    img = real()
    clock = Clock(T_RTH)
    state = {"f": img}
    m, rt, _ = make_monitor(fut, lambda t: (state["f"], "wgc" if state["f"] is not None else "every method failed"), [WIN], clock,
                            stale_seconds=10)
    await m.tick(rt)
    assert rt.status == "screen_capture"
    state["f"] = None
    clock.t += timedelta(seconds=4)
    await m.tick(rt)
    assert rt.status == "unreadable"
    clock.t += timedelta(seconds=8)
    await m.tick(rt)
    assert rt.status == "stale" and "No reliable observation" in rt.reason and rt.recommendation["action"] == "NO TRADE"
    state["f"] = img
    rt.thumb = None
    clock.t += timedelta(seconds=2)
    await m.tick(rt)
    assert rt.status == "screen_capture"


async def test_screenshot_changes_are_not_market_ticks(fut):  # noqa: F811
    """Visual bars never reach the simulator: screen data can't fill simulated orders."""
    from app.futures.paper import TRADABLE
    img = real()
    m, rt, _ = make_monitor(fut, lambda t: (img, "wgc"), [WIN], Clock(T_RTH))
    before = dict(fut.engine.last_bar_ts)
    await m.tick(rt)
    assert "screen_capture" not in TRADABLE and fut.engine.last_bar_ts == before
