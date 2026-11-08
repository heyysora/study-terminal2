# Study Terminal: Codebase Audit (Stage 10 → 0.5.0)

Audit date: 2026-11-07. Scope: every backend module, the React UI, the desktop launcher,
scripts, tests and docs as they stood after Stage 10 (baseline commit `63f9e45`, 106 tests passing).
The second half of this file lists defects found **later in this release**, mostly by running the
code against real data (real Yahoo history, real TradingView screenshots). Several of them were
invisible to the unit tests that existed at the time, which is the point of testing on real data.

How it was done: each module was read in full, the test suite was run on Python 3.13 and 3.11,
a linter (ruff: pyflakes + bugbear) was run, and the request paths were traced end to end
(provider → monitor → freshness → analysis → signals → alerts → UI, and order → simulator → store).
"Status" says what happened to each finding in this release.

Severity scale:
- **Critical** — can cause harm to the user (privacy, unwanted actions) or silently wrong decisions.
- **High** — wrong numbers, misleading claims, or lost data in normal use.
- **Medium** — wrong in edge cases, slow, or missing a required safeguard.
- **Low** — cosmetic, cleanup, or very unlikely.

---

## Critical

| ID | Area | Finding | Status |
|----|------|---------|--------|
| C1 | API security | **Cross-site requests and DNS rebinding.** The local API had no check on who was calling it. Any web page open in your browser could send a plain form POST to `http://127.0.0.1:8765` and trigger endpoints that take no JSON body: close a paper position (`/paper/positions/X/close?confirm=true`), pause market monitoring (silencing alerts), resume a paused screen capture, mark alerts read. Separately, the `Host` header was not validated, so a DNS-rebinding page could read every API response (including what the screen copilot read off your screen), and the WebSocket "same-origin" check trusted that same `Host` header. | **Fixed.** Host header restricted to `127.0.0.1`/`localhost`; every state-changing request must carry the `X-Study-Terminal` header (a cross-site page can't add it without a CORS preflight, which is refused); WebSocket checks Host and Origin. Tests added. |

## High

| ID | Area | Finding | Status |
|----|------|---------|--------|
| H1 | Signals | **Confidence not backed by enough evidence.** STRONG BUY needed only an average above +0.1R over ≥20 out-of-sample trades, with no uncertainty estimate and no check of the current market regime. Setups that *lost* money out-of-sample were still shown as POTENTIAL BUY, and setups never tested could reach BUY. | **Fixed (Phase 3).** Evidence tiers from sample size, day-clustered 95% intervals and fold consistency (`backtest/stats.py`). Only "reliable" evidence allows BUY/SHORT; everything else is watch-only and the overall answer is NO TRADE; clearly losing setups are NO TRADE outright; STRONG also needs a non-negative record in the current regime. |
| H2 | Screen privacy | **Analysis continued after the watched window changed content.** If you picked a browser window showing TradingView and then switched that window to another tab (email, bank), frames kept being captured and OCR'd. | **Fixed.** The window title is checked on every frame; when it stops looking like a chart and differs from what you consented to, analysis stops and nothing is read until a chart is back. |
| H3 | Desktop | **Unclean shutdown.** The backend ran in a daemon thread and the process exited immediately after asking it to stop, so final writes (pending bars, paper account state) could be cut off. No single-instance guard: a second launch reused the first backend in a confusing way. | **Fixed (Phase 8).** Backend runs in a non-daemon thread; Quit waits up to 30 s for the shutdown to finish; a named mutex keeps one instance and a second launch brings the first window forward. Clean shutdown verified by the packaged app's `--self-test` (Linux build); the mutex and window behaviour still need a Windows run (`scripts\verify-windows.ps1`). |
| H4 | Market data | **No validation of incoming bars.** Bars with `high < low`, zero or negative prices, or a single-print spike far outside the surrounding range flowed straight into indicators, signals and paper fills. | **Fixed (Phase 2).** Every bar is validated; bad bars are dropped and counted, spikes are flagged, and the counts are shown with the data. |
| H5 | Market data UI | **Source and timestamp not shown.** Quotes and charts showed a freshness meter but not where the data came from or when it was last updated, and chart data served from the app's cache wasn't labeled as cached. | **Fixed (Phase 2).** A new CACHED status; every quote and chart carries provider, source, last-update time and age, and the UI shows them. |

## Medium

| ID | Area | Finding | Status |
|----|------|---------|--------|
| M1 | Market data | No missing-candle detection: gaps in the 1-minute series during regular hours went unnoticed. | **Fixed (Phase 2).** Gaps are counted per symbol and surfaced; liquid symbols with gaps get a warning. |
| M2 | Paper engine | `_fill` would flip a position (keeping the old average price) if an exit order were larger than the position. Upstream checks prevent this today, but the fill path wasn't safe on its own. | **Fixed.** Over-sized exits now close the position and open the remainder at the fill price; test added. |
| M3 | Paper engine | Equity and unrealized P&L use each position's last mark with no indication of how old the mark is. | **Fixed.** Account summary reports the oldest mark age and flags stale marks. |
| M4 | Paper engine | The consecutive-loss counter counted each partial exit as a separate losing trade. | **Fixed.** Counted per round-trip trade (via the journal's trade grouping). |
| M5 | Backtest | Calibration was keyed by setup and timeframe only. Long vs short and market regime were mixed together. | **Fixed (Phase 3).** Stored per setup, direction and timeframe, with a per-regime breakdown. Older records are read conservatively (never "reliable"). |
| M6 | Backtest | Daily-loss and consecutive-loss limits apply per symbol (each symbol has its own simulated account), not portfolio-wide. | **Documented** in BACKTEST_RESULTS.md. Not changed: per-symbol accounts keep each test independent. |
| M7 | Performance | Each signal cycle can fetch up to four frames per symbol from Yahoo. With 40 symbols that's ~160 requests against a 60/minute throttle, so a cycle can take minutes and signals lag. | **Improved.** SPY context and higher timeframes are reused within a cycle, and cycle duration is reported so lag is visible. |
| M8 | Config | Optional API key read only from `.env` in the project folder; an installed copy had no place for it. | **Fixed (Phase 8).** Also read from `%LOCALAPPDATA%\StudyTerminal\.env` (shown in Settings > About and files). |
| M9 | Signals | Position-management alerts and signal alerts could repeat after app restart (dedupe state is in memory). | **Open.** Alert history is persisted; in-memory dedupe resets on restart. Low impact. |

## Low

| ID | Area | Finding | Status |
|----|------|---------|--------|
| L1 | Code | Unused imports (routes, education), `zip()` without `strict`, unused variable in market clock. | Fixed. |
| L2 | Paper engine | A buy limit placed above the market fills at the limit, not at the (better) market price. Pessimistic, so it never flatters results. | Documented, not changed. |
| L3 | Signals | `lifecycle()` "triggered then stopped" doesn't require the stop to be hit after the trigger. Invalidation usually fires first, so impact is small. | Fixed. |
| L4 | Docs | Version numbers disagreed (pyproject 0.1.0, API 0.3.0). | Fixed: 0.4.0 everywhere. |

## Things that work in tests but may fail in real use

These aren't bugs I can fix from here; they're the honest list of what tests can't prove.

- **Yahoo can change or block its unofficial endpoints** at any time. The app degrades to "no data" labels and disables signals; it doesn't invent data. Watch the status strip.
- **The Yahoo stream during US market hours** was never observed from this build environment (it was the weekend). Crypto ticks were verified.
- **Windows-only code** (window capture, tray, toasts, WebView2, hotkey, installer) can only be proven on Windows. See `docs/WINDOWS_VERIFICATION.md`.
- **OCR on real trading platforms** depends on fonts, themes and layouts. Accuracy numbers are in `docs/SCREEN_VALIDATION.md` and only cover what was actually tested (TradingView; not Webull, thinkorswim or IBKR).
- **Rate limiting**: Yahoo's limits are undocumented. The app throttles to 60 requests/minute and backs off on 429s, but heavy watchlists can still be throttled.

## Claims the data or testing can't support (and what was done)

| Claim (where) | Problem | Change |
|---|---|---|
| BUY / STRONG BUY wording on untested setups | No measured edge behind it | Untested setups cap at POTENTIAL/WAIT with "untested" shown. |
| "Model estimate: X% chance of profit" | Only valid if the model passed its deployment gate on enough data | Unchanged (it already refuses to show without a deployed model); wording now says "estimate" and shows its test sample. |
| SPY "high-risk conditions" | Thresholds (−1.5%, range > 12 ATR) are rules of thumb, not measured | Labeled as a heuristic in the UI. |
| Setup quality score | A checklist count, not a probability | Already labeled; unchanged. |

---

## Defects found later in this release (Phases 2–9)

| ID | Sev. | Area | Finding | How it was found | Status |
|----|------|------|---------|------------------|--------|
| H6 | High | Backtest | **Hourly and 4-hour bars "ended" after the close.** Yahoo's last hourly bar starts 15:30, so the simulator treated it as ending 16:29:59. The end-of-day flatten cancelled the bracket stop/target, then its market order couldn't fill after the close, so positions were carried for weeks with no stop and no target. Every hourly/4-hour backtest before this was invalid. | A real 2-year hourly run showed +20R trades held 4 weeks | **Fixed.** A bar's end is capped at that day's exchange close; the flatten now raises an error instead of silently carrying a position. Regression test with Yahoo-shaped hourly bars. |
| H7 | High | Analysis | **Early-close days treated after-hours as regular session.** The regular session was defined as 09:30–16:00 by the clock, so on days the exchange closes at 13:00 (day after Thanksgiving, Christmas Eve) the 13:00–16:00 after-hours bars fed VWAP, levels, signals, 4-hour bars, missing-candle counts and backtests. | The H6 safety check fired on 2024-11-29 | **Fixed.** Every session boundary now comes from the exchange calendar (`regular_close_minute`). Test added. |
| H8 | High | Backtest | **Same-bar stop filled at the bar's close.** When the entry and the stop were both inside one bar, the re-check passed no open price, so the stop filled at the close (as if price had gapped past it). On 5-minute bars this cost cents; on hourly bars it turned 1R losses into 2–3R losses. | Synthetic hourly test showed −3.4R losses | **Fixed.** Price moved continuously from entry to stop inside the bar, so the stop fills at the stop (+ slippage). |
| H9 | High | Screen | **Price axis assumed at the right edge.** On real TradingView the watchlist sits to the right of the axis, so the app read watchlist cells and reported confidently wrong prices (6 of 24 screenshots) and failed to fit the axis on 22 of 24. | First run on real TradingView screenshots | **Fixed.** The axis is found as whichever column of labels fits one straight price line; the price tag must sit in that column and agree with the axis. |
| H10 | High | Screen | **Crash on OCR'd circled digits.** `str.isdigit()` accepts '①', `int()` doesn't: the screen copilot crashed on an ordinary TradingView screen. | Real TradingView screenshot | **Fixed.** ASCII digits only; regression test. |
| M10 | Med | Screen | Several timeframe buttons in a toolbar: the first one was taken. Single-letter OCR noise ('Q' from a search icon) was taken as the ticker (9 of 20 held-out screenshots). | Held-out real screenshots | **Fixed.** Legend timeframe preferred, ambiguity reported as unknown; single letters ranked last and OCR tickers confirmed by matching the on-screen price against market data. |
| M11 | Med | Mentor | "Am I chasing this?" and "Which strategies performed best?" fell through to a generic chart explanation (`\bchas\b` never matched "chasing"). | New intent tests | **Fixed.** |
| M12 | Med | Diagnostics | Target exits were counted under the wrong name (`target` vs `take_profit`), so the diagnostics reported 0% target exits; the test that should have caught it never exercised that branch. | Real walk-forward output | **Fixed**, and the test now asserts both branches actually ran. |
| M13 | Med | Extension | The extension sent the tab title before TradingView added the price, then de-duplicated the update away. | End-to-end test in real Chrome | **Fixed.** Re-sends when the price appears; refreshes at most every 30 s. |
| M14 | Med | ML | Model selection used the test set: the best of three model types was picked by its test score and then judged on that same test set. The deployment gate also had no uncertainty check. | A marginal pass on real 15-minute trades | **Fixed.** Model type chosen on a validation slice of the training period; gate also requires the day-clustered 95% interval of Brier skill to be above zero (added after seeing the marginal pass; disclosed in BACKTEST_RESULTS.md). |
| L5 | Low | Desktop | Logging call with an argument but no placeholder in the new shutdown code. | Frozen self-test output | Fixed. |
| L6 | Low | Desktop | Quitting within ~1 s of launch logs a harmless `websockets` library error while the stream is still connecting. | Frozen self-test output | Open (cosmetic). |

### Summary
- Critical: 1 found, 1 fixed. High: 10 found (H1–H5 in the Stage 10 audit, H6–H10 later), all fixed; the Windows-specific parts of H3 are written but not yet verified on Windows. Medium: 14 found, 12 fixed, 1 documented (M6), 1 open (M9). Low: 6 found, 5 fixed or documented, 1 open (L6).
- The earlier Stage 10 backtest headline (−0.11R per trade on 274 trades) was produced before H6–H8 and M12 were fixed and is superseded by `docs/BACKTEST_RESULTS.md`.
