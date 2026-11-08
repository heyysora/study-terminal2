# Windows verification

**Status: not yet verified on Windows 11.** The build environment is Linux. I asked for access to your
Windows PC to install and test there, and that access was declined, so nothing below is marked as passing
on Windows until you run the check.

## What was verified, and where

| Part | Verified | Where / how |
|---|---|---|
| Backend, analysis, signals, journal, news, paper trading, API | Yes | 170 automated tests on Python 3.13 and 3.11 (Linux) |
| Packaged app starts, serves the UI, shuts down cleanly | Yes, on Linux | PyInstaller build of the same spec, `StudyTerminal --self-test` |
| Bundled files found in the installed layout (UI, OCR models, exchange calendar, BLS schedule) | Yes, on Linux | Same frozen build |
| Single instance, focus hand-off from a second launch | Partly | The focus API round-trip works; the Windows mutex is untested |
| Chrome extension | Yes | Real Chrome + real TradingView tab + real backend, end to end |
| WebView2 window, close-to-tray, Ctrl+Alt+S | **No** | Windows only |
| Tray icon and menu | **No** | Windows only |
| Toast notifications and alert sound | **No** | Windows only |
| Window capture (PrintWindow) and monitor capture | **No** | Windows only |
| Installer (Inno Setup), shortcuts, uninstall, start on login | **No** | Needs Windows to build and run |

## Run the check (about 2 minutes)

```powershell
cd <the unzipped StudyTerminal folder>
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1          # first time only
powershell -ExecutionPolicy Bypass -File .\scripts\verify-windows.ps1
```

It checks automatically: Python and packages, the WebView2 runtime, monitor capture, window capture (in memory,
nothing saved), the single-instance mutex, the Ctrl+Alt+S hotkey, and the desktop self-test (backend starts,
answers, shuts down cleanly). Then it asks you to confirm that you saw a notification, heard a sound and saw a
tray icon. The report goes to `%LOCALAPPDATA%\StudyTerminal\logs\windows-check.json`; send it to me if anything fails.

Then by hand (2 minutes):
1. `.\scripts\run-desktop.ps1`: the window opens.
2. Close the window: it should disappear to the tray with a "still running" notice.
3. Press Ctrl+Alt+S: the window comes back.
4. Launch `run-desktop.ps1` a second time: no second copy; the first window comes forward.
5. Tray > Quit: the app exits within a few seconds. `%LOCALAPPDATA%\StudyTerminal\logs\desktop.log` should say
   "backend stopped cleanly".
6. Settings > About and files > Open logs folder: Explorer opens the logs.

## Installer check
```powershell
winget install JRSoftware.InnoSetup        # free, once
powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1
```
The build runs the packaged app's self-test before making the installer. Then run
`dist-installer\StudyTerminal-Setup-0.5.0.exe` and check the Start menu entry, the desktop shortcut (if
ticked), the app icon, Settings > About ("installed app"), and Uninstall from Windows Settings > Apps (it asks
whether to keep your data).
