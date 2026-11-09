# Visual Market Monitor: using your TopstepX chart as the input (0.9.0)

Study Terminal watches the TopstepX chart already on your Windows screen, reads it, analyzes it with the existing futures
engine and alerts you when a setup develops. No paid data subscription. It uses ordinary window capture only: no private
TopstepX endpoints, no login tokens, no browser storage, and it never clicks, types or places orders.

**Honest status:** the reader and the monitor were built and tested on Linux with **synthetic** chart screenshots (exact ground truth,
see "What was tested"). They have not yet seen a real TopstepX chart, and window capture has not been run on Windows by me. Your first
session is the real test: follow "Check it on your charts" below before relying on it.

## What it reads, and how much to trust each value

| Class | Meaning | Examples | Typical precision |
|---|---|---|---|
| **A · read from text** (VISUAL_OBSERVATION) | OCR of on-screen text | instrument, timeframe, the current-price tag, bid/ask if shown | exact when OCR is right; checked against the axis and tick grid |
| **B · calculated from the axis** (VISUAL_OBSERVATION) | pixel position converted with the calibrated price axis | visible horizontal lines | about 1 pixel (often 1–3 NQ ticks) |
| **C · visually estimated** (VISUALLY_ESTIMATED) | measured from colored pixels | candle open/high/low/close, VWAP/EMA lines, relative volume | 1–3 ticks on a normal zoom; worse when zoomed out |
| **D · unavailable** (UNREADABLE) | not on screen or not readable | anything you can't see: never guessed | none |

Every value carries a confidence and the capture time. Volume is relative bar height only (no contract counts). A line is called
"VWAP" or "EMA 20" only because you assigned its color. Candle times are calculated from the timeframe and the capture time.

## Chart status labels

| Label | Meaning | Recommendations |
|---|---|---|
| **SCREEN_CAPTURE** | fresh, readable capture of your chart | allowed (still through every check) |
| **STALE** | no good reading for 20 s, or the chart hasn't changed for 90 s while the market is open (frozen) | NO TRADE |
| **UNREADABLE** | capture worked but couldn't be trusted: blank, covered, layout changed, low confidence, browser on another tab | NO TRADE |
| **DISCONNECTED** | the chart window is closed or minimized | NO TRADE |

Screen data is never described as an exchange feed. It's a visual observation of what TopstepX displays, with a capture time.

## Recommendations

LONG / SHORT / WAIT / EXIT / NO TRADE, each with contract, direction, observed price, entry zone, stop, target 1 (1R), target 2,
R:R, setup, supporting evidence (the checks it passed), invalidation, timeframe, data confidence and capture time.

- **NO TRADE** whenever the chart is frozen, stale, covered, the instrument or price is uncertain, fewer than 30 candles are readable,
  candle bodies aren't readable, or the layout changed. The reason is always shown.
- Otherwise the existing 13-step decision pipeline runs on the visible candles, with the existing risk engine and your account limits.
- **LONG / SHORT** require a strategy that passed walk-forward validation (same rule as everywhere else in Study Terminal). None has yet.
  Until then, a complete setup that passes the risk engine is shown as **WAIT, potential LONG/SHORT setup**, with the full plan, and
  you get an alert. This is deliberate: it's a setup the app can describe, not one with a proven edge.
- **EXIT** when the price read from the chart text reaches the stop or target 2 of an active LONG/SHORT.

Alerts (Windows notifications, de-duplicated so each event alerts once): potential LONG/SHORT setup, entry confirmation, setup invalid,
stop/target reached, chart stopped updating, recognition confidence fell, chart window disappeared.

## Windows instructions

### 1. Update Study Terminal
1. Unzip the new version over a fresh folder, e.g. `C:\Users\<you>\Downloads\study-terminal-0.9.0\study-terminal`.
2. PowerShell in that folder:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
   powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1
   ```
3. Run `dist-installer\StudyTerminal-Setup-0.9.0.exe`. Your data (journal, profiles, settings) is kept.

### 2. Prepare the TopstepX chart
- Open TopstepX (browser tab or app) and an **NQ, MNQ, ES or MES** chart.
- Show the **price axis with labels** on the right and make sure the **current-price tag** is visible on it.
- Keep the **symbol and timeframe visible** in the chart's header/legend (or set them in the profile).
- Turn on the **volume pane** under the price chart if you want volume.
- Zoom so **40–150 candles** are visible and candles are **at least 4 pixels wide**.
- If you use VWAP and EMAs, give each line a **distinct color** that isn't the candle color.
- Don't minimize the window. Overlapping windows are usually fine (capture reads the window itself), but if Study Terminal says the chart
  is covered, move the other window away.
- In a browser, keep the TopstepX tab in front. If you switch the window to another tab, nothing is captured (privacy guard).

### 3. Select your chart in Study Terminal
1. Menu > **Visual Monitor** > **Set up a chart**.
2. **Pick the TopstepX window** from the list (windows with "TopstepX" in the title are starred). A preview appears. It's shown only on
   that page and never saved.
3. **Drag a rectangle** on the preview around one chart: include the header (symbol/timeframe), the candles, the price axis with its
   labels and price tag, and the volume pane. Fine-tune with the x/y/width/height boxes.
4. Move the **"Volume pane starts at"** slider so the dashed blue line sits between the candles and the volume bars.
5. Instrument and timeframe: leave **auto** if they're visible on the chart, or fix them (e.g. NQ, 5Min).
6. Price axis: leave **automatic** (reads the axis labels; works when the chart auto-scales). Use **Calibrate manually** only for a
   chart with a fixed scale: click two gridlines and type their prices.
7. Colors: candle colors are detected automatically. To read VWAP/EMAs, click **VWAP line** (or EMA 9/20/50/200) and then click on
   that line in the preview.
8. Click **Test read**. Compare instrument, timeframe, price and candle count with your chart; small colored marks under the region
   show the candles it found. Fix the region or colors if something's off.
9. **Save profile**. Save separate profiles for different layouts (e.g. "NQ 5m" and "NQ 15m"); a 15-minute profile of the same
   product is used automatically as the higher-timeframe check.

### 4. Start continuous monitoring
1. **Visual Monitor** > **Monitor** > **Start monitoring**.
2. Each chart shows its status label, what was read (with A/B/C/D classes and confidence), the current recommendation and a history.
3. **Pause** / **Resume** / **Stop** at the top. Monitoring runs in the background: you can leave the page or close the window to the tray
   (Ctrl+Alt+S brings it back). If monitoring was running when you quit, it starts again with the app.
4. Change how often it captures in the profile (default every 2 s).

### 5. Check it on your charts (accuracy calibration)
Synthetic tests prove the logic, not accuracy on TopstepX. Measure it:
1. Take a screenshot of the TopstepX window (`Win + Shift + S`, or `Alt + PrtScn`) and save it.
2. **Live copilot** > **Calibrate screen reading** > Open. Upload it, choose your chart profile, type what's really on it: contract,
   timeframe, last price, and the **open/high/low/close of the last completed candle** (hover it in TopstepX).
3. Leave "Keep this screenshot" off unless you want to re-score it after updates. Don't tick "generated test chart".
4. After about 20 screenshots per layout, the report shows accuracy per field with a 95% range and the failures.

## Limitations
- Pixel precision limits candle values (class C). Exact prices come only from text (the price tag).
- Only what's on screen exists: previous-day levels, overnight levels, opening range and session VWAP need that part of the session
  visible (or the VWAP line's color assigned); otherwise they're unavailable, not estimated.
- Indicator identification depends on the colors you assign. Two lines with similar colors can't be told apart.
- Candle colors that change with a theme, heikin-ashi or hollow candles, or wicks in a different color than bodies reduce accuracy.
  Use solid candles with same-color wicks.
- Some GPU-rendered browser windows capture black unless visible on screen; the app then reports UNREADABLE.
- No real TopstepX screenshots were available while building this, and Windows capture wasn't run by me.

## What was tested (automated, Linux)
`backend/tests/test_visual_monitor.py`: 17 tests on four **synthetic** recorded screenshots (`tests/fixtures/visual`, ground truth in
the JSON files): window/profile selection and matching, region and profile validation, OCR of instrument/timeframe/price/bid/ask, auto
and manual axis calibration including a rescaled-chart mismatch, candles within 2 ticks of truth (lines drawn under and over candles),
relative volume, VWAP/EMA lines, unreadable price, instrument conflict, zoomed-out low confidence, blank capture, session-aware candle
times, removal of levels that need unseen history, missing/minimized windows, capture failure, covered window, layout change by window
size and by axis position, frozen chart, duplicate alerts, browser-tab privacy guard, risk-engine integration and the evidence rule,
EXIT, the API, and the calibration workflow with candle fields. Plus a browser check of the setup and monitor screens.
