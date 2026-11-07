"""Study Terminal desktop app (Windows).

- Runs the backend in this process, opens a native window (WebView2 via pywebview).
- Closing the window hides it to the system tray; monitoring continues.
- Tray icon: green = monitoring live, amber = degraded/polling, gray = paused, red dot = screen capture on.
- Global hotkey Ctrl+Alt+S brings the window back.
- Optional: keep the PC awake while monitoring (setting desktop.keep_awake_while_monitoring).
Run:  .\\scripts\\run-desktop.ps1
"""
from __future__ import annotations

import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app.config import get_settings  # noqa: E402

S = get_settings()
URL = f"http://127.0.0.1:{S.port}"
API = f"{URL}/api"
IS_WIN = sys.platform == "win32"


class Backend:
    def __init__(self):
        self.server = uvicorn.Server(uvicorn.Config("app.main:app", host="127.0.0.1", port=S.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self, timeout=60):
        self.thread.start()
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if httpx.get(f"{API}/health", timeout=2).status_code == 200:
                    return True
            except httpx.HTTPError:
                time.sleep(0.4)
        return False

    def stop(self):
        self.server.should_exit = True


def keep_awake(on: bool):
    if not IS_WIN:
        return
    import ctypes

    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))


def tray_image(color: str, screen_on: bool):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 60, 60], 12, fill=(17, 20, 28, 255))
    d.ellipse([18, 18, 46, 46], fill=color)
    if screen_on:
        d.ellipse([42, 4, 60, 22], fill="#ef4444")
    return img


class App:
    def __init__(self):
        self.backend = Backend()
        self.window = None
        self.icon = None
        self.quitting = False
        self.status = {}

    def api(self, method: str, path: str, **kw):
        try:
            return httpx.request(method, f"{API}{path}", timeout=10, headers={"X-Study-Terminal": "1"}, **kw).json()
        except Exception:
            return None

    # ---------------- window ----------------
    def show(self):
        if self.window:
            self.window.show()
            self.window.restore()
        else:
            webbrowser.open(URL)

    def on_closing(self):
        if self.quitting:
            return True
        self.window.hide()
        self.notify("Study Terminal is still running", "Monitoring continues in the system tray. Ctrl+Alt+S to reopen.")
        return False  # cancel the close: hide to tray instead

    def notify(self, title, body):
        if self.icon:
            try:
                self.icon.notify(body, title)
            except Exception:
                pass

    # ---------------- tray ----------------
    def build_tray(self):
        import pystray

        def toggle_monitoring(icon, item):
            enabled = (self.status.get("market_data") or {}).get("monitoring_enabled", True)
            self.api("POST", "/monitoring/pause" if enabled else "/monitoring/resume")
            self.refresh()

        def stop_screen(icon, item):
            self.api("POST", "/screen/stop")
            self.refresh()

        def quit_app(icon, item):
            self.quitting = True
            keep_awake(False)
            self.backend.stop()
            icon.stop()
            if self.window:
                self.window.destroy()

        menu = pystray.Menu(
            pystray.MenuItem("Open Study Terminal", lambda i, it: self.show(), default=True),
            pystray.MenuItem(lambda it: "Pause monitoring" if (self.status.get("market_data") or {}).get("monitoring_enabled", True)
                             else "Resume monitoring", toggle_monitoring),
            pystray.MenuItem("Stop screen monitoring", stop_screen,
                             visible=lambda it: (self.status.get("screen") or {}).get("state") in ("running", "paused")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit (stops all monitoring)", quit_app),
        )
        self.icon = pystray.Icon("StudyTerminal", tray_image("#6b7280", False), "Study Terminal", menu)
        threading.Thread(target=self.icon.run, daemon=True).start()

    def refresh(self):
        h = self.api("GET", "/health") or {}
        scr = self.api("GET", "/screen/status") or {}
        self.status = {**h, "screen": scr}
        md = h.get("market_data") or {}
        if not md.get("monitoring_enabled", True):
            color, text = "#6b7280", "paused"
        elif md.get("stream", {}).get("state") == "connected":
            color, text = "#22c55e", "live (stream connected)"
        elif md.get("healthy"):
            color, text = "#f59e0b", "polling"
        else:
            color, text = "#ef4444", f"problem: {md.get('health_reason', 'no data')}"
        screen_on = scr.get("state") == "running"
        if self.icon:
            self.icon.icon = tray_image(color, screen_on)
            self.icon.title = f"Study Terminal - market: {text} | screen: {scr.get('state', 'off')}"[:127]
            self.icon.update_menu()
        settings = (self.api("GET", "/settings") or {}).get("values", {})
        keep_awake(bool(settings.get("desktop.keep_awake_while_monitoring")) and md.get("monitoring_enabled", True))

    def status_loop(self):
        while not self.quitting:
            self.refresh()
            time.sleep(5)

    # ---------------- hotkey ----------------
    def hotkey_loop(self):
        if not IS_WIN:
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        MOD_ALT, MOD_CONTROL, VK_S, WM_HOTKEY = 0x0001, 0x0002, 0x53, 0x0312
        if not user32.RegisterHotKey(None, 1, MOD_ALT | MOD_CONTROL, VK_S):
            return  # another app owns Ctrl+Alt+S
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY:
                self.show()

    # ---------------- run ----------------
    def run(self):
        if not self.backend.start():
            print("Backend failed to start; see logs in %LOCALAPPDATA%\\StudyTerminal\\logs")
            sys.exit(1)
        try:
            self.build_tray()
        except Exception as e:
            print(f"System tray unavailable: {e}")
        threading.Thread(target=self.status_loop, daemon=True).start()
        threading.Thread(target=self.hotkey_loop, daemon=True).start()
        try:
            import webview

            self.window = webview.create_window("Study Terminal", URL, width=1560, height=980, min_size=(1100, 700),
                                                background_color="#0b0e14")
            self.window.events.closing += self.on_closing
            webview.start(gui="edgechromium" if IS_WIN else None)
        except ImportError:
            print("pywebview not installed - opening in your browser instead. Close the console to quit.")
            webbrowser.open(URL)
            while not self.quitting:
                time.sleep(1)
        # window loop ended via Quit
        self.quitting = True
        self.backend.stop()


if __name__ == "__main__":
    App().run()
