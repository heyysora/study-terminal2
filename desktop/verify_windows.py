"""Checks every Windows-only piece of Study Terminal on this PC and writes a report.

Run:  .\\scripts\\verify-windows.ps1      (or:  backend\\.venv\\Scripts\\python.exe desktop\\verify_windows.py)

Automatic checks (PASS/FAIL): Python + packages, WebView2 runtime, screen capture (monitor and a real window,
in memory only, nothing saved), single-instance mutex, global hotkey, tray icon creation, the desktop app's
self-test (backend starts, answers, shuts down cleanly).
Checks that need your eyes (CONFIRM): a Windows notification and a sound are sent, the tray icon appears for
10 seconds. Answer y/n when asked. The report is saved to %LOCALAPPDATA%\\StudyTerminal\\logs\\windows-check.json.
"""
from __future__ import annotations

import json
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
results: list[dict] = []


def rec(name: str, status: str, detail: str = "") -> None:
    results.append({"check": name, "status": status, "detail": detail})
    print(f"[{status:7}] {name}{': ' + detail if detail else ''}")


def ask(q: str) -> bool | None:
    try:
        a = input(f"         {q} [y/n] ").strip().lower()
    except EOFError:
        return None
    return a.startswith("y")


def main() -> int:
    if sys.platform != "win32":
        print("This check is for Windows.")
        return 2
    rec("Windows version", "INFO", f"{platform.platform()} ({platform.machine()})")
    rec("Python", "PASS" if sys.version_info >= (3, 11) else "FAIL", sys.version.split()[0])
    for mod in ("webview", "pystray", "win11toast", "mss", "rapidocr_onnxruntime", "cv2", "yfinance", "exchange_calendars"):
        try:
            __import__(mod)
            rec(f"package {mod}", "PASS")
        except Exception as e:  # noqa: BLE001
            rec(f"package {mod}", "FAIL", f"{type(e).__name__}: {e}")

    # The text reader, for real. "package rapidocr_onnxruntime PASS" above only means the name imports: in 0.18.1 it
    # imported fine and the reader was still broken, because the parts it loads by name at run time were missing from
    # the build. So start the engine and read known text.
    try:
        from app.screen import ocr_health
        r = ocr_health.check(deep=True)
        for st in r["steps"]:
            rec(f"text reader: {st['name']}", st["status"].upper() if st["status"] != "skipped" else "INFO", st.get("detail", ""))
        rec("text reader overall", "PASS" if r["ok"] else "FAIL", r["headline"] + (" " + r["advice"] if r["advice"] else ""))
    except Exception as e:  # noqa: BLE001
        rec("text reader overall", "FAIL", f"{type(e).__name__}: {e}")

    # WebView2 runtime (needed for the app window)
    import winreg
    ver = None
    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
                      (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")):
        try:
            with winreg.OpenKey(hive, key) as k:
                ver = winreg.QueryValueEx(k, "pv")[0]
                break
        except OSError:
            continue
    rec("WebView2 runtime", "PASS" if ver and ver != "0.0.0.0" else "FAIL",
        ver or "not found: install the Evergreen WebView2 Runtime from Microsoft (Windows 11 normally has it)")

    # screen capture: in memory only
    from app.screen.capture import Target, capture, list_targets
    tg = list_targets()
    mons = [t for t in tg if t.get("kind") == "monitor"]
    wins = [t for t in tg if t.get("kind") == "window"]
    rec("list monitors/windows", "PASS" if mons and wins else "FAIL", f"{len(mons)} monitor(s), {len(wins)} window(s)")
    if mons:
        img, how = capture(Target(kind="monitor", id=mons[0]["id"], title=mons[0]["title"]))
        ok = img is not None and float(img.mean()) > 1
        rec("capture a monitor", "PASS" if ok else "FAIL", f"{how}, {None if img is None else img.shape}")
    if wins:
        best = None
        for w in wins[:15]:
            img, how = capture(Target(kind="window", id=w["id"], title=w.get("title", ""), process=w.get("process")))
            if img is not None and float(img.std()) > 5:
                best = (w, img, how)
                break
        rec("capture a window (PrintWindow)", "PASS" if best else "FAIL",
            f"'{best[0].get('title', '')[:40]}' {best[1].shape} via {best[2]}" if best else "no window captured with content")

    # single instance mutex
    import ctypes
    k32 = ctypes.windll.kernel32
    h1 = k32.CreateMutexW(None, False, "Local\\StudyTerminal.VerifyMutex")
    h2 = k32.CreateMutexW(None, False, "Local\\StudyTerminal.VerifyMutex")
    second_sees = k32.GetLastError() == 183
    k32.CloseHandle(h2)
    k32.CloseHandle(h1)
    rec("single-instance mutex", "PASS" if second_sees else "FAIL")

    # global hotkey (Ctrl+Alt+S) can be registered
    u32 = ctypes.windll.user32
    ok = bool(u32.RegisterHotKey(None, 77, 0x0001 | 0x0002, 0x53))
    if ok:
        u32.UnregisterHotKey(None, 77)
    rec("hotkey Ctrl+Alt+S", "PASS" if ok else "FAIL", "" if ok else "another app already uses Ctrl+Alt+S")

    # desktop app self-test (backend up, health, clean shutdown) in a throwaway data folder
    import os
    import tempfile
    env = {**os.environ, "STUDY_TERMINAL_DATA_DIR": tempfile.mkdtemp(prefix="st-verify-"), "PORT": "8798", "NEWS_ENABLED": "false"}
    exe = ROOT / "dist" / "StudyTerminal" / "StudyTerminal.exe"
    cmd = [str(exe), "--self-test"] if exe.exists() else [sys.executable, str(ROOT / "desktop" / "launcher.py"), "--self-test"]
    try:
        p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)
        rec(f"desktop self-test ({'packaged exe' if exe.exists() else 'from source'})", "PASS" if p.returncode == 0 else "FAIL",
            (p.stdout.strip().splitlines() or [p.stderr.strip()[-300:]])[-1])
    except subprocess.TimeoutExpired:
        rec("desktop self-test", "FAIL", "timed out after 180 s")

    # things you have to see or hear
    from app.alerts.service import Notifier
    n = Notifier("http://127.0.0.1:8765")
    sent = n.toast("Study Terminal check", "If you can see this, Windows notifications work.", "/")
    time.sleep(4)
    seen = ask("Did a Windows notification titled 'Study Terminal check' appear?") if sent else False
    rec("Windows notification", "PASS" if seen else "FAIL" if seen is False else "CONFIRM", n.last_error or "")
    n.sound("high")
    heard = ask("Did you hear a Windows alert sound?")
    rec("alert sound", "PASS" if heard else "FAIL" if heard is False else "CONFIRM", "check that system sounds aren't muted")
    try:
        import threading

        import pystray
        from PIL import Image
        icon = pystray.Icon("StudyTerminalCheck", Image.new("RGB", (64, 64), (224, 164, 58)), "Study Terminal check")
        threading.Thread(target=icon.run, daemon=True).start()
        time.sleep(1)
        seen = ask("Is there a new amber square in the system tray (bottom right, maybe under ^)?")
        icon.stop()
        rec("tray icon", "PASS" if seen else "FAIL" if seen is False else "CONFIRM")
    except Exception as e:  # noqa: BLE001
        rec("tray icon", "FAIL", f"{type(e).__name__}: {e}")

    out = Path(os.environ.get("LOCALAPPDATA", ".")) / "StudyTerminal" / "logs" / "windows-check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "results": results}, indent=1))
    fails = [r for r in results if r["status"] == "FAIL"]
    print(f"\n{len(results)} checks, {len(fails)} failed. Report: {out}")
    print("Still check by hand: open the app, close the window (should hide to tray), Ctrl+Alt+S (should reopen), "
          "Quit from the tray (should exit within a few seconds).")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
