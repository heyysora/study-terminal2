"""Capture sources for the Visual Market Monitor, in order of preference for GPU-rendered Microsoft Edge windows:

  wgc          Windows Graphics Capture (Windows 10 1903+), via the free `windows-capture` package. Reads the window's own rendered
               content, including GPU-accelerated Edge pages, even when other windows overlap it. Not for minimized windows.
               WGC delivers a new frame only when the window's content changes, so an unchanged frame is still current.
  printwindow  PrintWindow(PW_RENDERFULLCONTENT): works for many windows but can return blank or partial images for GPU content.
  screen       The window's rectangle grabbed from the screen with `mss`: always matches what's displayed, but only if the window
               is visible and not covered (checked separately).

Every frame is checked before use: blank/black or mostly black frames (a typical failed GPU capture) are rejected and the next source
is tried. The source that worked is reported with each capture. Frames stay in memory only. Nothing here reads browser data,
cookies, storage, DevTools or network traffic: it only captures pixels that are displayed.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from . import capture as cap

log = logging.getLogger(__name__)
IS_WIN = sys.platform == "win32"
METHODS = ("auto", "wgc", "printwindow", "screen")


def frame_problem(img: np.ndarray | None) -> str | None:
    """Why a captured frame can't be used, or None if it looks like real window content."""
    if img is None or img.size == 0:
        return "no image"
    if img.shape[0] < 50 or img.shape[1] < 50:
        return "image too small"
    g = img.mean(axis=2)
    if float(g.std()) < 2.0:
        return "blank (one flat color)"
    black_rows = float((g.max(axis=1) < 3).mean())
    if black_rows > 0.4:
        return f"{black_rows:.0%} of the rows are pure black (partial GPU capture)"
    return None


@dataclass
class CaptureResult:
    frame: np.ndarray | None
    method: str
    at: float = field(default_factory=time.time)
    frame_age: float | None = None             # seconds since the source last produced this frame (WGC)
    tried: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.frame is not None


class WGCSession:
    """One Windows Graphics Capture session per window, kept open; the newest frame is kept in memory."""

    def __init__(self, hwnd: int):
        self.hwnd = hwnd
        self.frame: np.ndarray | None = None
        self.frame_at = 0.0
        self.closed = False
        self.error: str | None = None
        self._lock = threading.Lock()
        self._control = None

    def start(self) -> None:
        from windows_capture import Frame, InternalCaptureControl, WindowsCapture  # noqa: F401 - Windows only
        try:
            c = WindowsCapture(cursor_capture=False, draw_border=False, window_hwnd=self.hwnd, minimum_update_interval=200)
        except Exception:  # noqa: BLE001 - some Windows versions don't allow turning the yellow border off
            c = WindowsCapture(cursor_capture=False, draw_border=None, window_hwnd=self.hwnd, minimum_update_interval=200)

        @c.event
        def on_frame_arrived(frame, capture_control):
            buf = frame.frame_buffer
            img = np.ascontiguousarray(buf[:, :, :3])           # BGRA -> BGR
            with self._lock:
                self.frame, self.frame_at = img.copy(), time.time()

        @c.event
        def on_closed():
            self.closed = True

        self._control = c.start_free_threaded()

    def latest(self) -> tuple[np.ndarray | None, float | None]:
        with self._lock:
            if self.frame is None:
                return None, None
            return self.frame.copy(), time.time() - self.frame_at

    def stop(self) -> None:
        try:
            if self._control is not None:
                self._control.stop()
        except Exception:  # noqa: BLE001
            pass


def wgc_available() -> bool:
    if not IS_WIN:
        return False
    try:
        import windows_capture  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


class CaptureManager:
    """Captures a window with the chosen method ('auto' tries wgc -> printwindow -> screen)."""

    def __init__(self, *, wgc_factory=None, printwindow=None, screen=None, obscured=None):
        self.sessions: dict[int, WGCSession] = {}
        self._wgc_factory = wgc_factory or WGCSession
        self._printwindow = printwindow or (lambda hwnd: cap._print_window(hwnd) if IS_WIN else None)
        self._screen = screen or self._screen_grab
        self._obscured = obscured
        self.wgc_ok = wgc_factory is not None or wgc_available()

    @staticmethod
    def _screen_grab(hwnd: int) -> np.ndarray | None:
        if not IS_WIN:
            return None
        import ctypes
        from ctypes import wintypes

        import mss
        r = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        with mss.mss() as m:
            shot = m.grab({"left": r.left, "top": r.top, "width": r.right - r.left, "height": r.bottom - r.top})
            return np.asarray(shot)[:, :, :3].copy()

    def _wgc(self, hwnd: int, wait: float = 1.5) -> tuple[np.ndarray | None, float | None, str | None]:
        s = self.sessions.get(hwnd)
        if s is not None and s.closed:
            s.stop()
            self.sessions.pop(hwnd, None)
            s = None
        if s is None:
            s = self._wgc_factory(hwnd)
            try:
                s.start()
            except Exception as e:  # noqa: BLE001
                return None, None, f"could not start: {type(e).__name__}: {str(e)[:120]}"
            self.sessions[hwnd] = s
            t0 = time.time()
            while time.time() - t0 < wait:                  # the first frame arrives asynchronously
                f, _ = s.latest()
                if f is not None:
                    break
                time.sleep(0.05)
        f, age = s.latest()
        return f, age, None if f is not None else "no frame yet (window minimized or not rendered?)"

    def capture(self, hwnd: int, method: str = "auto", obscured=None) -> CaptureResult:
        if method not in METHODS:
            raise ValueError(f"Unknown capture method {method}")
        order = ["wgc", "printwindow", "screen"] if method == "auto" else [method]
        tried: list[dict] = []
        for m in order:
            if m == "wgc" and not self.wgc_ok:
                tried.append({"method": m, "error": "Windows Graphics Capture isn't available (Windows only; pip package windows-capture)"})
                continue
            age = None
            if m == "wgc":
                f, age, err = self._wgc(hwnd)
            elif m == "printwindow":
                f, err = self._printwindow(hwnd), None
            else:
                f, err = self._screen(hwnd), None
                chk = obscured or self._obscured
                if f is not None and chk is not None and chk(hwnd):
                    tried.append({"method": m, "error": "window is covered by another window (screen capture shows what's on top)"})
                    continue
            prob = err or frame_problem(f)
            if prob:
                tried.append({"method": m, "error": prob})
                continue
            tried.append({"method": m, "error": None})
            return CaptureResult(f, m, frame_age=age, tried=tried)
        return CaptureResult(None, "none", tried=tried)

    def release(self, hwnd: int | None = None) -> None:
        for h in ([hwnd] if hwnd is not None else list(self.sessions)):
            s = self.sessions.pop(h, None)
            if s:
                s.stop()
