# Test results (0.7.0, 2026-11-08)

All runs were on **Linux** in the build environment. Nothing here was run on Windows.

## Automated tests

| Run | Result |
|---|---|
| Python 3.11 (`pytest tests`) | **348 passed**, 0 failed, 0 skipped (≈ 95 s) |
| Python 3.13 (`pytest tests`) | **348 passed**, 0 failed, 0 skipped (≈ 80 s) |
| Frontend type-check and build (`npm run build` = `tsc -b && vite build`) | passed |
| Lint (`ruff --select E4,E7,E9,F,B`) on files changed in 0.7 | clean except pre-existing style warnings in older files (B008/E741/B904) |

No test was deleted or skipped to make the suite pass. Tests use no internet: market data comes from a fake provider,
recorded real ES 5-minute bars, rendered chart images, and mocked BLS / ProjectX HTTP.

Tests per file: futures contracts 42 · futures risk/paper 25 · stock paper engine 21 · futures analysis 20 · screen 19 ·
P8/P9 (calibration, BLS values, event warnings, futures mentor) 17 · decision pipeline 15 · P1 audit regressions 12 ·
automation 12 · analysis 12 · integration 10 · evidence 10 · API 10 · signals 9 · Yahoo provider 8 · news 8 · journal 8 ·
futures screen 8 · P2 data reliability 8 · freshness 8 · config/logging 8 · backtest 8 · P10 mobile 7 · market clock 7 ·
P6/P7 evaluation and replay 7 · extension 7 · data reliability 7 · futures API 6 · futures research 4 · Yahoo stream 3 ·
P11 number formatting 2.

## Checks against live services (2026-11-08, a Sunday)

| Check | Result |
|---|---|
| App started from source against real Yahoo data; automation cycle over NQ, MNQ, ES, MES | Ran. All four labelled DELAYED; every decision NO TRADE with "No decisions on delayed data" (correct: delayed data never produces decisions) |
| Economic calendar with BLS published values | All five series returned: CPI and core CPI (September 2026), PPI final demand (September 2026), payrolls and unemployment (October 2026) |
| Mentor futures answers on live data (why rejected, nearest support, size, best strategy) | Answered from the pipeline, levels, risk engine and research. Found and fixed a formatting bug: NQ-sized prices printed with 6 significant digits (26952.25 → 26952.2); now exact everywhere in futures messages, with a regression test |
| Screenshots of the Automation Center, Futures page and Live copilot (headless Chrome) | Rendered; saved as `docs/screenshot_*.png` |
| Frozen bundle (PyInstaller 6.22, Python 3.13) `--self-test` | `backend up; clean shutdown yes; version 0.7.0; brokerage_required=False; futures presets loaded; automation running (live locked: True)` |

## Not tested (and why)

- **Windows**: desktop window, tray, toasts, hotkey, window capture, installer. Run `scripts\verify-windows.ps1` on your PC.
- **Live futures fills and automated entries**: need a fillable feed (TopstepX API subscription). Tested with recorded bars,
  replay and injected clocks only.
- **TopstepX API**: tested against a mock server only.
- **Real TopstepX screenshots**: none available; calibration tool tested with synthetic charts (which never count as accuracy).
- **Mobile companion from a real phone / tunnel**: in-process tests only.
- **Claude / Ollama wording**: no key or local model available.

## How to run

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests          # or: ..\scripts\test.ps1
cd ..\frontend; npm ci; npm run build
```
