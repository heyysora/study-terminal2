# Test results (0.9.0, 2026-11-09)

All runs were on **Linux** in the build environment. Nothing here was run on Windows.

## Automated tests

| Run | Result |
|---|---|
| Python 3.11 (`pytest tests`) | **387 passed**, 0 failed, 0 skipped (≈ 100 s) |
| Python 3.13 (`pytest tests`) | **387 passed**, 0 failed, 0 skipped (≈ 100 s) |
| Frontend type-check and build (`npm run build` = `tsc -b && vite build`) | passed |
| Lint (`ruff --select E4,E7,E9,F,B`) on files changed in 0.7 | clean except pre-existing style warnings in older files (B008/E741/B904) |

## 0.9.0 Visual Market Monitor tests (SYNTHETIC screenshots)

`test_visual_monitor.py` (17) runs on four recorded synthetic screenshots in `tests/fixtures/visual` (generated with exact ground truth by
`make_fixtures.py`). Results on them: instrument, timeframe, price tag, bid and ask read exactly; 70/70 candles found with open/high/
low/close within 2 ticks (max error 0.25-0.5 points, i.e. 1-2 MNQ ticks); relative volume within 0.03 on average; VWAP/EMA lines
within 4 ticks; zoomed-out charts correctly flagged low confidence; blank, missing, minimized, covered, frozen and changed-layout
charts produce NO TRADE with the reason. **These numbers say nothing about real TopstepX charts**: no real TopstepX screenshot was
available. The calibration workflow measures that on yours.

The setup and monitor screens were driven in headless Chrome (upload a screenshot, drag the region, Test read, Save, Start): the test
read showed MNQ, 5Min, the exact price, bid/ask and 70 candles, and the monitor showed DISCONNECTED with NO TRADE (no Windows windows
exist on the build machine). Screenshots: `docs/screenshot_visual_setup.png`, `docs/screenshot_visual_monitor.png`.

## 0.8.0 live market data tests (all MOCKED)

These run against a local mock SignalR hub (`tests/mock_signalr.py`) and fake REST responses. They test Study Terminal's own logic;
**they say nothing about the real TopstepX service**, which hasn't been connected to.

| File | Covers |
|---|---|
| `test_live_candles.py` (9) | trade → 1-minute candle construction, closing on the clock, duplicates, out-of-order prints revising the right bar, too-late prints, tick precision and off-grid prints, session edges and close prints, 5m aggregation and volume sums, session-anchored 1h/4h/daily, backfill replacing ended minutes only, missing-minute detection |
| `test_live_stream.py` (8) | hub handshake with the token, exactly the two documented subscriptions, refusal of any other method, quotes and trades with source/exchange/receipt times, late prints not moving the last price back, duplicates, STALE after 30 s silence, closed market, disconnect → DISCONNECTED → automatic reconnect → REST backfill and gap log → re-subscription, refused subscription shown as DISCONNECTED, bar-close callback, contract rollover and resubscription, data-layer labels (LIVE only from the stream; DISCONNECTED not tradable), Yahoo never live |
| `test_live_chart.py` (5) | chart API without credentials is never live, EMAs/VWAP/levels/structure/swings/FVGs/profile each tied to real bars and prices, session-aligned 1h/4h/daily, input validation, automation re-evaluation only on 5-minute closes, decisions skipping the forming candle |

Manual check (also mocked): the app was run against `research/mock_topstepx.py` (synthetic prices) and the Live Market screen was
opened in Chrome. The status bar read LIVE with source `topstepx-stream`, and the price, bid/ask and update counter changed every few
hundred milliseconds (27 in-place updates in 12 s, no page reload). Dropping the mock's connections showed DISCONNECTED, then
reconnected within about a second with a backfill entry in the gap log. Pausing the mock's trades turned the status STALE after
30 s and greyed the chart (screenshots: `docs/screenshot_live_market_mock.png`, `docs/screenshot_live_market_stale_mock.png`;
synthetic prices). The frozen PyInstaller bundle of 0.8.0 passed `--self-test` on Linux. The decision pipeline accepted the streamed data at step 1 (and stopped at step 3, outside RTH).

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
- **TopstepX API and live stream**: tested against mock servers only. See the real-account checklist in
  [LIVE_MARKET_DATA.md](LIVE_MARKET_DATA.md#what-still-needs-a-real-topstepx-account).
- **Real TopstepX screenshots**: none available; the Visual Monitor and the calibration tool were tested with synthetic charts (which never count as accuracy).
- **Visual Monitor window capture on Windows**: not run by me (Linux build machine).
- **Mobile companion from a real phone / tunnel**: in-process tests only.
- **Claude / Ollama wording**: no key or local model available.

## How to run

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests          # or: ..\scripts\test.ps1
cd ..\frontend; npm ci; npm run build
```
