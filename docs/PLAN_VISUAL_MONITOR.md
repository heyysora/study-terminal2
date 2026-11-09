# Visual Market Monitor (plan, 2026-11-09)

Goal: use the TopstepX chart already on your Windows screen as the market-analysis input, with no paid data API.
Authorized screen capture only: no private endpoints, no token interception, no browser storage, no clicking.

## Reused from the existing code

| Existing | Reused for |
|---|---|
| `screen/capture.py`: window list (EnumWindows), PrintWindow capture with `mss` fallback, `frame_change` | window selection, continuous capture, change detection |
| `screen/vision.py`: OCR (RapidOCR), `find_price_axis` (fits price = a*y + b from axis labels), `last_price_tag`, `recognize` (ticker/timeframe incl. TopstepX adapter), `detect_auth_screen`, `horizontal_lines` | reading price, axis, instrument, timeframe; refusing login screens |
| `screen/calibration.py` (0.7) | real-screenshot accuracy workflow, extended to candle fields |
| `futures/features.py`, `pipeline.py`, `risk.py` | structure (BOS/CHoCH, swings, FVGs, sweeps, VWAP, regime) and the 13-step decision with the existing risk engine and evidence rules |
| `alerts/service.py` | notifications with de-duplication |
| `futures/sessions.py`, `contracts.py` | session-aware candle times, tick grid, NQ/MNQ/ES/MES specs |

## New pieces

1. **Chart profiles** (`screen/chart_profile.py`): saved per chart layout: window match, capture region, instrument and timeframe
   (auto-read or fixed), price-axis calibration (auto from labels or two manual points), colors of up/down candles, VWAP and EMA lines,
   volume-pane position, capture interval, stale/frozen thresholds.
2. **Chart reader** (`screen/chart_reader.py`): one capture of the region → instrument, timeframe, current price, bid/ask, axis,
   candles (OHLC from pixels), volume bars (relative), indicator lines, horizontal levels. Every value carries a class
   (A TEXT / B CALCULATED / C ESTIMATED / D UNAVAILABLE), a confidence and the capture time.
3. **Visual bars** (`screen/visual_bars.py`): candles → timestamped bars (session-aware), merged across captures.
4. **Monitor service** (`screen/visual_monitor.py`): background loop independent of the page; start/pause/resume/stop; checks for
   missing/minimized/obscured windows, blank captures, frozen charts, layout changes, falling confidence; status labels
   SCREEN_CAPTURE / VISUAL_OBSERVATION / VISUALLY_ESTIMATED / DELAYED / STALE / UNREADABLE / DISCONNECTED.
5. **Recommendations** (`screen/visual_recommend.py`): quality gates → NO TRADE with the reason; otherwise the existing pipeline and
   risk engine; LONG / SHORT / WAIT / EXIT / NO TRADE with entry, stop, T1, T2, R:R, setup, evidence, invalidation, timeframe,
   data confidence, capture time. Alerts de-duplicated.
6. **Visual Market Monitor screen**: window picker, live preview with a draggable/resizable region, click-to-calibrate axis and
   colors, saved profiles, monitoring controls, readings table by class, recommendation card, alerts.
7. Tests on recorded screenshots (synthetic, labelled as such) and docs with exact Windows steps.

## Limitations to expect

- **Precision is limited by pixels.** Candle OHLC comes from pixel rows. On a typical NQ chart one pixel is about 1–3 ticks, so
  candle values are estimates (class C). Only the price-tag text (class A) is read exactly, and OCR can misread it.
- **Only what's visible exists.** History is the candles on screen. Previous-day levels, session VWAP or a 200 EMA need that history to
  be visible; otherwise they're UNAVAILABLE. Volume bars give relative volume only (no contract counts).
- **Indicator identity comes from you.** A line is "VWAP" or "EMA 20" only because you assign its color in the profile.
- **Candle times are calculated** from the timeframe and the capture time, assuming no missing candles between visible ones.
- **Window capture is Windows-only** and hasn't been run on Windows by me. PrintWindow usually captures covered windows, but some
  GPU-rendered browser windows come back black; then the window must be visible. Minimized windows can't be captured.
- **No real TopstepX screenshots exist in this project.** Automated tests use synthetic screenshots, which prove the logic but not
  accuracy on your charts. The calibration workflow measures that on your own screenshots.
- **Evidence rule unchanged.** LONG/SHORT need a strategy that passed walk-forward validation (none has yet). Until then, complete
  setups are reported as WAIT "potential LONG/SHORT setup", with full plans and alerts, and the reason.
- No order buttons are ever clicked; nothing is sent to TopstepX.

## Done 2026-11-09
- Built as planned. Extra fixes found while testing: the price-tag detector treated dark navy backgrounds (TopstepX-like) as colored
  tags (now requires bright color too); header text split on dots ("MNQZ6.1m"); full-resolution change detection (a quiet market moves
  only a pixel or two, which a thumbnail misses); the monitor applies the browser-tab privacy guard; pipeline option `check_unvalidated`
  runs risk/cost/entry checks for unvalidated setups without ever approving them.
- Tests: 17 new (synthetic screenshots), full suite passes on 3.11 and 3.13; setup and monitor screens checked in Chrome.
- Not done: real TopstepX screenshots, Windows capture run.

## Edge stage (0.10.0, 2026-11-09)
- Stage 1, Edge capture source: `screen/capture_sources.py` (Windows Graphics Capture via `windows-capture`, PrintWindow, screen region;
  frame checks; pinned method; capture health), Edge-first window list, region preview of the live capture.
- Stage 2, calibration: source classes renamed to DIRECTLY_READ / CALCULATED_FROM_CALIBRATION / VISUALLY_ESTIMATED / UNAVAILABLE;
  manual calibration invalidated by zoom/rescale/pan (labels disagree) or resize (size differs), pausing analysis until recalibrated.
- Stage 3, market read: bias, structure, swings, BOS/CHoCH, VWAP position, EMA alignment, session levels when visible, volume, S/R,
  FVGs, sweeps (all VISUALLY_ESTIMATED); targets list.
- Stage 4, Live Visual Monitor page: window, live preview, capture time and health, last successful observation, confidence, bias,
  recommendation, entry/stop/targets, reasoning, invalidation, Recalibrate.
- Stage 5, tests and docs: 8 new tests; 395 pass on 3.11 and 3.13.
