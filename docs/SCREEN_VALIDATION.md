# Screen copilot: real-world validation

Date: 2026-11-07. Code: `backend/app/screen/vision.py` (pixels → ticker, timeframe, price, axis) and
`backend/app/screen/service.py` (cross-check against market data). Harness: `backend/research/screen_eval.py`.

## What was tested, and what wasn't

| Platform | Tested? | How |
|---|---|---|
| **TradingView** (web, logged out, default light theme) | Yes, 46 real screenshots | Chart pages of tradingview.com rendered in Chrome at 6 window sizes (1280×720 @150% … 2560×1440 @150%), 1-minute to daily, 30 symbols |
| **TradingView Advanced Chart widget** (official embed, dark theme) | Yes, 14 real screenshots | TradingView's own embeddable chart, delayed Cboe One data |
| TradingView logged-in layouts, custom themes, multiple panes, indicators | **No** | Needs your account. Your layouts will differ |
| **Webull, thinkorswim, Interactive Brokers** | **No** | Desktop apps behind a login. No screenshots were available, so **no accuracy claim is made**. They fall back to the generic reader; expect to tune |

Screenshots of TradingView aren't included in the download (they're TradingView's interface). The capture
script that produced them is described below, so the test can be re-run.

## Method

Three sets, used in this order:

1. **Development set** (24 shots): used to find and fix failures.
2. **Held-out set** (20 shots: 12 site + 8 dark widget): first scored blind, then used to fix two more
   failure types. From then on it no longer counts as blind.
3. **Blind set** (16 shots: 10 site + 6 dark widget, new symbols, sizes and intervals): captured after the
   last code change and scored **once**. This is the number to quote.

Each image is analyzed twice: from **pixels only**, and **with the window title** the app sees on Windows
(for TradingView in Chrome, e.g. `AAPL 342.37 ▼ −0.52% - Google Chrome`). Each field is scored correct,
**unknown** (the app said it couldn't read it: honest) or **WRONG** (it gave a confident wrong answer: the
failure that matters). Price counts as correct within 0.3% of the true price.

## Results

### Blind set (final code, scored once)

| Field | Pixels only | With window title |
|---|---|---|
| Ticker | 16/16 | 10/10 |
| Timeframe | 15/16 (1 unknown) | 10/10 |
| Visible price | 13/16 (3 unknown) | 9/10 (1 unknown) |
| Price axis fitted | 14/16 (2 unknown) | 9/10 (1 unknown) |
| **Confidently wrong, any field** | **0** | **0** |

The misses: one 2560×1440 @150% capture (3200×1800 px) where the price tag wasn't found; one site capture
whose page hadn't finished loading (no axis, no price in the title: correctly reported as unreadable); one
dark widget at 1-hour where the axis and timeframe weren't read.

### How it got there (same code path, earlier versions)

| Set | Version | Ticker | Timeframe | Price | Axis | WRONG |
|---|---|---|---|---|---|---|
| Development (24, pixels) | Stage 10 code | 24/24 | 23/24 | **0/24** | 2/24 | **6** (prices from the watchlist) |
| Development (24, pixels) | after axis fix | 24/24 | 24/24 | 23/24 | 24/24 | 0 |
| Held-out (20, pixels), first blind run | after axis fix | **11/20** | 17/20 | 18/20 | 20/20 | **13** |
| Held-out (20, pixels) | final | 20/20 | 19/20 | 18/20 | 20/20 | 0 |
| **Blind (16, pixels)** | **final** | **16/16** | **15/16** | **13/16** | **14/16** | **0** |

Failures found and fixed (all general, none specific to one image):
- The price axis was assumed to be at the right edge. On TradingView the watchlist is there, so prices were read
  from watchlist cells. Now the axis is the column of labels that fits one straight price line.
- A colored box was accepted as the price tag even when it was a volume tag or touched a grid label. Now it must
  sit in the axis column, agree with the axis at its height, and be mostly filled with color.
- '①' from OCR crashed the reader.
- Timeframe: toolbars show several interval buttons. The one in the chart legend ("Apple Inc · 5 · NASDAQ") now
  wins, and if it's still ambiguous the timeframe is reported unknown.
- Ticker: a search icon read as 'Q' was taken as the symbol. Single letters now rank last, and an OCR'd ticker
  is confirmed only if its market price matches the price on screen (within 1%).

## What happens with the reading
- **Ticker**: from the window title (trusted) or OCR (confirmed against market data by price). If neither works:
  "I can't read a ticker on this screen reliably, so I won't guess."
- **Discrepancy**: if the screen price differs from market data by more than 0.5%, the app says so and uses market
  data only. Outside regular hours this is often just after-hours vs the 4 PM close (seen in testing: TradingView
  showed the close, Yahoo the after-hours price).
- **Drawn lines, candle colors, indicators, position text**: visual estimates, labeled as such. Not measured here.
- Speed: about 3–6 seconds per analyzed frame on this test machine's CPU. Frames are only analyzed when the screen
  changes.

## Testing your own platform (Webull, thinkorswim, IBKR, your TradingView layout)
1. Take screenshots of your charts (Win+Shift+S works). No login screens or account pages.
2. Name each one `platform_SYMBOL_interval_price.png`, e.g. `webull_AAPL_5m_342.37.png` (price = the real last price
   when you took it; leave it off if unknown).
3. Put them in one folder and run `.\scripts\screen-eval.ps1 C:\path\to\folder`.
4. You get the same table as above plus `screen_eval_results.json` in that folder. Nothing is uploaded.

## Reproducing the TradingView captures
Headless Chrome (puppeteer-core) opened `https://www.tradingview.com/chart/?symbol=EXCHANGE:SYMBOL&interval=N`
logged out, waited 14 s and saved a screenshot plus the page title. The dark set used TradingView's documented
embed widget (`s3.tradingview.com/tv.js`, `theme: "dark"`). Ground truth: symbol and interval from the request,
price from the page title (or Yahoo's close where the title had none).
