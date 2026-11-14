# Study Terminal readiness report (0.13.3, 2026-11-13)

What you can rely on today, and what you can't yet. Companion to `docs/POST_FEATURE_AUDIT.md`, which has the details and
the evidence.

## How to read the status

Each capability gets **one** status: the highest level of evidence it has actually reached. They are not combined. A higher
status does not mean everything below it was done in every way, and passing tests never means it works in real use.

| Status | Means |
|---|---|
| NOT BUILT | Doesn't exist. |
| BUILT, NOT TESTED | Code exists; no automated test exercises it. |
| TESTED WITH SIMULATED DATA | Automated tests pass using made-up charts, fake servers or recorded data. Says nothing about your real setup. |
| TESTED ON WINDOWS | Ran on Windows. **Unless the "Your PC" column says yes, this means a GitHub-hosted Windows Server machine**, not your computer, with no real Edge or TopstepX window. |
| VERIFIED WITH REAL MARKET OBSERVATIONS | Compared against what your real TopstepX chart showed, using the Chart check. |
| VALIDATED THROUGH OUT-OF-SAMPLE TESTING | (Strategies only) made money on data it was never fitted to, with enough trades and costs included. |

Columns: **Your PC** = run on your own Windows computer (the last time was version 0.7.0, 20 of 20 checks passed; nothing
since). **Real TopstepX** = checked against your real TopstepX chart (never, for any version).

## Summary

- **Nothing is VERIFIED WITH REAL MARKET OBSERVATIONS yet.** Every screen-reading number (contract, timeframe, live price,
  candles, indicators) has only been checked on made-up charts. The Chart check exists to fix this, and it needs you, your
  PC and a live TopstepX chart.
- **No strategy is VALIDATED.** NQ/MNQ results are inconclusive, ES/MES are losing, the stock studies are losing or
  inconclusive. The app correctly keeps every setup at WAIT.
- **The safety rules hold in every test**: no code path can send a real order, live trading can't be switched on, risky or
  unreliable data always gives NO TRADE, and restarting doesn't undo a stop or a risk lock.
- **Install, upgrade, backup, restore and rollback work on a Windows machine**, just not yet on yours.
- **This audit found and fixed a real safety bug:** in 0.13.2 (the version currently on the Releases page until 0.13.3 is
  published) a chart showing the wrong market could be reported as "Working". Don't use 0.13.2 for the Chart check.

## Safety

| Capability | What it does | Status | Your PC | Real TopstepX | Known limitations | Evidence |
|---|---|---|---|---|---|---|
| Practice-only lock | No code can send, change or cancel a real order; "live" mode is refused | TESTED ON WINDOWS | No | No | — | test_safety_audit.py on Windows and Linux; Windows self-test reports "live locked: True" |
| Practice badge always visible | PRACTICE MODE on every screen, both modes | TESTED WITH SIMULATED DATA | No | No | Checked in code and headless Chrome, not on your screen | test_safety_audit.py |
| Risk limits | Per-trade, daily, losses in a row, size, max loss limit, reward-to-risk, stop required | TESTED WITH SIMULATED DATA | No | No | Topstep rule presets from Topstep's help pages (2026-11-07/08), unconfirmed until you confirm them | risk and paper-engine tests |
| NO TRADE / WAIT logic | Anything not approved reads WAIT; approval needs a validated strategy (none exists) | TESTED WITH SIMULATED DATA | No | No | Not a separate engine (the 0.12 brief's NO TRADE engine is not built); this is the pipeline and quality gates | test_safety_audit.py, test_plain.py |
| Unreliable data blocks ideas | Stale, unreadable, disconnected, wrong market/timeframe, unconfirmed chart title, low confidence → NO TRADE | TESTED WITH SIMULATED DATA | No | No | Only simulated failures | test_safety_audit.py, test_watchdog.py |
| Reliability watchdog | One status per chart (Working / Working with problems / Frozen / Can't read / Not connected / Check chart settings / Off); restarts a dead reading loop; notices an unclean shutdown | TESTED WITH SIMULATED DATA | No | No | Detection thresholds were set on synthetic charts | test_watchdog.py (8 tests) |
| Stop everything | Stops all watching and automation; survives a restart; needs a written note to undo | TESTED WITH SIMULATED DATA | No | No | — | test_home.py, test_safety_audit.py |

## Reading your TopstepX chart (Phase 2)

| Capability | What it does | Status | Your PC | Real TopstepX | Known limitations | Evidence |
|---|---|---|---|---|---|---|
| Window capture of Edge (Windows Graphics Capture) | Captures only the TopstepX window, even when covered | BUILT, NOT TESTED | No | No | On Windows only the library loading was checked; it has never captured a real window. Minimized windows can't be captured | Windows self-test "available" only |
| Contract and timeframe recognition | Reads e.g. "MNQZ6 · 5m" from the chart title; refuses if it disagrees with the setup or can't be seen | TESTED WITH SIMULATED DATA | No | No | Fixed in 0.13.3 for the OCR version Windows uses (see audit X1) | test_watchdog.py, test_visual_monitor.py |
| Live price | Reads the price box about twice a second with several checks | TESTED WITH SIMULATED DATA | No | No | A screen reading, not exchange ticks; moves between reads aren't seen. 0 wrong of 300 synthetic frames on both OCR versions | test_live_price.py |
| Price-scale calibration | Converts pixel heights to prices from the scale labels | TESTED WITH SIMULATED DATA | No | No | — | test_visual_monitor.py |
| Candles | Open/high/low/close from the picture | TESTED WITH SIMULATED DATA | No | No | Candle times are estimated, not read from the time axis | test_visual_monitor.py |
| Indicators (VWAP, EMAs) | Read only if you assign each line's color | TESTED WITH SIMULATED DATA | No | No | Otherwise "not available" | test_visual_monitor.py |
| Resizing / zooming detection | Detects layout changes and stops trusting the old scale | TESTED WITH SIMULATED DATA | No | No | | test_visual_monitor.py |
| Frozen chart detection | Nothing changes for a while during market hours → Frozen | TESTED WITH SIMULATED DATA | No | No | | test_visual_monitor.py, test_watchdog.py |
| Tab switching / minimizing | Other tab → nothing captured (privacy); minimized → Not connected | TESTED WITH SIMULATED DATA | No | No | Tab detection relies on the Edge window title | test_watchdog.py |
| Interruptions and recovery | Comes back by itself when the chart returns; restarts a dead loop | TESTED WITH SIMULATED DATA | No | No | | test_watchdog.py |
| Chart check (the test tool) | Guided comparison of 13 things against your real chart; records how each value was obtained | TESTED WITH SIMULATED DATA | No | No | Needs you during market hours. Results so far: none | test_chart_check.py; docs/REAL_CHART_TESTING.md |
| Live copilot (older screen reader) | Earlier screenshot reader | TESTED WITH SIMULATED DATA | No | No | Duplicates the Visual Monitor (audit D1) | existing tests |

## Windows reliability (Phase 5)

| Capability | Status | Your PC | Known limitations | Evidence |
|---|---|---|---|---|
| Fresh install | TESTED ON WINDOWS | No (0.7.0 only) | Not code-signed: SmartScreen warning once | reliability run 43525788935 |
| Upgrade with your data kept | TESTED ON WINDOWS | No | Tested 0.13.1 → 0.13.2; the check was too strict on two files (fixed); all data identical | same |
| Automatic backup before an upgrade | TESTED ON WINDOWS | No | Keeps the newest 10 | same |
| Restore from a backup | TESTED ON WINDOWS | No | Done by copying the folder; there's no restore button | same |
| Start-up and clean shutdown, logs | TESTED ON WINDOWS | No | | same |
| No secrets in logs | TESTED ON WINDOWS | No | | same |
| Uninstall keeps your data | TESTED ON WINDOWS | No | | same |
| Installer rollback after a failed setup | TESTED ON WINDOWS | No | | same |
| Damaged database recovery | NOT BUILT | No | App refuses to start with a technical error; file is kept; restore by hand | same (observed) |
| Dependency checks in the installer (winget) | BUILT, NOT TESTED | No | The GitHub machine already has everything installed | — |
| Journal persistence over real days of use | TESTED WITH SIMULATED DATA | No | Only across one simulated upgrade | upgrade check |
| Releases only published after Windows tests and reliability checks pass | BUILT, NOT TESTED | — | Added in 0.13.3 after 0.13.2 was published with a failing test | workflow file; proven on the next run |

## Data, practice and analysis

| Capability | Status | Your PC | Real TopstepX | Known limitations |
|---|---|---|---|---|
| Stock prices and charts (Yahoo, free) | TESTED ON WINDOWS | No | n/a | Connected on the Windows machine; accuracy never compared to a reference. Unofficial data, may be delayed |
| Futures prices from Yahoo | TESTED WITH SIMULATED DATA | No | n/a | Delayed; always labelled delayed, never live |
| Futures "change today" | TESTED WITH SIMULATED DATA | No | No | Measured from 6 PM New York, not exchange settlement |
| Stock practice account | TESTED WITH SIMULATED DATA | No | n/a | Simulated fills by design |
| Futures practice account | TESTED WITH SIMULATED DATA | No | No | Refuses orders on free data unless "Practice on delayed prices" is on (audit F1) |
| Automation Center (futures) | TESTED WITH SIMULATED DATA | No | No | Never acts with free data (audit F2) |
| Home and Simple/Advanced modes | TESTED WITH SIMULATED DATA | No | No | Checked in headless Chrome only |
| Trust & Validation | TESTED WITH SIMULATED DATA | No | No | Intervals too narrow for correlated screenshots (audit C2) |
| Economic calendar and news | TESTED WITH SIMULATED DATA | No | n/a | Coverage beyond BLS releases unchecked |
| TopstepX API and stream (paid, off) | TESTED WITH SIMULATED DATA | No | No | Mock server only; costs about $29/month if you turn it on |
| AI explanations: Ollama (free) | TESTED WITH SIMULATED DATA | No | n/a | Fake server only |
| AI explanations: Anthropic (paid, off) | TESTED WITH SIMULATED DATA | No | n/a | Paid per use if you add a key; not needed |
| Chrome extension | TESTED WITH SIMULATED DATA | No | n/a | Not tried in a real Chrome |
| Mobile companion | TESTED WITH SIMULATED DATA | No | n/a | Not tried on a real phone |

## Strategies (Phase 4)

The status scale has no value for "tested out-of-sample and failed", so strategies get a **result** instead. **Validated
through out-of-sample testing: none.**

| Strategy | Result | Why |
|---|---|---|
| Futures, all setups combined: NQ / MNQ | Inconclusive | +0.29R / +0.42R average, but the 95% range includes losing (50 and 42 trades) |
| Futures, all setups combined: ES / MES | Losing | −0.07R / −0.03R |
| Liquidity sweep reversal | Inconclusive (NQ/MNQ long), losing (ES/MES long), inconclusive (short) | 11–27 trades each |
| Opening range retest | Untested (long), losing (short) | 3–8 trades each |
| Initial balance breakout, VWAP reclaim | Untested | 0–2 trades each |
| Trend pullback | Untested / inconclusive | 3–9 trades each |
| Stock 5-minute and 1-hour studies | Losing | 2,796 trades over 21 months (1-hour) |
| Stock 15-minute study | Inconclusive | |

Limits of all of it: one 10-week futures period, a holdout that was viewed during development, NQ/MNQ and ES/MES not
independent, Yahoo data. What validation would need is in the audit, Phase 4.

## Not built

Multi-timeframe analysis (1m–4h), a separate NO TRADE engine, trade quality scores, the fuller journal, the performance
dashboard, the strategy lab, replay of recorded screen sessions, calendar improvements, AI mentor improvements, a single
trading profile, desktop extras (layouts, annotations, export center), damaged-database recovery, a restore button, and
`docs/COST_AUDIT.md`.

## What you can safely rely on today

- It will not place a real trade.
- When it can't trust what it sees, it says WAIT rather than guessing (tested on simulated failures).
- Your data survives an upgrade and is backed up first (on a Windows machine, not yet yours).

## What you can't rely on yet

- Any number it reads from your TopstepX chart, until the Chart check on your PC says so.
- Any strategy making money.
- Recovery from a damaged data file without your help.

## Next step that matters most

Install 0.13.3 on your PC and run the Chart check on a live MNQ (or ES) chart during market hours. That is the only way any
part of this report can move to VERIFIED WITH REAL MARKET OBSERVATIONS.
