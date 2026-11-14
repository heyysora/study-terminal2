# Study Terminal post-feature audit (0.13.2 audited, fixes in 0.13.3; 2026-11-13)

Purpose: establish exactly what works, what doesn't, and what you can rely on. Nothing is marked complete unless there is
evidence for it. "Tested" below always says **what kind** of test: unit/integration tests on Linux, the same tests on a GitHub
Windows machine, or real use on your PC with your TopstepX chart. Passing tests is not proof that something works in real use.

How this audit was done: reading the code and docs, running the full test suite (485 tests after the fixes below; Python 3.11
and 3.13 on Linux, and on a GitHub-hosted Windows Server machine), the new safety tests (`tests/test_safety_audit.py`), and the
new Windows reliability job (`scripts/windows-reliability.ps1`). Nobody has used this version on your PC or against your real
TopstepX chart.

## Found and fixed during this audit

| # | Problem | Fix (0.13.3) | Evidence |
|---|---|---|---|
| X1 | **Wrong market could pass as "Working".** The OCR version the Windows app ships (rapidocr 1.2.3) reads the "·" in a TopstepX chart title as ":" ("ESZ6:5m:CME"). The reader didn't split on ":", so it saw no market name, then quietly used the profile's own setting (MNQ) at 0.8 confidence. Result: an ES chart under an MNQ profile was reported HEALTHY and could have produced ideas with ES prices. Only showed up in the Python 3.13 run, which uses the same OCR version as Windows. | The title is also split on ":", keeping only pieces with a letter (so "10:15" is never read as a 15-minute timeframe). The wrong-market check now works on both OCR versions. | test_watchdog.py (wrong market, colon titles, clock times) on rapidocr 1.2.3 and 1.4.4 |
| X2 | **Fail-open default.** Whenever the chart's title couldn't be read for any reason, the profile's market and timeframe were assumed at 0.8 confidence, which passes the 0.6 an idea needs. | Now marked "profile setting, not confirmed by the chart" at 0.5: no trade ideas, the watchdog shows "I can't see the market name on the chart" and suspends ideas. Stricter, not looser. | test_watchdog.py (`test_chart_title_not_visible_means_no_ideas`) |
| X3 | The Windows upgrade check failed on two files that are meant to change: `installed_build.txt` (records the new version) and Yahoo's download cache. | Those two are listed as expected changes in the result, not hidden. Every other file must still be byte-identical; a tampered user file still fails the check (verified). | Windows run 43525788935 output re-checked |

---

## Phase 1: findings

Severity: **High** = can mislead you or make a feature useless in your setup. **Medium** = wrong or confusing in some cases.
**Low** = cosmetic or documentation.

### 1.1 Implemented but not fully functional in your setup (free data, no TopstepX API)

| # | Area | Finding | Severity |
|---|---|---|---|
| F1 | Futures practice orders | The futures practice account only fills orders on live data feeds (`TRADABLE = realtime, near_realtime, polling`). With free data you only have Yahoo (delayed) and the screen-read chart (`screen_capture`), and neither is accepted. So practice futures orders are **refused** unless you turn on "Practice on delayed prices" (fills are then labelled delayed and won't match the live market). The live price read from your TopstepX chart cannot fill practice orders. | High |
| F2 | Automation Center (futures) | Its decisions run on the futures data feed, which is Yahoo delayed data in your setup. Every decision is therefore "No decisions on delayed data". The "app places practice trades for me" mode will never place a trade in your setup. The Visual Monitor's suggestions are separate and are not fed into it. | High |
| F3 | Live Market screen | Needs the paid TopstepX API (about $29/month). Off by default; untested with a real account. Without it the screen has no live data. | Medium |
| F4 | Multi-timeframe check in Visual Monitor | The 15-minute check only works if you set up a second chart profile with a 15-minute TopstepX chart. With one chart there is no higher-timeframe check at all (the setup isn't refused for it either). | Medium |
| F5 | VWAP / EMAs from the screen | Only read if you assign each line's color in chart settings; otherwise "not available". VWAP is never computed from the picture unless the session open is visible. | Medium |
| F6 | Candle times | Candle times are calculated from the timeframe and capture time; the chart's time axis is not read. A candle can be assigned to the wrong minute after gaps or session breaks. | Medium |
| F7 | Trust & Validation paper-trading evidence | Requires completed practice trades filled on live data. Because of F1, this category can't progress with free data. | Medium |

### 1.2 Duplicate or conflicting functionality

| # | Finding |
|---|---|
| D1 | Two screen readers: **Live copilot** (older, screenshot/mss capture, stock-oriented fusion) and **Live Visual Monitor** (Edge/Windows Graphics Capture, futures, watchdog). They can run at the same time and report differently. The Visual Monitor is the one to use for TopstepX. |
| D2 | Two calibration paths: "Calibrate screen reading" in Live copilot (uploaded screenshots, feeds Trust & Validation) and the new **Chart check** (live chart, guided). Results are stored separately. |
| D3 | Four chart screens (Chart, Live copilot, Live Market, Live Visual Monitor) and three on/off switches for watching (copilot, Automation Center, Visual Monitor). Simple mode hides most of this; Advanced shows all of it. |
| D4 | Two "is it working" systems: the stock market-data health (Yahoo) and the new reliability watchdog (charts). Home combines them depending on Stocks/Futures. |
| D5 | Two practice accounts for futures (practice and research sandbox) plus replay and the stock account. Their results are kept separate (good), but four balances exist. |

### 1.3 Incomplete integrations

| # | Integration | State |
|---|---|---|
| I1 | TopstepX API (ProjectX), read-only market data and account balances | Built from public docs; **never tested against a real account**. Paid. |
| I2 | TopstepX SignalR market stream | Built; tested only against a local mock server. Paid API required. |
| I3 | Chrome extension (sends the active TradingView symbol) | Built; not tested in a real Chrome install for this audit. Not related to TopstepX. |
| I4 | Mobile companion page | Local network only; not tested on a real phone for this audit. |
| I5 | Optional AI: local Ollama (free) | Code path tested with a fake server only. |
| I6 | Optional AI: Anthropic API | **Paid if you use it.** Off unless you add your own key; nothing requires it. Flagged because the project rule is $0 to operate. |
| I7 | Economic calendar | Uses the free BLS release schedule and public Fed/BEA calendars. Coverage beyond BLS releases has not been checked against an official full calendar. |

### 1.4 Calculations to be aware of

| # | Calculation | Issue | Severity |
|---|---|---|---|
| C1 | Futures "change" on Home and My chart | Measured from the first price read after 6 PM New York (or from when watching started). Not the exchange's settlement-based daily change, and not the 9:30 AM open many day traders use. Labelled on screen. | Medium |
| C2 | Accuracy intervals on Trust & Validation | Wilson intervals assume each sample is independent. Screenshots taken minutes apart on the same chart are correlated, so the intervals are narrower than they should be. Counting by session would be more honest. | Medium |
| C3 | Strategy cost-sensitivity table (Futures > Evidence) | Computed over **all dates with the final parameters**, including the period the parameters were chosen on. Its "promising" labels are therefore not out-of-sample evidence. The screen says "(all dates)", but the tier words can still mislead. | High |
| C4 | NQ and MNQ research | Same underlying price series. They are not two independent confirmations; the same goes for ES and MES. | Medium |
| C5 | Live price | Read about twice a second from the price box; moves between reads are not seen; same price within 1 s is stored once. Accurate as a reading of the screen (0 wrong in 300 synthetic frames), not tick data. | Low (documented) |
| C6 | Risk audit "loss above 1.25x the per-trade limit" | A heuristic allowance for slippage, not a TopstepX rule. | Low |
| C7 | Stock "how much could I lose today" | daily loss limit + today's losses so far. Correct. Checked by test. | — |

### 1.5 Error handling

| # | Situation | Handling | Evidence |
|---|---|---|---|
| E1 | One part of Home fails | Home still loads and says to restart | test_home.py |
| E2 | Chart reading loop dies | Watchdog restarts it, logs and reports it | test_watchdog.py |
| E3 | App killed or crashed | Next start reports "didn't close normally" | test_watchdog.py; Windows job |
| E4 | Backup can't be written | Start-up continues; Home shows it; next start retries | test_backup.py |
| E5 | Yahoo down | Last data served, labelled CACHED, never "live" | test_futures_p2_data.py |
| E6 | Damaged database file | **Not handled.** App won't start, technical error only; file kept. See Phase 5. | Windows job |
| E7 | Data folder on a full or read-only disk | Not tested. | — |
| E8 | Edge/TopstepX layout changes after a TopstepX update | Detected as layout change → "Check chart settings"; reading stops rather than guessing. Only tested on synthetic layouts. | test_visual_monitor.py |

### 1.6 Works only with synthetic or simulated data so far

Everything that reads your screen: contract/timeframe/price/candle/indicator recognition, the live price, frozen-chart
detection, layout/zoom detection, tab-switch privacy guard (by window title), Windows Graphics Capture on a real Edge window, the
watchdog's detection of real failures, and the Chart check itself. The research uses real (Yahoo) historical futures data; the
practice simulator uses real stock prices but simulated fills.

### 1.7 Claims that have not been verified

- "Reads your TopstepX chart": unverified on a real TopstepX chart (Phase 2 provides the way to verify it).
- "Windows Graphics Capture available": the Windows job only proves the library loads; it has never captured a real Edge window.
- Topstep rule presets: taken from Topstep's help pages on 2026-11-07/08 and marked unconfirmed until you confirm them.
- Any strategy edge: none is validated (Phase 4).
- 0.13.x screens on your PC: not seen on your PC by anyone but you.

### 1.8 Not built (asked for in the 0.12.0 brief)

Multi-timeframe analysis across 1m/5m/15m/1h/4h, a separate NO TRADE engine layer (the decision pipeline and quality gates do
this job today), trade quality scores, the fuller journal (chart snapshots, plan history), the performance dashboard with
separated result sources, the strategy lab interface, replay of recorded screen sessions, calendar improvements, the AI mentor
improvements, a single trading profile, desktop extras (layouts, annotations, export center), and `docs/COST_AUDIT.md`.

---

## Phase 2: real-chart validation

Built: the **Chart check** screen and `docs/REAL_CHART_TESTING.md`. Thirteen checks: contract, timeframe, live price, price
scale, candles, indicators, resizing, zooming, tab switching, minimizing, frozen chart, closing/reopening TopstepX, restarting.
Each result records what was read and **how** (read directly / worked out from the price scale / estimated from the picture /
not available), the time, the version, the capture method, and pictures for price checks. Results from test sources are stored
but never counted. Results so far: **none from a real TopstepX chart.**

## Phase 3: trading safety audit

| Claim | Result | Evidence |
|---|---|---|
| Practice mode is always visible | **Verified in code and tests**: the PRACTICE MODE badge is rendered by the app shell on every screen in both modes; the API reports practice mode for every setting combination | test_safety_audit.py (2 tests) |
| No real order execution exists | **Verified**: no broker order endpoint anywhere in the code (one documentation sentence in the live checklist excepted, by exact text); only six files can reach the network and none contains order-sending code; the TopstepX client refuses any non-read path before sending; the stream can only subscribe; no broker library is imported | test_safety_audit.py (5 tests) |
| Live trading can't be switched on | **Verified**: the "live" mode is refused; the lock is reported as on | test_safety_audit.py |
| Risk limits are enforced | **Verified by existing tests**: per-trade, daily, consecutive losses, position size (micros counted 10:1), max loss limit, reward-to-risk, stop required | test_futures_risk_paper.py, test_paper_engine.py, test_futures_automation.py |
| The NO TRADE logic is conservative | **Verified**: every outcome except APPROVED reads WAIT; unknown outcomes read WAIT; APPROVED is only reachable after the validation check, and no strategy is validated, so the app currently never approves a futures trade | test_safety_audit.py, test_plain.py |
| Stale or unreliable data can't produce an idea | **Verified**: stale, unreadable, disconnected, stopped, paused, low confidence, wrong market or timeframe → NO TRADE with no entry | test_safety_audit.py (6), test_watchdog.py |
| A chart can't be read as the wrong market | **Was failing on the shipped OCR version; fixed (X1, X2)** | test_watchdog.py |
| The watchdog detects failures | **Verified on simulated failures**: minimized, covered, other tab (nothing captured), frozen, wrong market, wrong timeframe, slow capture, fallback capture, price-box failures, scale drift, dead loop (restarted), unclean shutdown | test_watchdog.py (6 tests); real-chart checks pending |
| Restarting can't bypass safety | **Verified**: Stop everything stays on after a restart and automation can't simply be started; risk locks and personal limits survive restart; the live lock stays on | test_safety_audit.py (3 tests) |

No safety rule was weakened and no test was removed. Changed existing tests: the expected reason for a wrong-market chart (still
refused, the reason now names the market), and one futures data test pinned to a weekday market time because it failed when run
outside trading hours. Two rules were made stricter (audit X1, X2).

## Phase 4: strategy validation audit

### Method (what the research does)

| Item | Futures research (bundled run 2026-11-08) | Stock backtests (0.5.0 run 2026-11-07) |
|---|---|---|
| Data | Yahoo continuous futures, 5-minute bars, 49 trading days (2026-08-31 to 2026-11-06) | Yahoo, 20 large-cap stocks; 5/15-minute: 58 days; 1-hour: 720 days |
| Out-of-sample | Walk-forward: 3 folds (2-week train → 2-week test), only test windows reported | Walk-forward: train 20 sessions → test 5 (1-hour: 60 → 20) |
| Final holdout | Last 10 trading days (2026-10-27 to 2026-11-06), 14-20 trades per product. **Not pristine**: those bars were viewed in aggregate during 0.6.0 development (disclosed in the run) | None |
| Parameters | 4 combinations (target R, chase limit) chosen per fold | 12 combinations in the "optimized" variant; a "fixed" variant with no fitting |
| Costs | Fees per round turn (NQ/ES $3.78, MNQ/MES $1.22), 1 tick slippage per side, a stop and target in the same bar counts as the stop, targets need one tick of trade-through | 1 bp/1¢ slippage per fill, stops gap-filled at the worse price, no commission |
| Uncertainty | 95% interval by day-clustered bootstrap (trades on the same day move together); Wilson for win rate | Same |
| Market conditions | One 10-week period; no split by trend/range/volatility regime | 1-hour study covers 21 months; 5/15-minute one 21-day period |

### Problems with the method

1. **Too little data.** 42-81 out-of-sample futures trades per product across all setups; 0-27 per individual setup. That is
   far below what's needed to tell a real edge from luck (roughly 100+ trades per setup, over several months).
2. **One market period.** All futures results come from September to early November 2026. Nothing shows how any setup behaves in
   other conditions.
3. **Holdout not fully unseen** (disclosed). Only data after 2026-11-08 is genuinely unseen.
4. **Cost table uses all dates** (finding C3), so its "promising" labels are not out-of-sample.
5. **NQ/MNQ and ES/MES aren't independent** (finding C4).
6. **Survivorship bias** in the stock universe (today's large caps).
7. Yahoo continuous futures data is unofficial, can have gaps and roll jumps, and volume is approximate.

### Status of every strategy

"Inconclusive" means the 95% interval includes zero: it can't be told apart from luck.

| Strategy (futures, out-of-sample) | NQ | MNQ | ES | MES | Status |
|---|---|---|---|---|---|
| Liquidity sweep reversal, long | 13 trades, +0.93R | 12, +1.06R | 24, −0.07R | 27, −0.05R | **Inconclusive** on NQ/MNQ (few trades), **losing** on ES/MES |
| Liquidity sweep reversal, short | 16, −0.01R | 11, −0.23R | 23, +0.11R | 23, +0.10R | **Inconclusive** |
| Opening range retest, long | 3, −0.02R | 3, −0.05R | 5, +0.01R | 5, −0.19R | **Untested in practice** (too few trades) |
| Opening range retest, short | 6, −0.71R | 4, −1.02R | 5, −0.58R | 8, −0.17R | **Losing** (small samples, consistently negative) |
| Initial balance breakout, long/short | 0-1 trades | — | — | 0-1 | **Untested** (almost never triggered) |
| VWAP reclaim, long/short | — | 2, −1.01R (short) | 1, −1.02R | 2, −0.59R | **Untested** (too few trades) |
| Trend pullback, long | 3, −0.01R | 5, +1.38R | 6, −0.43R | 9, +0.02R | **Untested / inconclusive** |
| Trend pullback, short | 8, +1.01R | 5, +1.37R | 4, +0.24R | 6, −0.25R | **Untested / inconclusive** |
| **All setups combined** | 50 trades, +0.29R, interval −0.24 to +0.84 | 42, +0.42R, −0.07 to +0.86 | 68, −0.07R, −0.35 to +0.22 | 81, −0.03R, −0.27 to +0.21 | NQ/MNQ **inconclusive**, ES/MES **losing** |

| Stock studies (out-of-sample, after costs) | Trades | Avg R | 95% interval | Status |
|---|---|---|---|---|
| 5-minute, fixed / optimized | 843 / 792 | −0.03 / −0.06 | −0.12 to +0.07 / −0.18 to +0.07 | **Losing** |
| 15-minute, fixed / optimized | 446 / 431 | +0.00 / +0.02 | −0.14 to +0.15 / −0.10 to +0.15 | **Inconclusive** |
| 1-hour, fixed / optimized | 2,796 / 2,794 | −0.03 / −0.02 | −0.07 to +0.02 / −0.05 to +0.02 | **Losing** (strongest evidence: 21 months) |

**Validated strategies: none.** The registry marks every futures setup "experimental". Nothing here shows Study Terminal can
make money. The app already treats every setup as watch-only (WAIT), which is the correct consequence.

What would be needed before any strategy could be called validated: at least several months of new, genuinely unseen data
(forward-collected after 2026-11-08), 100+ trades per setup, results split by market condition, the interval for average R
above zero after realistic costs, and the result repeated on a second period.

## Phase 5: Windows reliability

Run on a **GitHub-hosted Windows Server 2022 machine** (run 43525788935, 2026-11-13), not on your PC. It installs the real
installer the build produces, silently, as a normal user. Script: `scripts/windows-reliability.ps1`; full output is kept as the
`windows-reliability` artifact on each run.

| Check | Result | Detail |
|---|---|---|
| Fresh install | **PASS** | installed to `%LOCALAPPDATA%\Programs\Study Terminal`, exit 0 |
| Start-up and clean shutdown | **PASS** | self-test in 6.2 s: backend up, clean shutdown, live trading locked |
| Clean exit recorded | **PASS** | no "didn't close normally" marker left |
| Log file | **PASS** | start and stop lines written |
| No secrets in the log | **PASS** | fake API keys were planted for the run and searched for; not found |
| Uninstall removes the program | **PASS** | |
| Uninstall keeps your data | **PASS** | data folder untouched by a silent uninstall (the default answer is "keep") |
| Install previous release (0.13.1) and seed it with data | **PASS** | journal trades, practice accounts, settings, limits, chart profiles, calibration samples |
| Upgrade 0.13.1 → 0.13.2 over it | **PASS** | setup exit 0, new version starts |
| Automatic backup before the upgrade | **PASS** | backup database identical to the pre-upgrade database |
| Your data survives the upgrade | **FAIL → fixed in the check (X3)** | all 10 views identical, no unexpected row changes; the failure was the build marker and Yahoo cache changing, which they're meant to |
| Restore from the backup | **PASS** | restored copy starts; data as before |
| Installer rollback after a failed setup | **PASS** | a deliberately failing setup was used; the previous program was restored byte-for-byte and the half-installed file removed |
| Damaged database file | **OBSERVED: not handled** | the app refuses to start (exit 1) with a technical error in the log; the damaged file is left in place, not deleted or overwritten. There is no plain message and no offer to restore from the backup. You would have to restore by hand from `%LOCALAPPDATA%\StudyTerminal\backups`. |

Not tested on Windows: your PC; Windows 10/11 desktop editions; a non-admin account with a different user profile path; a full
or read-only disk; antivirus interference; the installer's dependency auto-install via winget (the GitHub machine already has
the tools); journal persistence over real days of use; Edge capture of a real window.
