"""Study Terminal desktop app (Windows).

- Runs the backend in this process, opens a native window (WebView2 via pywebview).
- Closing the window hides it to the system tray; monitoring continues.
- Tray icon: green = monitoring live, amber = degraded/polling, gray = paused, red dot = screen capture on.
- Global hotkey Ctrl+Alt+S brings the window back.
- Optional: keep the PC awake while monitoring (setting desktop.keep_awake_while_monitoring).
- One instance at a time: launching it again brings the running window to the front.
- Quit waits for the backend to finish shutting down (pending bars and paper-account state are written).
- --minimized starts straight to the tray (used by "start on login").
Run from source:  .\\scripts\\run-desktop.ps1      Installed: Start menu > Study Terminal
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from app.config import VERSION, get_settings  # noqa: E402

S = get_settings()
URL = f"http://127.0.0.1:{S.port}"
API = f"{URL}/api"
IS_WIN = sys.platform == "win32"
LOG_DIR = S.data_dir / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
log = logging.getLogger("desktop")          # desktop shell events only; the backend writes study_terminal.log
_fh = logging.FileHandler(LOG_DIR / "desktop.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_fh)
log.setLevel(logging.INFO)
log.propagate = False
HEADERS = {"X-Study-Terminal": "1"}


def message_box(title: str, text: str, error: bool = True) -> None:
    """A visible message even when there's no console (the installed app has none)."""
    log.log(logging.ERROR if error else logging.INFO, "%s: %s", title, text)
    if IS_WIN:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)
    else:
        print(f"{title}: {text}", file=sys.stderr)


def _port_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def choose_port() -> int | None:
    """If another program already uses our port, move to the next free one instead of asking you to edit a settings file.
    Must run before the backend is imported. Returns the new port, or None if the usual one is free (or nothing is)."""
    global S, URL, API
    if _port_free(S.port):
        return None
    for port in range(S.port + 1, S.port + 40):
        if _port_free(port):
            log.warning("port %s is used by another program; using %s instead", S.port, port)
            os.environ["PORT"] = str(port)
            get_settings.cache_clear()
            S = get_settings()
            URL, API = f"http://127.0.0.1:{S.port}", f"http://127.0.0.1:{S.port}/api"
            return port
    return None


def save_help_file() -> str | None:
    """Zip the logs etc. into Downloads when the app can't start, so there's something to send without hunting for folders."""
    try:
        from app.config import BUILD
        from app.datacare import make_help_file
        p = make_help_file(S.data_dir, S.secret_values(), {"version": VERSION, "build": BUILD, "startup_failed": True})
        return str(p)
    except Exception:  # noqa: BLE001
        log.exception("couldn't save a help file")
        return None


class SingleInstance:
    """Named mutex: a second launch finds the first and asks it to show its window instead of starting again."""

    def __init__(self, name: str = "Local\\StudyTerminal.SingleInstance"):
        self.handle = None
        self.already_running = False
        if IS_WIN:
            import ctypes
            self.handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
            self.already_running = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS

    def release(self):
        if self.handle:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self.handle)
            self.handle = None


class Backend:
    def __init__(self):
        from app.main import app as asgi_app   # imported here so a frozen build bundles it
        self.server = uvicorn.Server(uvicorn.Config(asgi_app, host="127.0.0.1", port=S.port, log_level="warning", log_config=None))
        self.thread = threading.Thread(target=self._serve, daemon=False, name="backend")
        self.error: str | None = None

    def _serve(self):
        try:
            self.server.run()
        except BaseException as e:  # noqa: BLE001 - surfaced to the user by run()
            self.error = f"{type(e).__name__}: {e}"
            log.exception("backend crashed")

    def start(self, timeout=90):
        self.thread.start()
        t0 = time.time()
        while time.time() - t0 < timeout:
            if not self.thread.is_alive():
                return False
            try:
                if httpx.get(f"{API}/health", timeout=2).status_code == 200:
                    return True
            except httpx.HTTPError:
                time.sleep(0.4)
        return False

    def stop(self, wait: float = 30.0) -> bool:
        """Ask the server to shut down and wait until it has (lifespan shutdown flushes the paper account and bars)."""
        self.server.should_exit = True
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(wait)
        done = not self.thread.is_alive()
        if done:
            log.info("backend stopped cleanly")
        else:
            log.warning("backend did not stop within %ss", wait)
        return done


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
    def __init__(self, minimized: bool = False):
        self.backend = Backend()
        self.window = None
        self.icon = None
        self.quitting = False
        self.status = {}
        self.minimized = minimized

    def api(self, method: str, path: str, **kw):
        try:
            return httpx.request(method, f"{API}{path}", timeout=10, headers=HEADERS, **kw).json()
        except Exception:
            return None

    def open_folder(self, which: str):
        d = LOG_DIR if which == "logs" else S.data_dir
        if IS_WIN:
            os.startfile(str(d))  # noqa: S606

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
            self.quit()

        menu = pystray.Menu(
            pystray.MenuItem("Open Study Terminal", lambda i, it: self.show(), default=True),
            pystray.MenuItem(lambda it: "Pause monitoring" if (self.status.get("market_data") or {}).get("monitoring_enabled", True)
                             else "Resume monitoring", toggle_monitoring),
            pystray.MenuItem("Stop screen monitoring", stop_screen,
                             visible=lambda it: (self.status.get("screen") or {}).get("state") in ("running", "paused")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open logs folder", lambda i, it: self.open_folder("logs")),
            pystray.MenuItem("Open data folder", lambda i, it: self.open_folder("data")),
            pystray.MenuItem(f"Version {VERSION}", None, enabled=False),
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

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        log.info("quit requested")
        keep_awake(False)
        self.backend.stop()          # waits for a clean shutdown
        if self.icon:
            self.icon.stop()
        if self.window:
            self.window.destroy()

    def restart_backend(self):
        """Restart the backend in place (used to carry out a restore, rescue or fresh start before the data is opened)."""
        log.info("restarting the backend for a data recovery action")
        self.backend.stop(30)
        self.backend = Backend()
        ok = self.backend.start()
        if not ok:
            helpf = save_help_file()
            message_box("Study Terminal", "Study Terminal couldn't restart. Close it and open it again; your request is kept and "
                        "will be done then." + (f"\n\nA help file was saved: {helpf}" if helpf else ""))
        if self.window:
            self.window.load_url(URL)

    def status_loop(self):
        n = 0
        while not self.quitting:
            if n % 2 == 0 and (self.api("GET", "/data/status") or {}).get("restart_requested"):
                self.restart_backend()
            if n % 5 == 0:
                self.refresh()
            if (self.api("GET", "/desktop/focus") or {}).get("show"):   # a second launch asked us to show up
                self.show()
            n += 1
            time.sleep(1)

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
        log.info("Study Terminal %s starting (frozen=%s, data=%s)", VERSION, getattr(sys, "frozen", False), S.data_dir)
        if not self.backend.start():
            why = self.backend.error or "it didn't answer within 90 seconds"
            helpf = save_help_file()
            message_box("Study Terminal couldn't start",
                        "Study Terminal couldn't start. Your data hasn't been changed.\n\n"
                        "Try opening it again. If it still won't start, restart your computer and try once more.\n\n"
                        + (f"A help file was saved so you can send it:\n{helpf}\n\n" if helpf else "")
                        + f"(Technical reason: {why})")
            self.backend.stop(5)
            sys.exit(1)
        try:
            self.build_tray()
        except Exception as e:
            print(f"System tray unavailable: {e}")
        threading.Thread(target=self.status_loop, daemon=True).start()
        threading.Thread(target=self.hotkey_loop, daemon=True).start()
        try:
            import webview

            self.window = webview.create_window(f"Study Terminal {VERSION}", URL, width=1560, height=980, min_size=(1100, 700),
                                                background_color="#0b0e14", hidden=self.minimized)
            self.window.events.closing += self.on_closing
            webview.start(gui="edgechromium" if IS_WIN else None)
        except ImportError:
            print("pywebview not installed - opening in your browser instead. Close the console to quit.")
            webbrowser.open(URL)
            while not self.quitting:
                time.sleep(1)
        # window loop ended via Quit
        if not self.quitting:
            self.quit()
        else:
            self.backend.stop()


def self_test() -> int:
    """Start the backend, check /api/health, shut down cleanly. Used by the installer build.
    Exit code 0 = OK, 1 = failed, 2 = started in Recovery mode (damaged data file or data folder can't be written)."""
    choose_port()
    b = Backend()
    ok = b.start(timeout=120)
    health, futures_ok, auto, auto_ok, wgc = None, False, {}, False, "not checked"
    if ok:
        try:
            health = httpx.get(f"{API}/health", timeout=5).json()
            if health.get("recovery"):
                rec = health["recovery"]
                stopped = b.stop(30)
                print(f"self-test: recovery mode ({rec.get('kind')}: {rec.get('problem')}); clean shutdown {'yes' if stopped else 'NO'}; "
                      f"version {VERSION}")
                return 2
            fut = httpx.get(f"{API}/futures/info", timeout=10).json()   # proves bundled futures presets load
            futures_ok = bool(fut.get("presets", {}).get("presets")) and bool(fut.get("products"))
            auto = httpx.get(f"{API}/futures/automation", timeout=10).json()   # monitoring loaded; live execution locked
            auto_ok = auto.get("live", {}).get("locked") is True and auto.get("status") in ("running", "stopped", "paused", "emergency_stopped")
            ok = ok and futures_ok and auto_ok
            try:
                from app.screen.capture_sources import wgc_available
                wgc = "available" if wgc_available() else "not available"
            except Exception:  # noqa: BLE001
                wgc = "not available"
        except (httpx.HTTPError, ValueError):
            ok, futures_ok, auto, auto_ok = False, False, {}, False
    stopped = b.stop(30)
    print(f"self-test: backend {'up' if ok else 'FAILED'}; clean shutdown {'yes' if stopped else 'NO'}; "
          f"version {VERSION}; brokerage_required={None if not health else health.get('brokerage_required')}; "
          f"futures presets {'loaded' if futures_ok else 'MISSING'}; automation {auto.get('status') if auto_ok else 'FAILED'} "
          f"(live locked: {auto.get('live', {}).get('locked')}); Windows Graphics Capture {wgc}")
    return 0 if ok and stopped else 1


def main():
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    inst = SingleInstance()
    if inst.already_running:
        try:
            httpx.post(f"{API}/desktop/focus", headers=HEADERS, timeout=3)
        except httpx.HTTPError:
            message_box("Study Terminal", "Study Terminal is already starting. Give it a few seconds.", error=False)
        return
    choose_port()
    try:
        App(minimized="--minimized" in sys.argv).run()
    except Exception:  # noqa: BLE001
        helpf = save_help_file()
        message_box("Study Terminal error", "Study Terminal hit an unexpected error and closed. Your data hasn't been changed; "
                    "open it again to carry on.\n\n" + (f"A help file was saved so you can send it:\n{helpf}\n\n" if helpf else "")
                    + "(Technical details: " + traceback.format_exc(limit=2)[-600:] + ")")
        raise
    finally:
        inst.release()


if __name__ == "__main__":
    main()
