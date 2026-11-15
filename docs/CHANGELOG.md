# Changelog

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
