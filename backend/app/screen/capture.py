"""Window/monitor enumeration and capture.

Windows: window list via EnumWindows; capture via PrintWindow(PW_RENDERFULLCONTENT), which grabs
the chosen window even when other windows overlap it (works for Chrome/Edge/most apps on
Windows 8.1+). If that returns a blank image (some GPU-rendered apps), it falls back to grabbing
the window's screen rectangle with `mss`, which needs the window visible.
Elsewhere: only image-file input (for testing and for analyzing a saved screenshot).
Frames live in memory only and are never written to disk.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np

IS_WIN = sys.platform == "win32"


@dataclass
class Target:
    kind: str           # "window" | "monitor"
    id: int             # hwnd or monitor index
    title: str
    process: str | None = None


def list_targets() -> list[dict]:
    out: list[dict] = []
    try:
        import mss

        with mss.mss() as m:
            for i, mon in enumerate(m.monitors[1:], start=1):
                out.append({"kind": "monitor", "id": i, "title": f"Screen {i} ({mon['width']}x{mon['height']})", "process": None})
    except Exception:
        pass
    if IS_WIN:
        out += _win_windows()
    return out


def _win_windows() -> list[dict]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    res = []
    proc_cb = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def name_of(hwnd) -> str | None:
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(520)
            size = wintypes.DWORD(520)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value.rsplit("\\", 1)[-1]
        finally:
            kernel32.CloseHandle(h)
        return None

    def cb(hwnd, _lp):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                res.append({"kind": "window", "id": int(hwnd), "title": buf.value, "process": name_of(hwnd)})
        return True

    user32.EnumWindows(proc_cb(cb), 0)
    return res


def window_title(hwnd: int) -> str | None:
    if not IS_WIN:
        return None
    import ctypes

    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd):
        return None
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def capture(target: Target) -> tuple[np.ndarray | None, str]:
    """Returns (BGR image, method) or (None, reason)."""
    if target.kind == "monitor":
        try:
            import mss

            with mss.mss() as m:
                shot = m.grab(m.monitors[target.id])
                return np.asarray(shot)[:, :, :3].copy(), "mss-monitor"
        except Exception as e:
            return None, f"screen capture failed: {e}"
    if not IS_WIN:
        return None, "window capture is only available on Windows"
    img = _print_window(target.id)
    if img is not None and img.mean() > 3:
        return img, "printwindow"
    try:
        import ctypes
        from ctypes import wintypes

        import mss

        r = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(target.id, ctypes.byref(r))
        with mss.mss() as m:
            shot = m.grab({"left": r.left, "top": r.top, "width": r.right - r.left, "height": r.bottom - r.top})
            return np.asarray(shot)[:, :, :3].copy(), "mss-region (window must be visible)"
    except Exception as e:
        return None, f"window capture failed: {e}"


def _print_window(hwnd: int) -> np.ndarray | None:
    import ctypes
    from ctypes import wintypes

    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass
    r = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return None
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    hdc = user32.GetWindowDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(mdc, bmp)
    try:
        user32.PrintWindow(hwnd, mdc, 2)  # PW_RENDERFULLCONTENT
        bih = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bih), 0):
            return None
        return np.frombuffer(buf, np.uint8).reshape(h, w, 4)[:, :, :3].copy()
    finally:
        gdi32.SelectObject(mdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(mdc)
        user32.ReleaseDC(hwnd, hdc)


def frame_change(a: np.ndarray | None, b: np.ndarray | None) -> float:
    """0..255 mean absolute difference of small grayscale thumbnails (cheap change detector)."""
    if a is None or b is None or a.shape != b.shape:
        return 255.0
    import cv2

    ta = cv2.resize(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY), (96, 54), interpolation=cv2.INTER_AREA)
    tb = cv2.resize(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), (96, 54), interpolation=cv2.INTER_AREA)
    return float(np.abs(ta.astype(np.int16) - tb.astype(np.int16)).mean())
