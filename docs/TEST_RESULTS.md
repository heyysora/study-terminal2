# Test results (0.18.3, 2026-11-16)

## 0.18.2 — the screen-text reader, and the gate that was missing (2026-11-16)

**Root cause reproduced before any change was made.** A folder holding only `config.yaml` with its parent on the
import path, imported by name:

```
imported    : <module 'ch_ppocr_v3_det' (NamespaceLoader)>
is namespace: True
REPRODUCED  : AttributeError: module 'ch_ppocr_v3_det' has no attribute 'TextDetector'
```

| Test category | Result |
|---|---|
| Unit and integration (this machine) | **646 pass**, 0 fail, on Python 3.11 (rapidocr 1.4.4) and Python 3.13 (rapidocr 1.2.3) — 17 new |
| Reader check against a deliberately broken bundle | **PASS** — caught, with the correct repair advice |
| Reader check against the real library, both layouts | **PASS** — engine starts, reads known text from a dark image |
| Ten subsystem checks (source tree) | **PASS** — imports, image handling, maths, model fitting, database, calendars, time zones, model runtime, reader, crypto client (read-only) |
| Windows CI, packaged app | see the run for this version: checks 12 and 13 are new and gate the release |
| **Real PC (the user's Windows 11, Edge, TopstepX)** | **NOT TESTED** — no access; the first run of this installer is what settles it |

New tests (17): an empty folder masquerading as a module; a module present but lacking its class; a missing model
file; the library absent entirely; the check never raising; a broken reader being its own error type; a dead reader
not being restarted on every capture; the plain words for it not blaming the chart; the test image being genuinely
readable; the reader working here, quick and deep; every subsystem doing real work; a broken subsystem reported not
raised; a crashing endpoint answering in JSON; an unknown path refused; a refused request still explaining itself;
a dead reader reached through a real request answering 503 with the repair.

Correction: the 0.18.1 note said 657 tests. The suite at that commit held 629. Counts here come from
`pytest --collect-only`.


## 0.18.1 — reading your TopstepX chart (2026-11-16)

Run against the actual screenshot of your Edge window (1920x1074, whole window captured, nothing set by hand):

| What | 0.18.0 | 0.18.1 |
|---|---|---|
| Window matched | yes | yes |
| Market | NQ (from the tab title) | NQ (from the tab title) |
| Timeframe | not found | **1Min, from the chart label** |
| Price | 27,686.00 | 27,686.00 |
| Candles read | 219 | 219 |
| Overall confidence | **0.00** | **0.51** |
| Status | UNREADABLE | readable |

- 629 tests pass on Python 3.11 and 3.13 (an earlier draft of this line said 657; that number was wrong and is corrected here). 6 new tests cover the glued timeframe, the label shape, a stray number not being mistaken for a timeframe, a hand-set timeframe clearing the gate, a missing label not blacking out the chart, and the error text naming its own line.
- Two existing tests were corrected, not removed: one asserted the old "set but never counted" timeframe behaviour; the other compared two whole API payloads including a timestamp computed as "now + minutes to close", so it failed on any run within an hour of the daily futures break (it fired for the first time today). Both now test the same thing without the clock race.


## 0.18.0 (automated practice trading on by default, weekly strategy re-testing)

- SIMULATED TEST ONLY, Linux, Python 3.11 and 3.13: 621 passed, 0 failed on each. New: mode B as the default and the migration of an older saved state, an explicit choice being kept, a validated strategy traded in practice without being asked, the weekly schedule (never tested, 7 days, waiting for a closed market, forced after 11 days, oldest first, one per tick), a permanent run history that survives a restart, a strategy losing its validation and stopping, a failed run being reported, and the switch-off.
- VERIFIED WITH LIVE DATA, Linux build machine: one real research run end to end on MES through the installed code path. It took 231 seconds, used 59 days of real 5-minute bars, returned 57 out-of-sample trades averaging 0.185R, tier "inconclusive", and therefore validated nothing. The schedule, the history and the trust page all updated from that run.
- VERIFIED ON WINDOWS (GitHub Windows Server 2025, run 43752542117, installed app): full Windows test suite passed; 55 of 55 reliability checks passed, including the upgrade from 0.17.0 with journals, practice accounts and settings unchanged, and the real window start (app page loaded 8.3 s after the window opened).
- UNVERIFIED: a weekly run firing on its own schedule (only forced runs and scripted ones were exercised); automatic entry of a validated strategy with real market data, because no strategy is validated; everything on your PC.

## 0.17.0 (TopstepX tab fix, every TopstepX window, faster start, automatic trust evidence)

- SIMULATED TEST ONLY, Linux, Python 3.11 and 3.13: 611 passed, 0 failed on each. New: the exact tab title reported from a real PC ("NQZ26 $27,927.25 ▼ -1.61%") through the window finder, window list, privacy check and monitor; several TopstepX windows attaching and detaching; timeframe worked out from candles at 1, 5, 15 and 60 minutes; trust reaching Visual validation from automatic samples only, and failing when the chart's label and its candles disagree.
- VERIFIED ON WINDOWS (GitHub Windows Server 2025, run 43718274246, installed app): full Windows test suite passed; 55 of 55 reliability checks passed, including the rescue drill that failed for 0.16.1, the upgrade from 0.16.0, the data-check drill with live sources, and a new check that starts the real window: loading screen first, engine ready 6.9 s after the window opened, the app's page loaded at 7.6 s.
- Measured on the Linux build machine: engine answering 2.0 s after launch; four seconds after start, Home answers in 5 ms and the other first screens in under 160 ms (they were 0.4 to 1.4 s before the warm-up).
- UNVERIFIED: all of it on your PC. In particular the TopstepX fix was built from the tab title you reported and has not been seen working against your Edge window; the timeframe and candle checks have never run on a real chart.
- 0.16.1 was built but not published: 51 of 54 Windows checks passed. The three failures were in the test scripts (a same-second time comparison in the recovery drill, and the upgrade check not expecting the app's own data-check records), not in the app.

## 0.16.0 (data validation, safety controller, TopstepX automatic validation)

Each line says where it ran and whether the data was real or simulated.

- SIMULATED TEST ONLY, Linux, Python 3.11 and 3.13: 587 passed, 0 failed on each (35 new cases: 34 in `test_datahealth.py`, 1 in `test_integration.py`). These prove the software handles corrupted, stale, conflicting and missing data correctly. They are not evidence about any live source.
- VERIFIED WITH LIVE DATA, Linux build machine, 2026-11-14 (Saturday; US stock and futures markets closed): crypto exchanges VERIFIED (three exchanges within 0.06–0.41%), Solana token data VERIFIED (DexScreener vs Jupiter and GeckoTerminal; token identity vs the chain), stock prices HEALTHY, futures prices DELAYED, Solana RPC HEALTHY, FOMO and pump.fun direct UNSUPPORTED, TopstepX chart UNVERIFIED.
- VERIFIED ON WINDOWS (GitHub Windows Server 2025, run 43673137873, installed app, live sources): full Windows test suite passed; 54 of 54 reliability checks passed (the 39 install, upgrade and recovery checks plus 15 data-check drill results). From that machine: crypto VERIFIED (largest gap 0.18%), Solana token data VERIFIED, stocks HEALTHY, futures DELAYED, Solana RPC HEALTHY, FOMO and pump.fun UNSUPPORTED, TopstepX UNVERIFIED; safety controller matched the data; evidence stored with versions and kept across a restart.
- UNVERIFIED: freshness and "still updating" for stocks and futures during market hours (markets were closed for every run); a real outage on Windows; anything on your PC.
- BLOCKED on your PC: TopstepX chart validation (needs a logged-in chart in Edge).

## 0.15.0 (dark look, crypto exchange prices, memecoin exit plans and journal)

- Here (Linux, Python 3.11 and 3.13): 552 passed, 0 failed on each. (One port-discovery test failed once when both suites ran at the same moment and grabbed the same ports; it passes on its own and in a single run.)
- GitHub Windows Server 2025, run 43669539846: full test suite passed; packaged self-test reports "crypto price library read-only"; reliability 39/39 checks passed, including upgrade from 0.14.1 and the recovery drill.
- Your PC: not tested yet.

## 0.14.1 (design-only release)

- Here (Linux, Python 3.11): 538 passed, 0 failed.
- GitHub Windows Server 2025, run 43658335608: full test suite passed (publish only runs when it does); reliability 39/39 checks passed, including install, upgrade from 0.14.0 and the recovery drill.
- Your PC: not tested yet. Passing on GitHub's Windows machine is not the same as passing on yours.

## Automated tests

| Run | Result |
|---|---|
| Python 3.11, Linux (rapidocr 1.4.4) | **517 passed**, 0 failed |
| Python 3.13, Linux (rapidocr 1.2.3, same OCR version as the Windows app) | **517 passed**, 0 failed |
| Python 3.12, GitHub Windows Server 2025 machine, 0.13.6 build (run 43631197421) | **517 passed**, 0 failed |
| Same, 0.13.5 build (run 43555645264) | 512 passed, 0 failed |
| Same, an earlier 0.13.5 build (run 43554150282) | 511 passed, 1 failed (extension port discovery timed out; fixed) |
| Same, 0.13.4 build (run 43539726145) | 502 passed, 0 failed |
| Same, 0.13.3 build (run 43532538992) | 485 passed, 0 failed |
| Same, 0.13.2 build | 482 passed, **1 failed** (wrong market reported as Working; fixed in 0.13.3) |
| Lint (`ruff --select E9,F,B`) on files changed in 0.13.x | clean |

Passing these tests shows the code does what the tests check, on made-up charts and fake servers. It doesn't show the app reads
your real TopstepX chart correctly; see `docs/STUDY_TERMINAL_READINESS_REPORT.md`.

## Windows reliability (GitHub-hosted Windows Server 2025, not your PC)

0.13.6, run 43631197421: **39 passed**, 0 failed (upgrade 0.13.5 -> 0.13.6 kept all data).

0.13.5, run 43555645264: **39 passed**, 0 failed, including 20 recovery-drill checks against the installed app (backup,
restore with automatic restart, corrupted file, partial rescue, failed restore and rollback, data identical throughout). Details:
`docs/WINDOWS_RECOVERY_AUDIT.md`.

0.13.4, run 43539726145: **19 passed**, 0 failed, nothing left "observed": a damaged data file opens Recovery mode, a restore
from it brings your data back exactly, and the app starts when its port is taken.

0.13.3, run 43532538992: **16 passed**, 0 failed, 1 observed (damaged database: the app won't start; the file is kept).
Upgrade tested from 0.13.2 with data: everything kept.

0.13.2, run 43525788935: 15 passed, 1 failed (the upgrade check was too strict on two files meant to change; all your data came
through identical; check fixed), 1 observed (a damaged database stops the app from starting; the file is kept). Details:
`docs/POST_FEATURE_AUDIT.md`, Phase 5.

## Weekend prices (0.13.6), checked on Saturday 2026-11-14 on Linux with real Yahoo data

- Bitcoin streamed live: 21 price updates in 100 seconds, labelled near real-time (unofficial free feed).
- SPY and NQ futures labelled closed with the right opening times (Mon 9:30 AM ET, Sun 6:00 PM ET); Home gave Friday's real
  results (SPY -0.36%, NQ -1.23%) from daily bars; the Charts page showed SPY's official close and the after-hours price.
- Not checked on your PC, and not with your TopstepX chart open on a weekend.

## Real use

- Your PC: last checked with 0.7.0 (20 of 20). Nothing since.
- Your real TopstepX chart: never. Use the Chart check (`docs/REAL_CHART_TESTING.md`).

## 0.12.0 preview 2: live price

| Check | Result |
|---|---|
| `test_live_price.py` (13): price-box read matches the full read; follows a moving chart; every check can reject (confidence, off the price steps, dropped digit, wrong digit, garbage, no box); jumps wait for confirmation; gaps break the line; thinning keeps order and gaps; saved and reloaded; old files removed; session starts at 6 PM New York; the monitor's fast path through to the endpoint; profile validation | passed |
| Accuracy on 300 moving SYNTHETIC frames (three price levels, scale changes included) | rapidocr 1.4.4: 297 accepted, 0 wrong, 3 rejected; rapidocr 1.2.3: 288 accepted, 0 wrong, 12 rejected (rejected frames fall back to a full read) |
| Fast read time | median 25 ms (1.4.4) |
| Screens in headless Chrome with a moving SYNTHETIC chart, light and dark | checked by eye |

## 0.12.0 preview 1: interface foundation

| Check | Result |
|---|---|
| `test_plain.py` (10): word list in sync with the frontend; every pipeline reason and every chart-quality reason has plain words; risk messages keep their numbers; every non-approved outcome reads WAIT; only live statuses read "Working" and delayed is never called live; unknown reasons pass through unchanged | passed |
| `test_home.py` (16): the five answers for working, frozen, minimized and unreadable charts; an idea shows what it could lose; an untested idea stays WAIT; a stored decision is never shown as an idea; tightest loss limit; next step from real setup state; stopped state; stocks view; through the real app: fresh install, Simple vs Advanced leave settings, limits, risk status and the live lock identical, Stop everything (needs confirmation, leaves hand-placed practice trades, can't be switched back on without a written note, starts nothing by itself), Home survives a failing part | passed |
| `test_backup.py` (6): no backup on a fresh folder; database and data files copied, `.env` and logs never copied, originals byte-identical; one backup per build; only the newest 10 kept; a failed backup reports and never raises; the app backs up on first start of a new build | passed |
| Frontend type-check and production build | passed |
| Upgrade 0.11.0 -> 0.12.0 on one data folder (seeded with the real 0.11.0 code) | all 4 data files byte-identical; all 10 user-visible views identical; 25 of 30 database rows identical, the other 5 are the monitoring heartbeat and re-evaluated decision timestamps (same as on every start); the automatic backup's database is identical to the pre-upgrade database |
| Packaged app self-test (PyInstaller, Linux) | passed: backend up, clean shutdown, live locked; a second start on the same folder makes no second backup |
| Screens checked in headless Chrome (Linux) with a SYNTHETIC demo chart: Home first run, Home with a readable chart, Home with a frozen chart, Stop everything dialog and stopped state, Advanced mode, narrow window | looked at by eye; screenshots in docs/ |

Not tested: anything on Windows (the desktop window, the installer, real Edge/TopstepX capture feeding Home), and no usability test
with a real beginner. The packaged Linux self-test logs one error from the `websockets` library while shutting down under uvloop
(`'ClientConnection' object has no attribute 'recv_messages'`); it comes from the library closing a half-open connection, the
self-test still exits 0, and Windows doesn't use uvloop.

## 0.11.0 Trust & Validation rules

`test_trust.py` (9) tests the validation RULES with hand-built records (see docs/TRUST_VALIDATION.md). They don't produce evidence.
On a fresh install the dashboard reports EXPERIMENTAL: categories 1-5 and 8-9 UNTESTED, 6-7 IN PROGRESS from the bundled research
(NQ/MNQ inconclusive, ES/MES losing; no validated strategy).

## 0.10.0 Edge capture tests (SCREENSHOT-BASED, not live-market validation)

`test_edge_capture.py` (7) with fake capture backends and the synthetic recorded screenshots: frame checks (blank, flat, mostly black
partial GPU frames); Automatic order Graphics Capture → PrintWindow → screen with fallback on blank frames; covered window refused for
screen capture; pinned method never silently switched; Edge windows listed first; manual calibration invalidated by a zoom/rescale and
by a resize, one alert, analysis paused, recovery after recalibration; window closed → DISCONNECTED → reopened → LIVE; failing captures
→ UNREADABLE → STALE → recovery; visual data never reaches the simulator. Plus a market-read test in `test_visual_monitor.py`.
The page was rendered in Chrome with the app's capture replaced by a recorded synthetic screenshot (`docs/screenshot_live_visual.png`).
**No test ran against Microsoft Edge, TopstepX, Windows Graphics Capture or live market data.**

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
- **Visual Monitor window capture on Windows, including Windows Graphics Capture of Edge**: not run by me (Linux build machine).
- **Mobile companion from a real phone / tunnel**: in-process tests only.
- **Claude / Ollama wording**: no key or local model available.

## How to run

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests          # or: ..\scripts\test.ps1
cd ..\frontend; npm ci; npm run build
```
