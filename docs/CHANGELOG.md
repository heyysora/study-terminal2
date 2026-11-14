# Changelog

## 0.13.5 (2026-11-13)

Finishes recovery and reliability so ordinary problems can be fixed from inside the app. No trading changes.

- **Backups you can trust.** Every backup records each file's size and fingerprint and is marked finished only at the end; it
  is read back straight away and re-checked daily (or with **Check my backups**). Backups that didn't finish, are missing
  files or are damaged are shown in red and can't be restored. The newest usable backup is never deleted automatically, even
  if newer ones are bad. Settings and Health show the last good backup and whether the newest one passed, and the app warns
  when there's no usable backup.
- **Safer restore.** The new data file is built and checked before your current one is touched; if anything fails after
  that, your original is put back exactly. A backup that turns out damaged at restart changes nothing and is flagged.
- **Recovery screens explain themselves**: what went wrong, whether your data is safe, and for each option what it does,
  whether you could lose anything, and what happens next.
- **Health page**: app, data file, backups, chart monitor, Chrome extension, last good start, recent errors, whether a
  restart would help (with a Restart button), a recovery check you can run on your own computer, and a complete help file.
- **Chrome extension finds the app by itself** when it isn't on port 8765 (checks 8765-8804 and remembers the answer). A
  **Find Study Terminal** button, plus connection status and repair steps in Settings and Health.
- Fixed: after a quick restart the app could move to another port for no reason (Linux kept the old port briefly reserved).
- Fixed: the extension could wait forever when another program held its port without answering.

## 0.13.4 (2026-11-13)

Makes the problems found in the audit fixable from inside the app. No trading changes.

- **Recovery mode.** If your data file is damaged or the data folder can't be written, Study Terminal opens a plain Recovery
  screen instead of crashing: use the newest backup (shows when it was made and what's in it), rescue whatever can still be
  read, start with empty data, or save a help file. It restarts itself to do it. The damaged file is kept in `damaged\`.
- **Backups you can see and use.** Daily backups (newest 7 kept), **Back up now**, and **Restore** in Settings > Your data. A
  restore backs up your current data first. **Open my data folder** and **Open backups folder** buttons.
- **Help file.** One click saves a zip with logs, Chart check results and pictures, and app status to your Downloads folder.
  Passwords and keys are blanked out; `.env` is never included. Chart check has **Save my results to send**.
- If port 8765 is taken by another program, Study Terminal moves to the next free one by itself.
- If it can't start at all, it says so in plain words and saves a help file automatically.
- Home warns when the disk is nearly full.
- Trust & Validation accuracy is counted by session (screenshots from one session aren't independent) and needs samples from
  at least 3 different days to pass. The in-sample cost table no longer shows "promising" labels.
- Windows reliability now also checks Recovery mode, a restore on Windows, and starting with the port taken: 19 of 19 passed.

## 0.13.3 (2026-11-13)

Fixes from the post-feature audit (`docs/POST_FEATURE_AUDIT.md`, `docs/STUDY_TERMINAL_READINESS_REPORT.md`). No new features.

- **Fixed: a chart showing the wrong market could be reported as "Working".** The OCR version in the Windows app reads the "·" in
  a TopstepX chart title as ":", so the market name wasn't found and the chart's own setup was assumed instead. The title is now
  read correctly with either OCR version, and a clock time like "10:15" is never taken for a timeframe.
- **Stricter: if the chart's market or timeframe can't be read, no trade ideas.** Before, the setup's own values were trusted at
  high enough confidence to allow ideas. Now the watchdog shows "I can't see the market name on the chart" and ideas stop.
- **Releases are only published when every test passes on Windows and the Windows reliability checks pass.** 0.13.2 was
  published even though one Windows test failed (the bug above).
- The Windows upgrade check lists the build marker and Yahoo's cache as expected changes instead of failing on them; every other
  file must still be unchanged.

## 0.13.2 (2026-11-13)

- **Reliability watchdog**: one plain status per chart (Working, Working with problems, Frozen, Can't read, Not connected, Check
  chart settings, Off), restarts a stopped reading loop, warns once per change, notices if the app didn't close normally, and
  stops trade ideas when the chart can't be trusted or doesn't match its setup.
- **Chart check** (Phase 2 test tool): compare what Study Terminal reads with what your real TopstepX chart shows, and test
  resizing, zooming, switching tabs, minimizing, a frozen chart and restarting. Results and pictures are saved in your data
  folder. See `docs/REAL_CHART_TESTING.md`.
- Safety audit tests (`tests/test_safety_audit.py`) and an automatic Windows reliability run on every build (install, upgrade
  with data, backup, restore, uninstall, installer rollback, damaged database).
- Uninstalling without questions (silent) now keeps your data.
- **Known problem, fixed in 0.13.3**: a wrong-market chart could show as "Working" with the OCR version Windows uses.

## 0.13.1 (2026-11-13)

- **Charts (Simple mode) redesigned** like Home: big price, change today versus yesterday's close, a clean line chart with
  1D / 5D / 1M / 3M / 1Y and a Candles view, hover for the price at any time, quick-switch chips for your watchlist, and plain
  cards for "Should I practice a trade or wait?" (5-minute chart, the day-trading view), key prices, what's happening and news.
  The full trader page with every indicator is unchanged in Advanced mode.
- Chart time axes show dates at day boundaries instead of repeating "09:30".
- Home (stocks) leads with the actual move ("The stock market is down 0.39% today"); it no longer says "leaning up" while the
  S&P 500 is down.
- Simple mode shows only urgent pop-ups, one at a time; the rest go to Messages.
- More WAIT reasons in plain words.

## 0.13.0 (2026-11-13)

Release of the 0.12.0 preview work, for day trading practice. Everything below under "0.12.0 preview 2" and "0.12.0 preview 1" is
included: the live price read from your TopstepX chart about twice a second with a live line chart, light and dark themes, Home
with five plain answers and a setup guide, the safety bar (practice badge, health light, Stop everything), plain-language WAIT
explanations, Simple and Advanced modes, and an automatic data backup the first time a new version starts.

Practice trading, risk calculations, permissions and the practice-only lock are unchanged. 450 tests pass on Python 3.11, 3.13
and on Windows. Accuracy on your real TopstepX charts still needs checking (see docs/LIMITATIONS.md).

## 0.12.0 preview 2: live price and a cleaner look (2026-11-13)

Display and reading changes only. Practice trading, risk calculations, permissions and the practice-only lock are unchanged.

### Added
- **Live price from your TopstepX chart.** About twice a second Study Terminal reads only the price box on the chart's price scale
  (about 25 ms per read). A price is used only if it sits on the contract's price steps, matches where it sits on the price scale
  (fitted by the full chart read), and isn't a sudden jump of more than 40 ticks that the next read fails to confirm. Anything
  else is rejected and a full chart read is done instead. The full read (candles, indicators, analysis) still runs every few seconds.
- **Live price header and chart** on Home and My chart: big price, change since the session opened at 6:00 PM New York time (or
  since watching started), a line chart of accepted prices with 5 min / 1 hour / 4 hours / Today ranges, hover to see the price at
  any moment, and a Candles view (candles are estimated from the picture). Gaps in the line are times the chart couldn't be read;
  nothing is filled in. "How accurate is this?" shows how many prices were accepted and rejected.
- Prices are saved per day in `<data>\live_prices\` (two weeks kept) so today's chart survives a restart. Test and demo sources
  are never saved.
- **Light and dark themes**, following the Windows setting by default (button in the top bar). New typography, rounded cards,
  pill buttons, and one accent color that turns green or red with the day's move.
- API: `GET /api/visual/live` and `GET /api/visual/live/{profile}` (`range=live|1h|4h|day`); pushed `visual_price` messages.
  Chart profiles gain `live_seconds` (default 0.5; older saved profiles get the default).

### Not changed
- Practice trading (stocks and futures) works exactly as before.
- The live price is labeled as read from your screen, never as an exchange feed.

## 0.12.0 preview 1: interface foundation (2026-11-10)

First part of 0.12.0. It changes what is shown and adds a backup. It does not change trading logic, risk calculations, permissions,
stored data or the practice-only lock, and adds no dependency, service or cost.

### Added
- **Safety bar on every screen**: a permanent PRACTICE MODE badge; one health light (Working / Not watching / Needs attention /
  Not working) with a sentence and what to do; a **Stop everything** button with an in-app confirmation; a banner when the
  interface can't reach the engine; an always-visible risk line in plain words (practice money, today so far, most you can still
  lose today, at risk right now, new practice trades allowed or stopped).
- **Home**: five answers (Is Study Terminal working? What is the market doing? Should I practice a trade or wait? How much could I
  lose? What should I do next?), a getting-started guide whose ticks reflect real state, the last three decisions as sentences, and
  a "start again" box after a stop.
- **Plain-language layer** (`backend/app/plain.py`, mirrored in `frontend/src/plain.json`): every "don't trade" outcome reads WAIT
  with a headline, what to do, and the original reason under "More detail"; status words (Working / Old prices (delayed) / Chart
  isn't updating / Can't read the chart / Can't find the chart); everyday names and hover explanations for trading terms; "Practice"
  instead of paper/sim/simulator on labels; confidence shown as High / Medium / Low with "not the chance of winning".
- **Simple and Advanced modes** (Simple is the default). Advanced shows every screen and the original terms.
- **Automatic backup** of existing data the first time a new build starts (`<data>\backups\`), before the database is opened.
- API: `GET /api/home` (read-only), `POST /api/stop-everything` (needs `confirm: true`), `POST /api/start-again`, `GET /api/plain`,
  `POST /api/plain/explain`. Settings: `ui.mode`, `ui.setup_dismissed`, `ui.trades_chosen`.

### Changed
- The app opens on Home (the old stock dashboard is "Stock overview" in Advanced).
- Automation Center: the mode buttons read "I place practice trades myself" / "The app places practice trades for me"; the disabled
  "C - Live (locked)" button is replaced by one sentence saying real-money trading isn't part of Study Terminal. The lock itself is
  unchanged in the backend and still reported by the API.
- Recommendation card (Visual Monitor): leads with the plain reason; plan numbers use everyday labels in Simple mode.
- Error messages and alerts pass through the word list in Simple mode.

### Not changed (checked by tests)
- Risk limits, risk status, automation rules and the live lock are identical in Simple and Advanced.
- Data status values used by trading rules; delayed data is never labelled as working or live.
- Database layout. Existing journals, practice accounts, settings, limits, chart profiles and validation evidence load unchanged.

### Still to verify on Windows
See the list at the end of the delivery notes and `docs/TEST_RESULTS.md`.
