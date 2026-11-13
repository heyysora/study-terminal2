"""Visual Market Monitor: continuously reads the TopstepX chart(s) on your screen and turns them into recommendations and alerts.

Runs in the backend, so it keeps working when the page is closed (and while the desktop app is in the tray). Authorized screen
capture only (the same PrintWindow/mss capture as the screen copilot); frames stay in memory and are never written to disk.

Per chart profile, every capture is classified:
  LIVE VISUAL OBSERVATION  fresh, readable screen capture (source: SCREEN CAPTURE; values are DIRECTLY_READ,
                           CALCULATED_FROM_CALIBRATION, VISUALLY_ESTIMATED or UNAVAILABLE). A changed screenshot is not a market tick.
  STALE            no good reading for `stale_seconds`, or the chart hasn't changed for `frozen_seconds` during the session (frozen)
  UNREADABLE       capture worked but the chart couldn't be read reliably (blank, obscured, low confidence, layout changed)
  DISCONNECTED     the chart window is gone or minimized
Only LIVE VISUAL OBSERVATION can produce a recommendation other than NO TRADE. Screen data is never called an exchange feed.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from ..futures import contracts as fc
from ..futures.sessions import FuturesClock
from . import capture as cap
from .capture_sources import CaptureManager
from .chart_profile import ChartProfile, ProfileStore
from .chart_reader import ChartReading, read_chart
from .visual_bars import bars_from_reading, visual_frame
from .visual_recommend import build as build_rec
from .visual_recommend import expired

log = logging.getLogger(__name__)
IS_WIN = sys.platform == "win32"
TF_SEC = {"1Min": 60, "2Min": 120, "3Min": 180, "5Min": 300, "15Min": 900, "30Min": 1800, "1Hour": 3600, "4Hour": 14400, "1Day": 86400}
LABEL_TEXT = {"screen_capture": "LIVE VISUAL OBSERVATION", "stale": "STALE", "unreadable": "UNREADABLE", "disconnected": "DISCONNECTED",
              "stopped": "STOPPED", "paused": "PAUSED"}


class WinInfo:
    """Windows facts about a window. Off Windows everything reports 'unknown' (None), never a guess."""

    def exists(self, hwnd: int) -> bool | None:
        if not IS_WIN:
            return None
        import ctypes
        return bool(ctypes.windll.user32.IsWindow(hwnd))

    def minimized(self, hwnd: int) -> bool | None:
        if not IS_WIN:
            return None
        import ctypes
        return bool(ctypes.windll.user32.IsIconic(hwnd))

    def rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        if not IS_WIN:
            return None
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return r.left, r.top, r.right, r.bottom

    def obscured(self, hwnd: int, region: list[int]) -> bool | None:
        """True if another window covers part of the capture region (checked at 9 points)."""
        if not IS_WIN:
            return None
        import ctypes
        from ctypes import wintypes
        rc = self.rect(hwnd)
        if rc is None:
            return None
        x, y, w, h = region
        if not w or not h:
            w, h, x, y = rc[2] - rc[0], rc[3] - rc[1], 0, 0
        u = ctypes.windll.user32
        for fx in (0.1, 0.5, 0.9):
            for fy in (0.1, 0.5, 0.9):
                pt = wintypes.POINT(int(rc[0] + x + fx * w), int(rc[1] + y + fy * h))
                top = u.WindowFromPoint(pt)
                if top and u.GetAncestor(top, 2) != hwnd:          # GA_ROOT
                    return True
        return False


@dataclass
class Runtime:
    profile: ChartProfile
    hwnd: int | None = None
    title: str | None = None
    process: str | None = None
    status: str = "stopped"
    reason: str = "Not started."
    last_capture_at: datetime | None = None
    last_good_at: datetime | None = None
    last_change_at: datetime | None = None
    last_ocr: float = 0.0
    thumb: np.ndarray | None = None
    reading: ChartReading | None = None
    signature: dict | None = None
    pending_signature: dict | None = None
    bars: list[dict] = field(default_factory=list)
    recommendation: dict | None = None
    active: dict | None = None                 # issued LONG/SHORT being tracked for EXIT
    potential: dict | None = None              # current potential setup (for invalidation alerts)
    captures: int = 0
    readings: int = 0
    capture_method: str | None = None
    history: list[dict] = field(default_factory=list)
    next_due: float = 0.0
    health: dict = field(default_factory=dict)       # capture method used, methods tried, frame age
    last_img: np.ndarray | None = None               # newest region image, in memory only (live preview)
    tape: object | None = None                       # PriceTape: accepted live prices (see live_price.py)
    live: dict = field(default_factory=dict)         # newest accepted price {price, at, method, confidence}
    next_live: float = 0.0
    last_full: float = 0.0

    def summary(self) -> dict:
        r = self.reading
        return {"profile": self.profile.to_dict(), "status": self.status, "label": LABEL_TEXT.get(self.status, self.status.upper()),
                "reason": self.reason, "window": {"hwnd": self.hwnd, "title": self.title, "process": self.process},
                "last_capture_at": self.last_capture_at and self.last_capture_at.isoformat(),
                "last_good_at": self.last_good_at and self.last_good_at.isoformat(),
                "last_change_at": self.last_change_at and self.last_change_at.isoformat(), "captures": self.captures,
                "capture_health": self.health, "source": "SCREEN CAPTURE",
                "readings": self.readings, "capture_method": self.capture_method,
                "reading": r.to_dict(candles=120) if r else None, "recommendation": self.recommendation, "active": self.active,
                "history": self.history[-30:][::-1]}


class CaptureStats:
    """Per-day counts of what monitoring actually observed on your screen (real captures only), kept for the Trust & Validation
    dashboard. Written to <data dir>/visual_capture_stats.json at most every 30 s."""

    def __init__(self, path):
        import json
        from pathlib import Path
        self.path = Path(path) if path else None
        self.days: dict = {}
        self._dirty, self._t = False, 0.0
        if self.path and self.path.exists():
            try:
                self.days = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                self.days = {}

    def record(self, day: str, status: str, method: str | None) -> None:
        d = self.days.setdefault(day, {"attempts": 0, "window_found": 0, "live": 0, "unreadable": 0, "stale": 0, "disconnected": 0, "methods": {}})
        d["attempts"] += 1
        if status != "disconnected":
            d["window_found"] += 1
        if status == "screen_capture":
            d["live"] += 1
        elif status in ("unreadable", "stale", "disconnected"):
            d[status] += 1
        if method:
            d["methods"][method] = d["methods"].get(method, 0) + 1
        self._dirty = True
        if time.monotonic() - self._t > 30:
            self.flush()

    def flush(self) -> None:
        import json
        if not (self.path and self._dirty):
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.days), encoding="utf-8")
            self._dirty, self._t = False, time.monotonic()
        except Exception:  # noqa: BLE001
            log.exception("could not save capture statistics")


class VisualMonitor:
    def __init__(self, store: ProfileStore, futures=None, alerts=None, broadcaster=None, settings=None, *,
                 capture_fn=None, list_fn=None, win: WinInfo | None = None, now=None, ocr_fn=None):
        self.store, self.futures, self.alerts, self.broadcaster, self.settings = store, futures, alerts, broadcaster, settings
        self.capture_fn = capture_fn                 # tests inject (target) -> (frame, method)
        self.capture_manager = CaptureManager()
        sp = getattr(store, "path", None)
        self.capture_stats = CaptureStats(sp.parent / "visual_capture_stats.json" if sp is not None and capture_fn is None else None)
        self.list_fn = list_fn or cap.list_targets
        self.win = win or WinInfo()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.ocr_fn = ocr_fn
        self.state = "stopped"
        self.runtimes: dict[str, Runtime] = {}
        self._task: asyncio.Task | None = None
        self._alerted: dict[str, str] = {}           # alert key -> fingerprint of the last alert sent (one alert per change)
        self.alert_log: list[dict] = []

    # ---------------- control ----------------

    def _sync_profiles(self) -> None:
        profiles = {p.id: p for p in self.store.all() if p.active}
        for pid in list(self.runtimes):
            if pid not in profiles:
                del self.runtimes[pid]
        for pid, p in profiles.items():
            if pid in self.runtimes:
                self.runtimes[pid].profile = p
            else:
                self.runtimes[pid] = Runtime(profile=p, hwnd=p.window_hwnd, tape=self._tape(pid))

    def _tape(self, pid: str):
        from .live_price import PriceTape
        sp = getattr(self.store, "path", None)
        # only real screen captures are saved; injected test/demo sources stay in memory
        folder = sp.parent / "live_prices" if sp is not None and self.capture_fn is None else None
        try:
            return PriceTape(pid, folder)
        except OSError:
            log.exception("couldn't open the live price folder")
            return PriceTape(pid, None)

    async def start(self) -> dict:
        self._sync_profiles()
        if not self.runtimes:
            raise ValueError("Save at least one active chart profile first (Visual Market Monitor > Set up a chart).")
        self.state = "running"
        for rt in self.runtimes.values():
            rt.status, rt.reason, rt.next_due = "stale", "Starting…", 0.0
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
        self._save_state()
        self._push()
        return self.status()

    def pause(self) -> dict:
        if self.state == "running":
            self.state = "paused"
            for rt in self.runtimes.values():
                rt.status, rt.reason = "paused", "Monitoring paused by you. Nothing is captured."
            self._save_state()
            self._push()
        return self.status()

    async def resume(self) -> dict:
        if self.state == "paused":
            return await self.start()
        return self.status()

    async def stop(self) -> dict:
        self.state = "stopped"
        if self._task:
            self._task.cancel()
            self._task = None
        for rt in self.runtimes.values():
            rt.status, rt.reason, rt.recommendation, rt.last_img = "stopped", "Monitoring stopped. Nothing is captured.", None, None
        self.capture_manager.release()               # end Windows Graphics Capture sessions (removes the capture border)
        self.capture_stats.flush()
        for rt in self.runtimes.values():
            if rt.tape is not None:
                rt.tape.gap(time.time())
                rt.tape.flush()
        self._save_state()
        self._push()
        return self.status()

    def _save_state(self) -> None:
        if self.settings is not None:
            try:
                self.settings.update({"visual.last_state": self.state})
            except Exception:  # noqa: BLE001
                pass

    async def autostart(self) -> None:
        if self.settings is not None and self.settings.get("visual.last_state", "stopped") == "running":
            try:
                await self.start()
            except ValueError:
                pass

    def status(self) -> dict:
        return {"state": self.state, "charts": {pid: rt.summary() for pid, rt in self.runtimes.items()},
                "alerts": self.alert_log[-30:][::-1],
                "note": "Screen-captured chart data: visual observations with capture times, not a verified exchange feed. "
                        "Analysis only: Study Terminal never clicks, types into or sends orders to TopstepX."}

    def _push(self) -> None:
        if self.broadcaster:
            self.broadcaster.publish({"type": "visual", "data": {"state": self.state, "charts": {
                pid: {k: v for k, v in rt.summary().items() if k not in ("reading", "history")} for pid, rt in self.runtimes.items()}}})

    # ---------------- loop ----------------

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            if self.state != "running":
                continue
            for rt in list(self.runtimes.values()):
                mono = time.monotonic()
                full = mono >= rt.next_due
                fast = not full and mono >= rt.next_live and rt.status == "screen_capture"
                if not (full or fast):
                    continue
                rt.next_live = mono + float(rt.profile.live_seconds)
                if full:
                    rt.next_due = mono + float(rt.profile.capture_seconds)
                try:
                    await self.tick(rt, fast=fast)
                except Exception as e:  # noqa: BLE001
                    log.exception("visual monitor tick failed")
                    self._set(rt, "unreadable", f"Internal error while reading the chart ({type(e).__name__}).")

    def _set(self, rt: Runtime, status: str, reason: str) -> None:
        changed = status != rt.status
        rt.status, rt.reason = status, reason
        if status != "screen_capture" and rt.tape is not None:
            rt.tape.gap(time.time())                      # the live line breaks instead of bridging a period we couldn't see
            if changed and self.broadcaster:
                self.broadcaster.publish({"type": "visual_price", "data": {"profile": rt.profile.id, "t": time.time(), "price": None,
                                                                          "method": "gap", "status": status}})
        if status != "screen_capture" and changed:
            kind = {"disconnected": "chart_missing", "stale": "chart_stale", "unreadable": "low_confidence"}.get(status)
            if kind:
                self._alert(rt, kind, "medium", f"{rt.profile.name}: {LABEL_TEXT[status]}", reason, fingerprint=status + reason[:40])
        if status == "screen_capture":
            for k in ("chart_missing", "chart_stale", "low_confidence", "calibration_invalid"):
                self._alerted.pop(f"{rt.profile.id}:{k}", None)

    def _resolve_window(self, rt: Runtime) -> bool:
        p = rt.profile
        if rt.hwnd and self.win.exists(rt.hwnd) is not False:
            title = cap.window_title(rt.hwnd) if IS_WIN else rt.title
            if title is None and IS_WIN:
                rt.hwnd = None
            elif title is not None and not p.matches(title, rt.process) and IS_WIN:
                rt.hwnd = None
            else:
                rt.title = title or rt.title
                return True
        for t in self.list_fn():
            if t.get("kind") == "window" and p.matches(t.get("title"), t.get("process")):
                rt.hwnd, rt.title, rt.process = int(t["id"]), t.get("title"), t.get("process")
                return True
        return False

    async def tick(self, rt: Runtime, fast: bool = False) -> None:
        now = self._now()
        p = rt.profile
        clock = FuturesClock(fc.get(p.root if p.root != "auto" else "MNQ"))
        session_open = clock.window_at(now) is not None
        if not self._resolve_window(rt):
            self._set(rt, "disconnected", f"No open window matches '{p.window_title_contains}'"
                                          f"{' in ' + p.window_process if p.window_process else ''}. Open TopstepX in Microsoft Edge "
                                          "(or re-select the window). Monitoring has stopped producing observations.")
            return self._after(rt, now, None)
        from .vision import is_browser, title_looks_like_trading
        if is_browser(rt.process) and not title_looks_like_trading(rt.title or "", rt.process):
            self._set(rt, "unreadable", "The browser window isn't showing the chart (another tab is open). Privacy: nothing is captured "
                                        "until you switch back to the TopstepX tab.")
            return self._after(rt, now, None)
        if self.win.minimized(rt.hwnd):
            self._set(rt, "disconnected", "The TopstepX window is minimized; minimized windows can't be captured.")
            return self._after(rt, now, None)
        if self.capture_fn is not None:
            frame, method = await asyncio.to_thread(self.capture_fn, cap.Target("window", rt.hwnd, rt.title or "", rt.process))
            tried, age = [{"method": method, "error": None if frame is not None else method}], None
        else:
            res = await asyncio.to_thread(self.capture_manager.capture, rt.hwnd, p.capture_method,
                                          lambda h: bool(self.win.obscured(h, p.region)))
            frame, method, tried, age = res.frame, res.method, res.tried, res.frame_age
        rt.last_capture_at = now
        rt.captures += 1
        rt.capture_method = method
        rt.health = {"method": method, "requested": p.capture_method, "tried": tried, "frame_age_seconds": None if age is None else round(age, 2),
                     "at": now.isoformat()}
        if frame is None:
            why = "; ".join(f"{t['method']}: {t['error']}" for t in tried if t.get("error")) or method
            self._set(rt, "unreadable", f"Capture failed ({why}).")
            return self._after(rt, now, None)
        if method and method.startswith("mss") and self.win.obscured(rt.hwnd, p.region):
            self._set(rt, "unreadable", "Another window covers the chart, and this window can only be captured while visible.")
            return self._after(rt, now, None)
        fh, fw = frame.shape[:2]
        if p.window_size and (abs(fw - p.window_size[0]) > 0.02 * p.window_size[0] or abs(fh - p.window_size[1]) > 0.02 * p.window_size[1]):
            self._set(rt, "unreadable", f"Layout changed: the window is {fw}x{fh} now, {p.window_size[0]}x{p.window_size[1]} when the "
                                        "region was set. Re-select the region (Visual Market Monitor > Set up a chart).")
            return self._after(rt, now, None)
        x, y, w, h = p.region
        img = frame[y:y + h, x:x + w] if w and h else frame
        if img.size == 0 or img.shape[0] < 50 or img.shape[1] < 50:
            self._set(rt, "unreadable", "The capture region is outside the window or too small.")
            return self._after(rt, now, None)
        rt.last_img = img
        import cv2
        # change detection at full resolution: a quiet market may move only the last candle by a pixel or two
        thumb = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        changed = rt.thumb is None or rt.thumb.shape != thumb.shape or int((cv2.absdiff(thumb, rt.thumb) > 25).sum()) >= 3
        if changed:
            rt.last_change_at = now
        rt.thumb = thumb
        if rt.last_change_at and session_open and (now - rt.last_change_at).total_seconds() > p.frozen_seconds:
            self._set(rt, "stale", f"Chart frozen: nothing on it has changed for {int((now - rt.last_change_at).total_seconds())} s "
                                   "while the market is open (disconnected platform, paused chart, or replay mode).")
            return self._after(rt, now, rt.reading)
        if fast and await self._fast_price(rt, img, now, changed):
            return
        if not changed and rt.reading is not None and time.monotonic() - rt.last_ocr < 30 and rt.status == "screen_capture":
            rt.last_good_at = now                         # same picture as the last good reading: still valid
            return self._after(rt, now, rt.reading, fresh=False)
        rt.last_ocr = time.monotonic()
        kw = {"tokens": self.ocr_fn(img)} if self.ocr_fn else {}
        reading = await asyncio.to_thread(read_chart, img, p, now, title=rt.title or "", **kw)
        rt.readings += 1
        rt.reading = reading
        if not reading.ok:
            if not reading.calibration_valid:
                self._alert(rt, "calibration_invalid", "medium", f"{p.name}: recalibrate", reading.problems[-1], fingerprint="calibration")
            self._set(rt, "unreadable", "; ".join(reading.problems) or "Chart not readable.")
            return self._after(rt, now, reading)
        # layout change: axis or header moved compared with the last good reading -> wait for it to be stable twice
        sig = reading.signature
        if rt.signature and (abs(sig["axis_left"] - rt.signature["axis_left"]) > 15 or abs(sig["header_h"] - rt.signature["header_h"]) > 15):
            if rt.pending_signature != sig:
                rt.pending_signature = sig
                self._set(rt, "unreadable", "Chart layout changed (price axis or header moved). Checking the new layout before using it.")
                return self._after(rt, now, reading)
        rt.signature, rt.pending_signature = sig, None
        if reading.confidence < 0.4:
            self._set(rt, "unreadable", f"Recognition confidence fell to {reading.confidence:.2f}: " + "; ".join(reading.problems[:2]))
            return self._after(rt, now, reading)
        rt.last_good_at = now
        rt.last_full = time.monotonic()
        self._set(rt, "screen_capture", "Reading the chart on your screen (visual observation, capture time shown).")
        if reading.price.value is not None and reading.price.confidence >= 0.6:
            self._record_price(rt, now, float(reading.price.value), "full read", reading.price.confidence)
        self._after(rt, now, reading)

    # ---------------- live price ----------------

    def _tick_size(self, rt: Runtime) -> float:
        root = rt.reading.instrument.value if rt.reading is not None and rt.reading.instrument.value else rt.profile.root
        try:
            return float(fc.get(root if root and root != "auto" else "MNQ").tick_size)
        except Exception:  # noqa: BLE001
            return 0.25

    def _record_price(self, rt: Runtime, now: datetime, price: float, method: str, confidence: float) -> bool:
        if rt.tape is None:
            return False
        ok = rt.tape.offer(now.timestamp(), price, self._tick_size(rt), method)
        if ok:
            rt.live = {"price": price, "at": now.isoformat(), "method": method, "confidence": round(float(confidence), 3)}
            if self.broadcaster:
                self.broadcaster.publish({"type": "visual_price", "data": {"profile": rt.profile.id, "t": now.timestamp(), "price": price,
                                                                          "method": method, "status": rt.status}})
        return ok

    async def _fast_price(self, rt: Runtime, img, now: datetime, changed: bool) -> bool:
        """Read only the price box. True when a price was accepted (the full read can wait); False = do a full read."""
        from .live_price import read_tag
        r = rt.reading
        if rt.status != "screen_capture" or r is None or not r.ok or not r.axis or rt.tape is None:
            return False
        if time.monotonic() - rt.last_full > max(10.0, 3 * float(rt.profile.capture_seconds)):
            return False                                  # re-anchor the price scale with a full read regularly
        if not changed:
            rt.last_good_at = now                         # same picture: the last price still stands
            return True
        last = rt.tape.last()
        if self.ocr_fn is not None:                       # tests inject OCR: use the full path
            return False
        tr = await asyncio.to_thread(read_tag, img, r.axis, self._tick_size(rt), last[1] if last else None)
        if tr.value is None:
            rt.tape.reject(tr.why)
            return False
        if not self._record_price(rt, now, tr.value, "price box", tr.confidence):
            return False                                  # an unconfirmed jump: let a full read decide
        rt.last_good_at = now
        return True

    # ---------------- analysis + alerts ----------------

    def _after(self, rt: Runtime, now: datetime, reading: ChartReading | None, fresh: bool = True) -> None:
        p = rt.profile
        if rt.status in ("screen_capture", "unreadable") and rt.last_good_at and (now - rt.last_good_at).total_seconds() > p.stale_seconds:
            self._set(rt, "stale", f"No reliable observation for {int((now - rt.last_good_at).total_seconds())} s"
                                   + ("" if rt.status == "screen_capture" else f" ({rt.reason})") + ". Monitoring isn't producing reliable observations.")
        if self.state == "running" and self.capture_fn is None:      # only real screen captures count as evidence
            self.capture_stats.record(now.date().isoformat(), rt.status, rt.capture_method if rt.status != "disconnected" else None)
        rec = self._recommend(rt, now, reading)
        rt.recommendation = rec
        self._alerts_for(rt, rec, now)
        entry = {"at": now.isoformat(), "status": rt.status, "action": rec["action"], "reason": rec["reason"][:160],
                 "price": rec.get("observed_price"), "confidence": rec.get("data_confidence")}
        last = rt.history[-1] if rt.history else None
        if last and all(last[k] == entry[k] for k in ("status", "action", "reason", "price")):
            last["repeats"] = last.get("repeats", 0) + 1          # same result again: one line, not hundreds
            last.setdefault("since", last["at"])
            last["at"] = entry["at"]
        else:
            rt.history.append(entry)
        rt.history = rt.history[-300:]
        self._push()

    def _recommend(self, rt: Runtime, now: datetime, reading: ChartReading | None) -> dict:
        p = rt.profile
        if expired(rt.active, now):
            rt.active = None
        notes: list[str] = []
        F = F_htf = None
        if rt.status == "screen_capture" and reading is not None and reading.ok and reading.timeframe.value in TF_SEC \
                and reading.instrument.value in ("NQ", "MNQ", "ES", "MES"):
            spec = fc.get(reading.instrument.value)
            clock = FuturesClock(spec)
            tfs = TF_SEC[reading.timeframe.value]
            bars, n1 = bars_from_reading(reading, tfs, clock)
            notes += n1
            rt.bars = bars
            vw = reading.indicators.get("VWAP", {})
            screen_vwap = vw.get("values") if isinstance(vw, dict) and vw.get("values") else None
            F, n2 = visual_frame(bars, spec, clock, tfs, screen_vwap=screen_vwap, has_volume=reading.volume.value is not None)
            notes += n2
            F_htf = self._htf_frame(rt, reading.instrument.value)
        if self.futures is None:
            from .visual_recommend import no_trade
            return no_trade("Futures analysis isn't available.", reading=reading)
        rec = build_rec(reading, F, F_htf, status=rt.status, status_reason=rt.reason, profile=p, futures=self.futures, now=now,
                        prev_active=rt.active, notes=notes)
        if rec["action"] in ("LONG", "SHORT") and not (rt.active and rt.active.get("decision_id") == rec.get("decision_id")):
            rt.active = {k: rec.get(k) for k in ("contract", "direction", "entry", "stop", "target_1", "target_2", "setup", "decision_id")}
            rt.active["issued_at"] = now.isoformat()
        elif rec["action"] == "EXIT":
            rt.active = None
        return rec

    def _htf_frame(self, rt: Runtime, root: str):
        """15-minute structure from another monitored chart of the same product, if you have one set up."""
        for other in self.runtimes.values():
            if other is rt or other.status != "screen_capture" or not other.reading:
                continue
            if other.reading.instrument.value == root and other.reading.timeframe.value == "15Min" and other.bars:
                spec = fc.get(root)
                F, _ = visual_frame(other.bars, spec, FuturesClock(spec), 900)
                return F
        return None

    def _alert(self, rt: Runtime, kind: str, severity: str, title: str, body: str, fingerprint: str) -> bool:
        key = f"{rt.profile.id}:{kind}"
        if self._alerted.get(key) == fingerprint:
            return False                               # same alert already sent for this state
        self._alerted[key] = fingerprint
        entry = {"at": self._now().isoformat(), "chart": rt.profile.name, "kind": kind, "title": title, "body": body}
        self.alert_log = (self.alert_log + [entry])[-200:]
        if self.alerts is not None:
            cat = "entry" if kind in ("potential", "entry", "invalid", "exit") else "system"
            self.alerts.emit(cat, severity, title, body, key=f"visual:{key}", fingerprint=fingerprint,
                             symbol=(rt.recommendation or {}).get("contract"))
        return True

    def _alerts_for(self, rt: Runtime, rec: dict, now: datetime) -> None:
        name = rt.profile.name
        conf = f" Data confidence {rec.get('data_confidence')}, captured {str(rec.get('captured_at'))[11:19]} UTC (screen capture)."
        if rec.get("potential"):
            fp_ = f"{rec.get('setup')}|{rec.get('direction')}|{rec.get('entry')}"
            self._alert(rt, "potential", "medium", f"Potential {rec['potential']} setup: {rec.get('contract')} ({name})",
                        f"{rec.get('setup')}: entry {rec.get('entry')}, stop {rec.get('stop')}, T1 {rec.get('target_1')}, T2 {rec.get('target_2')}. "
                        f"Not a validated strategy." + conf, fp_)
            rt.potential = {k: rec.get(k) for k in ("setup", "direction", "entry", "stop")}
        elif rt.potential and (rec.get("invalidated") or rec["action"] in ("NO TRADE", "WAIT")):
            pot = rt.potential
            cur = rec.get("observed_price")
            d = 1 if pot["direction"] == "long" else -1
            if rec.get("invalidated") or (cur is not None and pot.get("stop") is not None and (cur - pot["stop"]) * d <= 0):
                self._alert(rt, "invalid", "medium", f"Setup invalid: {pot['setup']} {pot['direction']} ({name})",
                            (rec.get("reason") or "") + conf, f"{pot['setup']}|{pot['entry']}|invalid")
                rt.potential = None
        if rec["action"] in ("LONG", "SHORT"):
            self._alert(rt, "entry", "high", f"{rec['action']} {rec.get('contract')}: entry confirmation ({name})",
                        f"{rec.get('setup')}: entry {rec.get('entry')}, stop {rec.get('stop')}, T1 {rec.get('target_1')}, T2 {rec.get('target_2')}, "
                        f"{rec.get('reward_risk')}R. Passed the risk engine." + conf, rec.get("decision_id") or "")
        if rec["action"] == "EXIT":
            self._alert(rt, "exit", "high", f"EXIT {rec.get('contract')}: {rec.get('exit_kind')} reached ({name})",
                        rec["reason"] + conf, f"{rec.get('exit_kind')}|{(rec.get('active') or {}).get('decision_id')}")

    # ---------------- one-off reads (setup page) ----------------

    async def read_once(self, profile: ChartProfile, frame: np.ndarray, title: str = "") -> dict:
        x, y, w, h = profile.region
        img = frame[y:y + h, x:x + w] if w and h else frame
        if img.size == 0:
            raise ValueError("The region is outside the captured window.")
        kw = {"tokens": self.ocr_fn(img)} if self.ocr_fn else {}
        r = await asyncio.to_thread(read_chart, img, profile, self._now(), title=title, **kw)
        return r.to_dict(candles=200)
