# Changelog

## 0.18.0 (2026-11-15)

The two things you said yes to: the app places practice trades by itself, and it re-tests its strategies every week.

**Practice trades without being asked**
- Automated practice trading (mode B) is now the default. When a strategy has passed testing, Study Terminal starts and manages its practice trades on its own, inside your risk limits, with pretend money. It was already built; it just had to be switched on by hand.
- If you had never picked a mode yourself, your app switches to it on this update. If you had picked one, your choice is kept. You can switch back any time in the Automation Center, and that choice then sticks.
- Nothing changes about real money. There is no order-routing code in Study Terminal and no setting that adds any.
- **Today this does nothing visible**, because no strategy has passed testing yet (NQ and MNQ inconclusive, ES and MES losing out of sample). The app will say so on screen, and will start trading by itself the day a strategy passes.

**Weekly strategy testing**
- Every contract is re-tested 7 days after its last test, with the same documented procedure on newer market data. It waits for that market to be closed so it stays out of the way, and runs anyway if it falls more than 11 days behind. One contract at a time; each takes a few minutes of your PC's time.
- It never changes a strategy, a parameter or a threshold. A strategy that stops meeting the bar stops trading on the next cycle; one that starts meeting it starts trading. Both are written to the automation log and sent as an alert.
- Every run is kept for good, so a later test can't hide an earlier poor result. The Automation Center has a new "Weekly strategy testing" panel with the schedule, the history and a "Test now" button.
- Switch it off with research.weekly in Settings.

**"Can I trust it?"**
- A new box at the top lists what fills in without you: chart checks, weekly strategy testing, and automatic practice trades, each with its current state.

## 0.17.0 (2026-11-15)

Faster start, every TopstepX window read, and "Can I trust it?" that fills in by itself. Also includes the 0.16.1 fix, which never shipped because a Windows check failed.

**It couldn't find your TopstepX chart (fix from 0.16.1)**
- The app looked for a tab with "TopstepX" in its name. The real tab is named after the contract and price, like "NQZ26 $27,927.25 ▼ -1.61%". It's now recognised when finding the window, in the window list, and by the privacy check. Bank, mail and other tabs are still refused.
- The contract is taken from the tab name when the chart header can't be read.

**Every TopstepX window**
- If you have more than one TopstepX chart open, each one is now read, not only the first. A browser only draws the tab in front, so each chart needs its own Edge window (drag the tab out of the window). Up to six.

**Faster**
- The window opens at once with a loading screen while the engine starts behind it, instead of nothing appearing until everything was ready.
- The first screens' data is fetched before you click, so Home and Charts open without waiting on a download.
- Start-up no longer waits for the futures monitor to catch up on market data.
- The market calendar loads about 100 times faster; a heavy library (scikit-learn) only loads when it's needed.
- The background data checks start a few seconds after launch, use fewer requests, and save their results off the main path.
- Unused fonts removed.

**"Can I trust it?" fills in by itself**
- Price, contract, timeframe and candle readings are now checked automatically while your chart is open: price against reference candles for the same minute, contract against the browser tab's name, timeframe and candles by comparing what's read from the picture with reference candles at every possible timeframe. These count the same as samples labelled by hand, so the first level (Visual validation) can be reached with no input from you.
- What it can't do: the later levels need strategy evidence and a record of practice trades. Right now no strategy has reliable out-of-sample results, so those levels stay open however long the app runs. They aren't faked.

**Windows checks**
- The recovery drill compared times to the second and could miss a rescue that finished in the same second it was asked for; fixed in the drill.
- The upgrade check now treats the app's own data-check records as expected changes.

## 0.16.1 (2026-11-14)

Fix: Study Terminal couldn't find or read the TopstepX chart in Edge.

- Cause: the app looked for a browser tab with "TopstepX" in its name. The real TopstepX tab is named after the contract and its price, for example "NQZ26 $27,927.25 ▼ -1.61%", with no "TopstepX" in it. So the window was never found, and a privacy check that only lets chart-looking tabs through would have refused it as well. Earlier tests used a made-up tab name.
- Now a tab named as a known futures contract followed by a dollar price is recognised as TopstepX: when finding the window, in the window list (marked with a star), and in the privacy check. Bank, mail and other tabs are still refused.
- The contract is taken from the tab name when the chart header can't be read, and a mismatch between the two is flagged.
- Tested with the exact tab name reported from a real PC. Not yet confirmed on that PC with this version.

## 0.16.0 (2026-11-14)

Study Terminal now checks its own data, by itself, all the time, and stops trade ideas when the data can't be trusted.

**Data check (new screen)**
- Every data source is checked in the background from the moment the app starts: is it reachable, fresh, still updating, the right symbol and timeframe, well-formed, and has its reply format changed.
- Where a second independent source exists, prices are compared. Crypto is compared across Kraken, Coinbase and Bitstamp. Solana token prices from DexScreener are compared with Jupiter and GeckoTerminal, and token identity with the Solana chain itself. Prices are never averaged: if two sources disagree, neither is trusted.
- Each source gets a status: Verified, Healthy, Delayed, Degraded, Stale, Conflicting, Unverified, Offline or Not supported. "Answering" is not the same as "right". Stock and futures prices can only reach Healthy or Delayed because no free second source exists for them.
- Results, outages and recoveries are saved on your PC for 45 days, with the app and check versions.
- A red banner appears on every screen when a source has a real problem.

**One safety check in front of every market**
- Stock ideas, futures ideas and memecoin practice buys all pass through one controller. It pauses a market when its data isn't Verified, Healthy or Delayed, when Stop everything is on, or in recovery mode. It can only pause; it can't place or change anything. One bad market doesn't pause a healthy one.
- After a restart, ideas wait for a fresh check instead of trusting the last result.
- Before a memecoin practice buy, that token's price is cross-checked. A conflict blocks the buy and says why.
- Open practice trades whose data has gone bad are flagged.

**TopstepX chart: automatic validation**
- Once your chart is connected, every reading is saved and later compared with reference candles for the same minute. No screenshots or manual comparing. Price reading counts as verified after 30 matches on two different days.
- Minimise/restore, covered tab, resize, frozen chart, contract or timeframe changes and restarts are recorded when they happen. Study Terminal still never clicks or types in TopstepX.
- Until your PC has real readings it shows as Unverified.

**FOMO and pump.fun**
- FOMO (fomo.family) has no developer API, and its Terms of Service forbid bots, scrapers and third-party tools from collecting its data. Nothing was connected. It shows as Not supported, with the reason. Tokens you find there can be pasted into Memecoins.
- pump.fun direct access shows as Not supported for the same kind of reason; its tokens are still covered through DexScreener and the chain.

**Not in this release**
- The iPhone app, crypto paper trading, the unified opportunity feed and background start with Windows. See docs/RELEASE_CANDIDATE_STATUS.md for the full plan and the release gates.

## 0.15.0 (2026-11-14)

New dark look, live crypto prices from exchanges, and more memecoin practice tools.

**Look**
- The app now opens in a dark exchange style: near-black background with a green glow, charcoal cards, one green accent, green pills for the active tab and the main button. The lavender aurora design is still there as the light theme (the sun/moon button at the top switches).
- Charts has a Markets column on the left: a card per coin with price, 24-hour change, a small trend line and the 24-hour high and low. Your stock list sits under it.

**Live crypto prices (ccxt)**
- Bitcoin, Ethereum, Solana, XRP, Dogecoin, Cardano, Chainlink and Litecoin prices now come from public exchange data (Kraken first, then Coinbase, then Bitstamp), a few seconds old instead of about a minute. Free, no account.
- The library used for this (ccxt) can place orders when it's given exchange keys. Study Terminal gives it none, has no setting that could, and switches off every order and account function. Health shows "Crypto prices: Read-only", and the installer's self-test fails if that lock is ever missing.
- Crypto is still watch only. If no exchange answers, the cards say so instead of showing old numbers as live.

**Memecoin practice**
- Exit plan: at your target you can sell only part (a quarter, half, three quarters) and keep the rest. The stop for the rest moves up to your buy price. An optional trailing stop follows the price up and never moves down.
- Sell half button on open positions.
- Practice journal: every finished memecoin practice trade with what it made or lost, how long you held it and how it ended. "Why I bought" and "What I learned" are only ever what you type; the app doesn't guess them.
- Hide amounts: hides dollar figures and keeps percentages, for sharing your screen.
- Rug-risk check has two new lines: whether the token lists any website or social links, and (for pump.fun tokens) whether it's still on pump.fun's starting curve or has graduated to a trading pool.

**Looked at and left out**
- Buying or selling real memecoins, wallets, token launches (pumpfun-agent-skill): real money and private keys, which stay outside the app. See docs/MEMECOIN_REAL_TRADING.md.
- Reading a real wallet's positions (pumpfun-utilities): the app's practice account has no wallet. Its journal idea and hide-amounts idea are what was used.
- From claude-trading-skills: exit strategies and pump.fun stages were used. Paid data services (Birdeye, Helius and others), prediction markets, tax tools and execution skills were not.

## 0.14.1 (2026-11-14)

New look, nothing else changed.

- Lavender background with a soft aurora glow at the top, white cards that float on a light shadow instead of borders, rounded pill buttons.
- One main button per screen in dark navy; active tabs and chips in a soft magenta. Font is now Inter.
- Green and red are only used for price moves, gains/losses and danger (darker shades so they're easy to read). The accent no longer flips colour with the market.
- Practice badge and Stop everything stay easy to spot. Dark mode follows the same style.
- No changes to trading rules, risk limits, data or safety checks.

## 0.14.0 (2026-11-14)

New: memecoin practice, an odds check for any plan, and a plain read of the last candle. Still practice only; real orders remain
impossible from Study Terminal.

- **Memecoins (Solana), practice only.** Watch new tokens with live prices from DexScreener (free), run a rug-risk check in
  plain words (can someone create more tokens or freeze yours, special token rules, pool size, age, selling pressure, biggest
  holders), and practise with a separate pretend-money account. Costs are modelled: price impact from the pool size, a 1% fee
  and a $0.05 network fee (editable). Every practice buy needs a stop; stops are checked about every 20 seconds and fill at the
  price seen then, so fast drops fill below the stop. Token names with slurs are hidden. The lists are labelled for what they
  are: tokens that paid DexScreener for a profile or a boost, not "trending". Study Terminal never holds a wallet or a key; a
  new safety test checks that no memecoin code can sign or send a transaction.
- **Real memecoin trading is kept outside the app.** `docs/MEMECOIN_REAL_TRADING.md` walks through pumpfun-cli in WSL with a
  separate small wallet, a dry run before every trade, and why the auto-sniper and AI-wallet tools were left out.
- **Check the odds** on any practice plan (Home, Charts, and the order ticket once a stop and target are set): how often the
  target came first, the stop came first, or neither by the close, on each of the last ~60 days and in 10,000 simulated
  sessions built from them, with a plain verdict ("close to a coin flip") and the break-even win rate. A simulation, not a
  prediction; costs aren't included. Idea from the day-trader skill pack (jakeschincariol/day-trader-skill).
- **Stock practice day-trading rules:** a warning from your 4th trade of the day (the journal's limit) and after 3:30 PM; set
  a limit in Settings to make either a hard stop. A reminder at 3:45 PM if practice trades are still open before the 3:55 PM
  flat time.
- **Last closed candle** card on Charts: the candle in words, its pattern, the market mood (trending up/down, sideways,
  jumpy), and how many of five checks point up or down (a count, not a win chance). **Copy for an AI** puts the same data as
  JSON on the clipboard to paste into Claude or any AI. Closed candles only, so it never changes after the fact. Idea adapted
  from AI Agent Lens (roan-maverick/tradingview-indicator-for-ai-agents), without its paid TradingView webhook or public tunnel.
- Fixed: crypto charts and analysis were cut down to stock-market hours; they now keep every hour.
- Faster start: screens load when first opened (initial download 695 KB -> 497 KB).
- Looked at and not added: Point72 csp (a C++ streaming engine; not needed at Study Terminal's data rates), Goldman Sachs
  gs-quant (needs institutional client credentials), Man Group ArcticDB (production use needs a paid licence), QuantOrb (a
  Solana memecoin holder scanner; its checks overlap the new rug-risk check), solana-sniper-mcp and pumpclaw (real-money
  wallet tools; see the guide).

## 0.13.6 (2026-11-14)

Prices that keep moving where the market really is moving, and honest "closed" screens where it isn't. No trading changes.

- **Each market by its own hours.** Stocks follow the stock exchange; futures follow CME Globex (Sunday 6 PM to Friday 5 PM ET,
  so they now count as open on weekday evenings); crypto is open 24/7. Before, everything used stock-market hours, so Bitcoin
  was labelled "Market closed" on weekends even though its price was current.
- **Watch something live at the weekend.** Charts has **Bitcoin** and **Ethereum** chips ("Open 24/7"). Their prices stream
  live from Yahoo's free feed (unofficial, can lag a little), the big price and the line update as it goes, and 1D means the
  last 24 hours. Crypto is watch-only: no practice trades or setups for it.
- **Whatever is on the Charts page updates live**, even if it isn't on your watchlist (it's followed while it's on screen).
- **Closed markets say so plainly.** Charts shows the official close, the after-hours price on its own line, and a live
  countdown to the open. My chart (TopstepX) shows "Futures closed for the weekend, opens Sun 6:00 PM ET" with a countdown
  instead of looking frozen. Home says the market is closed, gives Friday's real result (from daily bars) and the opening time.
- Prices are never invented: when a market is closed its last real price stays on screen, marked with when it was.

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
