"""Reliability watchdog: each failure kind is detected, ideas are suspended where they must be, and the reading loop self-heals.
Uses SYNTHETIC screenshots and fake windows; this checks the logic, not behaviour on a real TopstepX chart."""
import asyncio
import time
from datetime import UTC, datetime

from app.screen.chart_profile import ChartProfile
from app.screen.live_price import PriceTape
from app.screen.visual_monitor import VisualMonitor
from app.watchdog import Watchdog, assess

from .test_visual_monitor import FakeWin
from .visual_chart import render, walk


class Store:
    def __init__(self, path=None, **kw):
        self.path = (path / "visual_profiles.json") if path else None
        self.p = ChartProfile.from_dict({"id": "p1", "name": "MNQ 5m", "window_title_contains": "TopstepX", "root": "MNQ",
                                         "timeframe": "5Min", **kw})

    def all(self):
        return [self.p]


class Alerts:
    def __init__(self):
        self.sent = []

    def emit(self, cat, sev, title, body, key=None, fingerprint=None, **kw):
        self.sent.append((sev, title, body))


def monitor(frames, win=None, windows=None, **kw):
    win = win or FakeWin()
    windows = windows if windows is not None else [{"kind": "window", "id": 7, "title": "TopstepX - Microsoft Edge", "process": "msedge.exe"}]
    m = VisualMonitor(Store(**kw), None, None, None, None, capture_fn=lambda t: (frames["img"], frames.get("method", "wgc")),
                      list_fn=lambda: windows, win=win, now=lambda: datetime.now(UTC))
    m._sync_profiles()
    m.state = "running"
    return m, m.runtimes["p1"], win


async def test_healthy_then_each_failure_is_detected():
    frames = {"img": render(walk(70, start=25000.0, seed=5))[0]}
    m, rt, win = monitor(frames)
    await m.tick(rt)
    assert assess(rt, running=True)["code"] == "HEALTHY"
    win.min = True                                                    # minimized
    await m.tick(rt)
    st = assess(rt, running=True)
    assert st["code"] == "DISCONNECTED" and st["suspends_ideas"] and "minimized" in st["reason"]
    win.min = False
    await m.tick(rt)
    assert assess(rt, running=True)["code"] == "HEALTHY"              # recovers by itself
    m._set(rt, "stale", "Chart frozen: nothing on it has changed for 95 s")
    assert assess(rt, running=True)["code"] == "STALE"
    m._set(rt, "unreadable", "Another window covers the chart, and this window can only be captured while visible.")
    st = assess(rt, running=True)
    assert st["code"] == "UNREADABLE" and st["reason"] == "Another window is covering your chart."
    assert assess(rt, running=False)["code"] == "OFF"


async def test_tab_switch_is_unreadable_and_nothing_is_captured():
    frames = {"img": render(walk(70, start=25000.0, seed=5))[0]}
    windows = [{"kind": "window", "id": 7, "title": "Gmail - Microsoft Edge", "process": "msedge.exe"}]
    m, rt, _ = monitor(frames, windows=windows)
    rt.hwnd, rt.title, rt.process = 7, "Gmail - Microsoft Edge", "msedge.exe"
    m.store.p.window_title_contains = ""                              # matches any title, so the privacy guard is what stops it
    await m.tick(rt)
    st = assess(rt, running=True)
    assert rt.status == "unreadable" and st["code"] == "UNREADABLE" and "different tab" in st["reason"]
    assert rt.captures == 0                                           # privacy: no capture of the other tab


async def test_wrong_market_or_timeframe_requires_recalibration_and_blocks_ideas():
    frames = {"img": render(walk(70, start=6000.0, seed=3), symbol="ESZ6")[0]}
    m, rt, _ = monitor(frames)                                        # profile says MNQ, chart shows ES
    await m.tick(rt)
    st = assess(rt, running=True)
    assert st["code"] == "REQUIRES_RECALIBRATION" and "ES" in st["reason"] and st["suspends_ideas"]
    from app.screen import visual_recommend as vr
    assert vr.quality_gates(rt.reading, "screen_capture", "", rt.profile).startswith("Chart doesn't match its setup")
    frames2 = {"img": render(walk(70, start=25000.0, seed=5), tf_text="15m")[0]}
    m2, rt2, _ = monitor(frames2)
    await m2.tick(rt2)
    assert assess(rt2, running=True)["code"] == "REQUIRES_RECALIBRATION" and "timeframe" in assess(rt2, running=True)["reason"]


def test_degraded_signals():
    class RT:
        profile = ChartProfile.from_dict({"name": "x", "root": "MNQ", "timeframe": "5Min"})
        status, reason, reading, capture_method, health = "screen_capture", "", None, "wgc", {}
        tape = PriceTape("x")
    rt = RT()
    assert assess(rt, running=True)["code"] == "HEALTHY"
    for _ in range(30):
        rt.tape.reject("no price box found on the price scale")
    st = assess(rt, running=True)
    assert st["code"] == "DEGRADED" and not st["suspends_ideas"] and "no price box" in st["details"][0]
    rt.tape = PriceTape("x")
    for _ in range(12):
        rt.tape.note_ok(1.0)                                          # the box sits 4 ticks from where the scale puts it
    assert "drifting" in assess(rt, running=True, tick=0.25)["reason"]
    rt.tape = PriceTape("x")
    rt.health = {"frame_age_seconds": 5.2}
    assert "behind" in assess(rt, running=True)["reason"]
    rt.health, rt.capture_method = {}, "printwindow"
    assert "backup capture" in assess(rt, running=True)["reason"]


async def test_watchdog_alerts_once_per_change_and_restarts_a_dead_loop():
    frames = {"img": render(walk(70, start=25000.0, seed=5))[0]}
    m, rt, win = monitor(frames)
    alerts = Alerts()
    wd = Watchdog(m, alerts)
    await m.tick(rt)
    m._task = asyncio.get_event_loop().create_task(asyncio.sleep(0))   # a loop that has already ended
    await asyncio.sleep(0.01)
    m.loop_at = time.monotonic()
    s = wd.check()
    assert wd.restarts == 1 and any(e["kind"] == "restart" for e in s["events"])
    assert not m._task.done()
    m._task.cancel()
    m._task = asyncio.get_event_loop().create_task(asyncio.sleep(3600))
    m.loop_at = time.monotonic()
    wd.check()
    win.min = True
    await m.tick(rt)
    wd.check()
    wd.check()
    assert len([a for a in alerts.sent if "Can't find the chart" in a[1]]) == 1          # one alert, not one per check
    assert wd.summary()["overall"]["code"] == "DISCONNECTED"
    m._task.cancel()


def test_unclean_shutdown_is_reported_once(tmp_path):
    class V:
        state, runtimes = "stopped", {}
    wd = Watchdog(V(), None, tmp_path)
    wd.started()
    assert wd.unclean_shutdown is None
    # the app is killed here: stopped() never runs
    wd2 = Watchdog(V(), None, tmp_path)
    wd2.started()
    assert wd2.unclean_shutdown and any("didn't close normally" in e["text"] for e in wd2.events)
    wd2.stopped()
    wd3 = Watchdog(V(), None, tmp_path)
    wd3.started()
    assert wd3.unclean_shutdown is None
