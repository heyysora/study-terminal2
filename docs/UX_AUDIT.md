# Study Terminal product experience audit (version 0.11.0)

Audit date: 2026-11-10. Nothing in the app was changed for this audit. It is a list of problems and proposed fixes for you to approve.

**Status (0.12.0 preview 1):** stages 1-3 of section 9 are implemented (top bar, plain-language layer, Home and setup guide), plus a
first Simple/Advanced switch. Stages 4-7 are still open. Findings addressed so far: A4, A5, B1-B6, B8, B12 (interface labels),
C1-C5, D1, D3, D5, G1 (wording), G5 (Stop everything dialog). Details in `docs/CHANGELOG.md`.

**The test used throughout:** a 10-year-old who has never traded and never used trading software should be able to find their way around, understand what the app is telling them, and use the basic features.

**Design rule this audit is held to:** the software should do the complicated thinking. The user should not have to do the complicated navigating.

**How the audit was done.** I read the source of every screen (all 15 menu entries, both status strips, every panel, button, setting and notification), the wording the backend sends to the screen, and the screenshots taken during earlier releases. No real user tried the app, and it was not run on Windows for this audit, so findings about how things *feel* are judgments from the code and screenshots, not observations of a person using it.

---

## 1. Short answers to the ten questions

| # | Question | Answer today | Main reasons |
|---|---|---|---|
| 1 | Is the purpose of every screen obvious? | No | 15 menu entries, several with near-identical names (Live copilot, Live Market, Live Visual Monitor, Chart). No screen says what it is for in one sentence. |
| 2 | Are labels understandable without finance or programming knowledge? | No | Heavy trading shorthand (RTH, VWAP, EMA, R, expectancy, walk-forward, slippage) and programming terms (token, polling, stream, PrintWindow, DIRECTLY_READ). |
| 3 | Are there unnecessary buttons or menus? | Yes | Three separate start/stop monitoring controls, four chart screens, four simulated accounts, settings in five places. |
| 4 | Is important information buried? | Yes | "Is everything working?" and "what should I do next?" are not answered anywhere. The reason for a WAIT is in small grey text. The emergency stop exists on one screen only. |
| 5 | Are there confusing settings? | Yes | About 40 settings across five locations, many using units a beginner can't judge (ticks, bps, ATR, seconds of staleness). |
| 6 | Are error messages understandable? | Partly | Most are full sentences, but they use internal words (provider, profile, token, calibration) and rarely say what to do. |
| 7 | Does the app explain what to do next? | No | There is no first-run guide and no "next step" on any screen. |
| 8 | Can users tell paper from live? | Mostly, with gaps | "Paper only" / "Simulator only" is always in the top strip, but it is small, uses two different words, and four different simulated accounts blur the picture. |
| 9 | Can users understand why the system says WAIT? | No | Five different words are used for "don't trade" (WAIT, NO TRADE, WATCH_ONLY, REJECTED, Blocked) and the reasons are written for traders. |
| 10 | Can users tell when the app is malfunctioning? | Partly | Problems are detected well, but shown as small labels in different places with different words (STALE, UNREADABLE, DISCONNECTED, Problem, App offline). There is no single "something is wrong" signal. |

---

## 2. Findings

Priority: **P1** = blocks a beginner or risks a dangerous misunderstanding. **P2** = causes real confusion. **P3** = polish.
Risk: chance that making the change breaks something that works today. Every proposal below keeps the existing calculations, data, safety limits and API; they change what is shown and where.

### A. Navigation and overall structure

| ID | Screen or component | Current problem | Why it confuses users | Proposed improvement | Priority | Risk of breaking things |
|---|---|---|---|---|---|---|
| A1 | Side menu | 15 entries in one flat list: Dashboard, Chart, Live copilot, Scanner, Paper trading, Automation Center, Live Market, Live Visual Monitor, Futures (TopstepX), Journal, Backtest, Learn, Trust & Validation, Alerts, Settings. | Too many choices, and nothing says where to start. | Five sections: **Home, Charts, Practice, My Progress, Settings**. Every existing screen moves under one of them (mapping in section 4). Old links keep working. | P1 | Low. Routing only; screens themselves are unchanged. |
| A2 | Side menu | Four entries that all mean "look at a chart": Chart, Live copilot, Live Market, Live Visual Monitor. | A beginner can't tell which one to open. Three of the names start with "Live". | One **Charts** section with a plain choice at the top: "Watch my TopstepX chart" (Visual Monitor, the default), "Look up a chart", "Check a screenshot". Live Market (needs the paid TopstepX API) moves to Advanced. | P1 | Low. |
| A3 | Stocks / Futures switch (top strip) | A two-button switch changes the top strip and the landing page, but the menu still shows everything for both markets. | The user is doing futures; stock screens (Scanner, stock Paper trading, Dashboard watchlist) look like part of the same workflow. | Ask once at first run "What do you trade?" and hide the other market's screens in Simple mode. Keep the switch in Settings. | P1 | Medium. Menu filtering must not hide a screen that holds the user's open simulated positions. |
| A4 | Landing page | In futures mode the app opens on Automation Center. In stock mode it opens on a watchlist dashboard. | Neither answers "is it working, what's the market doing, should I wait, what am I risking, what next". | A new **Home** screen with exactly five cards answering those five questions (layout in section 5). | P1 | Low. A new screen reading existing endpoints. |
| A5 | Whole app | No first-run guide. No screen suggests a next step. | A new user sees a full dashboard of empty or dashed values and no instruction. | A "Next step" card on Home driven by real state: no chart connected → "Connect your chart"; chart connected but unchecked → "Check chart settings"; rules unconfirmed → "Confirm your loss limits"; all done → "You're set. Watch for a plan." | P1 | Low. |
| A6 | Futures (TopstepX) screen | One screen holds the analysis, the account, rules, personal limits, data settings, simulator settings, fees, replay, evidence and the calendar. | It is the longest screen in the app and mixes daily use with one-time setup. | Split by purpose: plan and account → Practice; replay and evidence → My Progress; rules, limits, fees → Settings. | P2 | Medium. Large component; move panels without changing them. |
| A7 | Menu group labels | "Research" and "System" appear as small group headings above single items. | The grouping is partial, so it reads as inconsistent. | Removed by A1. | P3 | Low. |

### B. Words and labels

| ID | Screen or component | Current problem | Why it confuses users | Proposed improvement | Priority | Risk of breaking things |
|---|---|---|---|---|---|---|
| B1 | Recommendations everywhere | Five words mean "don't trade": **WAIT**, **NO TRADE**, **WATCH_ONLY**, **REJECTED**, **Blocked**. "potential LONG" adds a sixth state. | The user can't tell whether these are different situations or the same one. WATCH_ONLY shows an underscore straight from the code. | Three words on screen: **WAIT**, **POSSIBLE TRADE (practice only)**, **STOPPED**. The detailed internal state stays available under "More detail". | P1 | Low. Display mapping only; stored decisions keep their original values. |
| B2 | Data status labels | LIVE, Near real-time, Polling, DELAYED, CACHED, STALE, DISCONNECTED, Unavailable, LIVE VISUAL OBSERVATION, SCREEN CAPTURE, UNREADABLE. | Eleven labels for "how fresh is this". Several are programming terms. | Four plain states with one colour each: **Working**, **Slow** (delayed), **Chart isn't updating**, **Can't see the chart**. The exact label stays in Advanced mode and in the logs. The rule that delayed data is never called live is kept. | P1 | Low, if done as a display layer. The underlying status values must not change because trading rules depend on them. |
| B3 | Recommendation card | "Risk/reward 1.8R", "Evidence tier", "Size (risk engine)", "Data confidence 0.82", "What invalidates it". | None of these mean anything without trading knowledge. | "You could gain about $X for every $1 you risk", "How well tested is this idea?", "How many contracts", "How sure am I that I'm reading the chart right: High / Medium / Low", "The plan is cancelled if…". | P1 | Low. |
| B4 | Top strip (futures) | "Room above max loss", "Entries: Allowed/Blocked", "Rules … unconfirmed", "Futures sim balance". | These are the most important safety numbers and they are in the least clear wording. | "Money left before the account fails", "New trades: allowed / stopped (reason)", "Loss limits: not confirmed yet", "Practice money". | P1 | Low. |
| B5 | Top strip (stocks) | "Market data: Stream + polling / Polling only / Problem", "Market bias: SPY bullish". | Stream and polling are programming terms. "Problem" doesn't say what or what to do. | "Prices: working / slow / not working" with a one-line reason and a fix. | P2 | Low. |
| B6 | Automation Center | Modes are "A · Assisted", "B · Automated paper", "C · Live (locked)". | Letters carry no meaning. "Live (locked)" invites the question "how do I unlock it?". | "I place practice trades myself", "The app places practice trades for me". Remove the Live button from the mode row and state once, plainly: "Real-money trading is not part of Study Terminal." | P1 | Low. The lock stays exactly as it is in the backend. |
| B7 | Trust & Validation | UNTESTED / IN PROGRESS / PASSED / FAILED are clear, but the detail uses "95% lower bound", "Wilson", "out-of-sample", "walk-forward", "holdout", "average R". | The page exists to build trust, and a beginner can't read it. | Keep the four statuses. Lead each card with one sentence: "Checked 12 of about 35 real screenshots needed." Move the statistics under "How this is measured". Rename the page **Can I trust it?** | P2 | Low. |
| B8 | Visual Monitor values | Source classes are printed as code: DIRECTLY_READ, CALCULATED_FROM_CALIBRATION, VISUALLY_ESTIMATED, UNAVAILABLE. | They look like error codes. | "Read from the chart", "Worked out from the chart", "Estimated", "Couldn't read". | P2 | Low. |
| B9 | Charts and levels | RTH, VWAP, EMA 9/20/50/200, ATR, FVG, BOS, liquidity sweep, volume profile, regime. | Trading shorthand with no explanation at the point of use. | Simple mode: describe the effect ("price is above today's average price"). Advanced mode: keep the terms, each with a one-line hover explanation taken from the existing glossary. | P2 | Low. |
| B10 | Journal and Backtest | Expectancy, profit factor, R, drawdown, slippage, bps, walk-forward folds, calibration, optimization. | Performance is the thing a beginner most wants to understand. | "Average result per trade", "Money won for every $1 lost", "Biggest drop from your best point", "Price slip when the order fills". Technical name shown in brackets in Advanced. | P2 | Low. |
| B11 | Two meanings of "calibration" | Used for (a) checking the app reads your chart correctly, (b) lining up the chart's price scale, (c) "Signal calibration" in Backtest. | One word, three jobs. | (a) "Check chart reading", (b) "Line up the price scale", (c) "Do the scores match results?" | P2 | Low. |
| B12 | "Paper", "Sim", "Simulator", "Practice", "Sandbox", "Replay" | Six words for pretend money. | The user can't tell if these are the same account. | One word everywhere: **Practice**. | P1 | Low. Labels only. |
| B13 | Settings | "Token", "Chrome extension", "Mobile companion token". | "Token" is a programming word. | "Pairing code". | P3 | Low. |

### C. Home, status and "is it working?"

| ID | Screen or component | Current problem | Why it confuses users | Proposed improvement | Priority | Risk of breaking things |
|---|---|---|---|---|---|---|
| C1 | Whole app | No single health indicator. Health is spread over the top strip ("Market data", "Screen"), the Visual Monitor (status per chart), Automation Center (status and log) and Alerts. | To know whether the app is working the user must check four places and understand each label. | One always-visible light in the top bar: **Working / Needs attention / Not working**, with one sentence and one button ("Fix it"). It is the worst state of the existing checks; no new detection logic. | P1 | Low. |
| C2 | Top strip | Seven small cells of equal weight. Paper-vs-live is the last one, in the same small grey style as the rest. | The single most important fact has the least emphasis. | A permanent, coloured **PRACTICE MODE: no real money** badge at the top left of every screen. | P1 | Low. |
| C3 | Top strip | Values show "—" when not loaded or not available. | A dash doesn't say whether it is loading, empty or broken. | "Loading…", "Nothing yet", or the specific reason. | P2 | Low. |
| C4 | Backend not reachable | The only sign is "App offline" in one strip cell; pages show empty panels. | It looks like there is simply no data. | A full-width banner: "Study Terminal's engine isn't running. Close the app from the tray icon and open it again." | P1 | Low. |
| C5 | Emergency stop | Present only inside Automation Center, among other buttons. | In a stressful moment the user has to remember which screen it is on. | A **Stop everything** button fixed in the top bar on every screen, same behaviour and confirmation as today. | P1 | Low. It calls the existing action. |
| C6 | Stock Dashboard | Opens with a watchlist table, live signals, opportunities, paper account, positions and alerts: six dense panels. | Dense tables on the first screen; no summary sentence. | Replaced by Home (A4). The current dashboard becomes "Stock overview" under Charts in Advanced mode. | P2 | Low. |
| C7 | Automation log and "Recent decisions" | Raw rows of timestamps, contract codes and outcomes. | Useful for diagnosis, not for a beginner. | Simple mode shows the last three as sentences ("10:35: Waited. The larger charts didn't agree."). Full table in Advanced. | P2 | Low. |

### D. WAIT, plans and explanations

| ID | Screen or component | Current problem | Why it confuses users | Proposed improvement | Priority | Risk of breaking things |
|---|---|---|---|---|---|---|
| D1 | Recommendation card | The reason for WAIT is one small line of text under the badge, written for traders, followed by more small grey lines. | The answer to "why?" is the least visible thing on the card. | Lead with a big plain sentence: "**Wait.** The larger charts aren't agreeing yet." Then up to three short reasons with icons. Technical detail in an expandable "More detail". | P1 | Low. Needs a plain-language reason for each existing reject code (a lookup table; the logic is untouched). |
| D2 | 13-step decision list (Futures) | Every decision shows all 13 pipeline steps with pass/fail. | It is a debugging view. A beginner sees 13 rows of jargon. | Simple mode: show only the first step that failed, in plain words. Full list in Advanced. | P2 | Low. |
| D3 | "potential LONG" | A WAIT can carry "potential LONG" because no strategy has passed validation yet. | Looks like a hidden instruction to buy. | "The app noticed a possible up-move, but this idea hasn't passed testing yet, so it's practice-only." | P1 | Low. The evidence rule itself is unchanged. |
| D4 | Blocked trades | Risk-engine refusals appear as red notes with trader wording ("per-trade limit", "Reward-to-risk below minimum"). | The user doesn't learn which of *their* limits stopped it or where to see it. | "Stopped: this trade could lose $180 and your limit is $150 per trade. (Change in Settings › My limits.)" | P2 | Low. |
| D5 | Quality and confidence numbers | "Data confidence 0.82", evidence tiers, scores. | A number between 0 and 1 reads like a chance of winning. | Words (High / Medium / Low) plus, wherever a score appears: "This is not the chance of winning." | P1 | Low. |

### E. Practice trading

| ID | Screen or component | Current problem | Why it confuses users | Proposed improvement | Priority | Risk of breaking things |
|---|---|---|---|---|---|---|
| E1 | Accounts | Four simulated accounts: stock Paper account, futures Practice account, Research sandbox, Replay account. | The user can't tell which balance is "theirs". | Simple mode shows one: **My practice account** (futures practice, or stock paper if they trade stocks). Sandbox and replay are described as "test runs" under My Progress. | P1 | Medium. Display only, but totals must never be merged across accounts. |
| E2 | Order ticket | Order type, limit price, stop, targets, quantity, bracket all shown at once. | A beginner doesn't know which fields matter. | Simple mode: "Practice this plan" fills the ticket from the current plan and shows three numbers: what I could lose, what I could gain, how many contracts. Full ticket in Advanced. | P2 | Medium. Must go through the same preview and risk check as today. |
| E3 | Reset account | A "Reset account" button sits beside the account summary. | Easy to press; erases history. It does ask for confirmation today. | Move to Settings › Advanced, keep the confirmation, and offer "Save a backup first". | P2 | Low. |
| E4 | Position size calculator | A separate panel with its own inputs. | Duplicates what the order preview already calculates. | Fold into the order preview. | P3 | Low. |

### F. Setup and settings

| ID | Screen or component | Current problem | Why it confuses users | Proposed improvement | Priority | Risk of breaking things |
|---|---|---|---|---|---|---|
| F1 | Settings in five places | Settings page (about 13 controls), Futures › rules and settings (about 16), Visual Monitor setup (about 13), Automation Center (mode, mobile), Live copilot (calibration). | The user can't predict where a setting lives. | One **Settings** section with four plain groups: My limits, My chart, Alerts, Advanced. | P1 | Medium. Moving panels; each must keep saving to the same place. |
| F2 | Visual Monitor setup | Three steps asking for a window, a region, the instrument, timeframe, price-scale points, candle colours, capture method. Terms shown include window handle, PrintWindow, Windows Graphics Capture, axis points, colour tolerance. | This is the hardest task in the app and the first one a new user must do. | A guided "Connect your chart" walkthrough: (1) "Open TopstepX in Edge" with a live check, (2) "Is this your chart?" with a preview and Yes/No, (3) the app detects instrument, timeframe and colours itself and asks only "Does this look right?", (4) a test read shown as a sentence. Manual controls stay under "Adjust by hand". | P1 | Medium. The walkthrough calls the existing endpoints; auto-detect already exists for most fields. |
| F3 | Chart-reading check | Lives inside Live copilot as "Calibrate screen reading" with "Score it" and "Re-score kept screenshots". | Hidden in an unrelated screen; the buttons don't say what they do. | Move to My Progress › Can I trust it? as "Check a screenshot": upload, type what you see, get "The app read this correctly / incorrectly". | P2 | Low. |
| F4 | Two sets of risk limits | Stock limits in Settings › Risk limits (percent of equity). Futures limits in Futures › rules (dollars), split again into "Prop-firm rules (official)" and "Your own limits (personal)". | Three places, two units. | One "My limits" page showing only the limits for the market the user trades, with the firm's rules and their own limits side by side and a plain note on which wins (the stricter one). | P1 | Medium. No limit values may change during the move; add a test that compares before and after. |
| F5 | Units | Slippage in ticks and bps, stale time in seconds, ATR multiples, fees per round turn. | A beginner can't judge whether 4 ticks or 180 seconds is sensible. | Keep sensible defaults, hide these in Advanced, and show the dollar effect next to each ("about $5 per trade"). | P2 | Low. |
| F6 | "Unconfirmed" rules | The strip shows "unconfirmed" in small red text. | It isn't clear what to confirm or why it matters. | A Next-step card: "Confirm your loss limits so the app can protect your practice account the way your real account works." | P2 | Low. |

### G. Messages, alerts and errors

| ID | Screen or component | Current problem | Why it confuses users | Proposed improvement | Priority | Risk of breaking things |
|---|---|---|---|---|---|---|
| G1 | Error messages | The screen shows the backend's message as-is. Most are sentences, but they use internal words (provider, profile, token, calibration, stale) and often stop at what went wrong. | The user knows something failed but not what to do. | Every message follows one pattern: what happened, why, what to do next. Technical text goes to the log and an expandable "Details". | P2 | Low. |
| G2 | Pop-up notifications | Each toast links to "Open chart and full analysis", which goes to the stock chart page. | For futures and Visual Monitor alerts the link leads to the wrong place. | Link to the screen that raised the alert. | P2 | Low. |
| G3 | Alerts page | One long history with a "Send test alert" button. No grouping by importance. | Important problems (chart stopped updating) sit among routine ones. | Two lists: "Needs your attention" and "For your information". Test button moves to Settings › Alerts. | P2 | Low. |
| G4 | Three "Start monitoring" buttons | Live copilot ("Start watching"), Automation Center ("Start monitoring"), Visual Monitor ("Start monitoring"). They start three different things. | The user can't tell what is on. | One "Watching your chart: On / Off" control on Home that starts what is needed for the user's setup. The separate controls remain in Advanced. | P1 | Medium. Starting order and the privacy consent step for screen capture must be preserved. |
| G5 | Confirmation dialogs | Use the browser's plain confirm box with long text. | Looks like an error; easy to click through. | In-app dialogs with a clear title, one sentence and two labelled buttons. | P3 | Low. |

### H. Visual design and consistency

| ID | Screen or component | Current problem | Why it confuses users | Proposed improvement | Priority | Risk of breaking things |
|---|---|---|---|---|---|---|
| H1 | All screens | Small, dense text; many panels per screen; tables as the default presentation. | Looks like institutional trading software. | Simple mode: larger type, one main card per question, at most four cards per screen, tables only on request. | P2 | Low. A CSS and layout layer. |
| H2 | Colour | Green and red are used for direction (up/down), for profit and loss, and for good/bad status. | Red "SHORT" looks like an error. | Status uses green / amber / red with an icon and a word. Direction uses arrows and the words Up / Down. | P2 | Low. |
| H3 | Capitals | LIVE, STALE, DISCONNECTED, WATCH_ONLY, EMERGENCY STOP mixed with sentence-case labels. | Capitals read as shouting; a beginner assumes each one is an alarm. | Capitals only for the practice badge and Stop everything. | P3 | Low. |
| H4 | Help | A glossary and lessons exist under Learn, but nothing links to them from the screens that use the terms. | The help is there and nobody finds it. | A small "?" beside any term in Advanced mode that opens the existing glossary entry. | P2 | Low. |
| H5 | Time zones | Times appear in ET, CT and UTC on different screens. | The same moment looks like three different times. | One time zone everywhere (the computer's), with the exchange time in Advanced. | P2 | Low. Display only; stored times stay in UTC. |

---

## 3. Redundant or overlapping features

| Overlap | Where | Proposal |
|---|---|---|
| Four chart screens | Chart, Live copilot, Live Market, Live Visual Monitor | One Charts section (A2). |
| Three monitoring switches | Live copilot, Automation Center, Visual Monitor | One switch on Home (G4). |
| Four practice accounts | Paper, Practice, Sandbox, Replay | One shown by default (E1). |
| Risk limits in three places | Settings, Futures rules (firm), Futures rules (personal) | One "My limits" page (F4). |
| Two performance views | Journal analytics, Futures journal and evidence | One My Progress section, with practice results, replay results and history tests kept visibly separate. |
| Replay is hidden | "Replay a past session" sits far down the Futures screen | Its own "Replay" entry under My Progress. |
| Two calendars | Catalysts, Economic calendar | One "Big news today" card on Home; full list in Advanced. |
| Position size calculator and order preview | Paper trading | Merge (E4). |

Nothing is proposed for removal. Every feature stays reachable in Advanced mode.

---

## 4. Proposed menu: where each current screen goes

| New section | What a beginner sees (Simple) | What moves here (Advanced adds) |
|---|---|---|
| **Home** | Five cards: Is everything working? What is the market doing? Trade or wait? How much am I risking? What should I do next? | Recent decisions, automation log |
| **Charts** | Watch my TopstepX chart; Connect my chart | Chart lookup, screenshot check, Live Market (API), Scanner, stock overview, levels and indicators |
| **Practice** | My practice account, today's plan, "Practice this plan", open practice trades | Full order ticket, automated practice mode, sandbox |
| **My Progress** | How am I doing? (simple results), Review my trades, Can I trust it?, Learn | Journal analytics, Backtest, replay, evidence, research |
| **Settings** | My limits, My chart, Alerts | Data, simulator, fees, AI mentor, desktop, phone pairing, files and logs |

---

## 5. Proposed Home screen (Simple mode)

Top bar on every screen: **PRACTICE MODE: no real money** · health light · **Stop everything**.

| Card | Example content | Source (already exists) |
|---|---|---|
| 1. Is everything working? | "Yes. I can see your MNQ chart and it's updating." or "No. Your chart isn't updating. [Fix it]" | Visual Monitor status, market data status, automation status |
| 2. What is the market doing? | "Going up slowly. Price is above today's average." | Visual Monitor market read / futures analysis |
| 3. Trade or wait? | "**Wait.** The larger charts aren't agreeing yet." | Latest decision and its reason |
| 4. How much am I risking? | "Nothing right now. Today you can lose up to $400 before the app stops new practice trades." | Risk engine status and limits |
| 5. What should I do next? | "Keep watching. I'll tell you when something changes." | New rule table over existing state (A5) |

---

## 6. Simple and Advanced modes

- **Simple** is the default. Plain words, one main card per question, guided steps, risk information always visible.
- **Advanced** shows everything the app shows today, with today's terms.
- Switching modes changes only what is displayed. It must not change risk limits, trading permissions, the practice-only lock, calculations or stored data. A test should prove this by comparing the saved settings and the decision for the same input in both modes.
- The existing "Your level" setting (beginner / intermediate) for explanations would be folded into this switch.

---

## 7. Plain-language word list (proposed)

| Today | Simple mode |
|---|---|
| Market structure | Market direction |
| Multi-timeframe agreement | Do the charts agree? |
| Volatility / regime | How fast is the market moving? |
| Risk/reward, R | Possible gain vs. possible loss |
| Calibration required | Check chart settings |
| Stale / frozen | Chart isn't updating |
| Unreadable | Can't read the chart |
| Disconnected | Can't find the chart window |
| Drawdown | Money lost from your best point |
| Expectancy | Average result per trade |
| Profit factor | Money won for every $1 lost |
| Slippage | Price slip when the order fills |
| Max loss limit / room above max loss | Money left before the account fails |
| Daily loss limit | Most you can lose today |
| NO TRADE / WATCH_ONLY / REJECTED | Wait |
| Paper / sim / simulator | Practice |
| Walk-forward / out-of-sample | Tested on days it hadn't seen |
| Evidence tier | How well tested is this idea? |
| Data confidence | How sure am I that I'm reading the chart right? |
| VWAP | Today's average price |
| RTH | Main trading hours |

---

## 8. Beginner usability checklist

To be run with a real person who doesn't trade, on Windows, after each release. Pass means they manage it without help in the time shown.

| # | Task | Target | Status in 0.11.0 (expected, from this audit; not tested with a person) |
|---|---|---|---|
| 1 | Open the application | 10 s | Likely pass |
| 2 | Say what the first screen is telling them | 30 s | Likely fail (A4) |
| 3 | Connect a chart | 3 min | Likely fail (F2) |
| 4 | Say what the market is doing | 30 s | Likely fail (B9) |
| 5 | Say why the app says WAIT | 30 s | Likely fail (B1, D1) |
| 6 | Find their practice account | 20 s | Uncertain (E1) |
| 7 | Review a finished practice trade | 1 min | Uncertain (B10) |
| 8 | Find their loss limits | 30 s | Likely fail (F4) |
| 9 | Tell that the app is not working, and what to do | 20 s | Likely fail (C1, C4) |
| 10 | Say whether real money is involved | 5 s | Likely pass, but weak (C2) |

---

## 9. Suggested order of work (for approval; nothing started)

| Stage | What | Findings covered | Risk |
|---|---|---|---|
| 1 | Top bar: practice badge, health light, Stop everything, engine-offline banner | C1, C2, C4, C5 | Low |
| 2 | Plain-language layer: one word list used by every screen; WAIT reasons in plain words; status words | B1–B5, B8, B12, D1, D3, D5, G1 | Low |
| 3 | Home screen with five cards and the Next-step card | A4, A5, C6, C7 | Low |
| 4 | Five-section menu and Simple/Advanced switch | A1, A2, A3, A7, H1, H3 | Medium |
| 5 | "Connect your chart" walkthrough | F2, F3, G4 | Medium |
| 6 | One Settings section and "My limits" | F1, F4, F5, F6, A6 | Medium |
| 7 | Practice and My Progress tidy-up | E1–E4, B7, B10, G2, G3, H2, H4, H5 | Medium |

Stages 1 to 3 add screens and wording without moving anything, so they carry the least risk and remove most of the P1 problems. Each stage keeps all existing tests passing and adds tests that the practice-only lock, risk limits and stored data are unchanged.

No stage needs a new paid service, account or subscription.
