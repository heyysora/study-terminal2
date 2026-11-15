# Multi-market intelligence + iPhone companion: Stage 1 audit and plan

Written 2026-11-14 against Study Terminal 0.15.0. Nothing in this plan has been built yet. Stage 2 starts only after the four decisions in section 9 are answered.

The brief I received ends mid-sentence in section 16 ("Deliverables ... - Secure"). Everything before that is covered here. If the cut-off part held more requirements, send it and I'll fold it in.

## 1. The short version

- Most of the Windows side already exists in some form. The work is joining it up into one scanner with one status, adding crypto paper trading, and widening the memecoin engine.
- A native SwiftUI app can be built without a Mac, on GitHub's macOS machines, for free (this repository is public, and public repositories get those machines at no charge).
- The hard limit is notifications. Apple only lets an app receive push notifications if it's signed by a paid Apple Developer Program membership ($99 a year). A free Apple ID can't sign for push at all, and apps signed with it stop opening after 7 days.
- So "$0 a month, native app, notifications while the app is closed" can't all be true for our own app on a free Apple ID. There are two honest ways through, and you pick one in section 9:
  - **Free route:** our app shows everything; a separate free App Store app (ntfy) delivers the notifications, and tapping one opens ours. $0 forever. The app needs re-signing from your PC every 7 days.
  - **$99-a-year route:** our own app receives the notifications directly from your PC, and stays installed for a year at a time. No monthly cost, one yearly fee to Apple.
- When your PC is asleep, off or offline, nothing is being scanned and nothing can be sent. The phone will say so in plain words; it will never show "monitoring" from an old reading.

## 2. What is in the repository today

About 25,300 lines of Python (FastAPI, SQLite), 5,100 lines of React/TypeScript, 62 test files with 552 tests. Windows installer built and checked on GitHub's Windows machine each release (39 install, upgrade and recovery checks).

| Brief section | What already exists | State |
|---|---|---|
| Windows engine as the centre | `backend/app/main.py` starts every service on launch; loops for scanner, signals, news, futures, health, memecoins | Works. No single "is it monitoring?" status yet: each part reports its own. |
| Monitoring status | `home.py` health line (Working / Needs attention / Stopped), `watchdog.py`, feed-health alerts, System health page, startup history | Close. Needs the five states from the brief and a per-market breakdown. |
| Futures (MNQ, NQ, MES, ES, MYM, YM, M2K, RTY, GC, CL) | `futures/` (20 files): contracts, sessions, setups, signals, paper account, prop-firm rules, replay, research | Works. Kept as is. |
| TopstepX visible-screen monitoring | `screen/`, `validation/`, Chrome extension, Visual Monitor | Works. Kept as is. No TopstepX API subscription is used or needed. |
| Major crypto | Yahoo candles around the clock; live prices for 8 coins from public exchange data (ccxt, read-only, new in 0.15.0); market-hours logic knows crypto never closes | **Watch only.** No crypto signals and no crypto paper trading yet (`signals_allowed` is false for crypto by design). |
| Memecoin discovery | `memecoins/sources.py` + `service.py`: DexScreener newest-profile and most-promoted feeds, search, live rows | Partly. It lists what DexScreener promotes. It doesn't yet scan on its own or rank by real activity. |
| Memecoin risk | `memecoins/checks.py`: mint and freeze authority, Token-2022 traps, pool size, age, selling pressure, top-10 holders, links, pump.fun stage. Never says "safe". | Partly. Missing: creator wallet, bundled buys, wash trading, liquidity-withdrawal watch, sell-restriction (honeypot) test, the five-level scale. |
| Signals | `signals/engine.py` (stocks, 10 setups, evidence tiers), `futures/signals.py`; actions BUY, SHORT, WAIT, NO TRADE with entry, stop, targets, reasons | Works for stocks and futures. Not unified across markets; no EXIT or SELL as first-class signals; quality score exists as evidence tiers, not a single number. |
| Exit intelligence | Stops and targets on paper positions; memecoin exit plans (part-sell, trailing stop); close-of-day reminder | Mechanical exits only. No "this idea is no longer valid" analysis, and exits aren't scored separately. |
| Paper trading | Stocks (`paper/`), futures (`futures/paper.py`), memecoins (`memecoins/practice.py`) with slippage, fees, price impact, daily loss limits, trade limits | Works for three markets. **None for major crypto.** |
| Phone API | `api/routes_mobile.py`: off by default, one token (only its hash stored), lockout after bad tokens, status + alerts + pause/resume/emergency stop | Small and safe, but: one shared token (no per-device revoke), no pairing by QR, app listens on 127.0.0.1 only, phone can't request paper trades. |
| Notifications | `alerts/service.py`: Windows toasts and sounds, history, duplicate suppression by key and fingerprint | Windows only. No phone delivery, no quiet hours, no per-category switches. |
| Journal | Stock/futures journal with screenshots, memecoin practice journal | Works on the PC. |
| Safety | Real orders impossible: no broker order code, safety audit tests, live mode can't be switched on, ccxt locked to public prices | Kept, and extended to the phone API in every stage. |

Things the brief asks for that don't exist at all: the iOS app, device pairing, a LAN listener with encryption, phone notifications, crypto paper trading, signal tracking for untraded signals across all markets (futures has some; stocks and memecoins don't).

## 3. Findings that shape the design (checked 2026-11-14)

**Apple signing and push**
- A free Apple ID ("Personal Team") can install an app on your own iPhone, but the app stops opening after 7 days and has to be re-signed; at most 3 such apps at once.
- Free signing does not support the Push Notifications capability. Apple staff confirm this on Apple's developer forum: push is part of the paid Developer Program.
- With the paid program ($99 a year), profiles last a year and push works. The PC can talk to Apple's push service directly with a key file; no server in between is needed. I'll verify the exact steps in Stage 9 before building on them.

**Building without a Mac**
- GitHub's standard macOS machines are free and unlimited for public repositories, and this repository is public. The same workflow that builds the Windows installer can build the iOS app.
- Without a paid account the build produces an unsigned IPA. You then sign and install it from Windows with a sideloading tool and your Apple ID. I know of two such tools (AltStore, Sideloadly) but haven't re-checked how they behave today; that's a Stage 10 task, and I won't promise it works until I've seen it documented.
- I can compile the app and run its unit tests on GitHub's machines. I can't see it running on a real iPhone. That part is yours to confirm, same as with Windows.

**Free notifications that arrive while the app is closed**
- iOS doesn't let a closed app poll in the background reliably. The only dependable route is Apple's push service.
- ntfy is a free, open-source notification service with an iPhone app on the App Store. The PC sends a message to a topic on ntfy.sh; ntfy's own servers pass it through Apple's push service; it arrives with the app closed. Messages can carry a link, so tapping one can open Study Terminal on the right screen.
- Costs and caveats: free, no account. A topic on the public server is only as private as its name, so we'd use a long random name and keep account numbers out of messages. The free server has daily limits I'll measure in Stage 2. It's someone else's server, so delivery isn't guaranteed.

**Reaching the PC from outside your home**
- Same Wi-Fi: direct connection, encrypted, no extra software.
- On cellular: the PC is not reachable unless something bridges it. Tailscale's Personal plan is free (up to 6 users, unlimited devices, non-commercial use) and makes the PC reachable from the phone privately, without opening the PC to the internet. The existing phone API was already written with this in mind.
- Notifications through ntfy or Apple arrive on cellular either way; it's only opening live data in the app that needs Tailscale away from home.

**pump.fun and FOMO**
- pump.fun publishes documentation for its on-chain programs and SDKs for sending transactions. It doesn't run a documented data API; the addresses its own website calls are undocumented. I won't build on those. Memecoin data stays on DexScreener and the public Solana chain, as now.
- "FOMO" is almost certainly the social trading app at fomo.family (Solana and other chains, copy-trading). It lists no public API. Its trades can be read from the chain through a third-party paid-tier service, which breaks the $0 rule. Plan: no FOMO integration. If you meant something else by FOMO, tell me.

## 4. Target architecture

```
                 WINDOWS PC  (the only place analysis happens)
 ┌───────────────────────────────────────────────────────────────────┐
 │ Data adapters      Scanners           Engines           Stores    │
 │  Yahoo (stocks,     futures scan       risk engine       SQLite   │
 │   futures proxy)    crypto scan        signal engine      signals │
 │  exchanges (ccxt,   memecoin scan      exit engine        trades  │
 │   read-only)                           paper accounts     devices │
 │  DexScreener                                              alerts  │
 │  Solana public RPC        Monitor supervisor                      │
 │  TopstepX screen     MONITORING / PAUSED / CONNECTING /           │
 │                      DATA UNAVAILABLE / ERROR  (per market + all) │
 │                                                                   │
 │  Notification hub: categories, priority, cooldown, quiet hours,   │
 │  duplicate suppression, history ──► Windows toast                 │
 │                                 ──► phone channel (ntfy or APNs)  │
 │                                                                   │
 │  Companion API v1 (separate listener, encrypted, per-device keys) │
 └───────────────────────────────┬───────────────────────────────────┘
                                 │  same Wi-Fi, or Tailscale when away
                 ┌───────────────┴────────────────┐
                 │ iPhone app (SwiftUI)           │  shows, asks, never analyses
                 │ Home · Markets · Opportunities │
                 │ Journal · Settings             │
                 └────────────────────────────────┘
```

Rules that hold across every stage:

1. The phone never computes a signal, a risk level or a fill. It displays what the PC sent, with the PC's timestamp and freshness.
2. Every paper-trade request from the phone goes through the same checks as one made on the PC. The phone can't change risk limits, can't clear an emergency stop, and there is nothing it could send that reaches a broker, exchange or wallet, because the PC has no such code.
3. The PC works the same with no phone paired.
4. Every screen that shows a price says where it came from and how old it is. Old data is labelled old, on the PC and on the phone.

### 4.1 Monitor supervisor (Stage 3)

One object that owns the answer to "is Study Terminal watching the market right now?".

- States: MONITORING, PAUSED (you paused it, or Stop everything), CONNECTING (starting up or retrying), DATA UNAVAILABLE (source down, rate-limited, or data too old), ERROR (a scanner crashed).
- Tracked per market (futures, stocks, crypto, memecoins) and rolled up to one overall state: the overall state is never better than the worst market you've switched on.
- Inputs: last successful fetch per source, age of the newest price, rate-limit responses, scanner heartbeat, internet check, invalid-data counters.
- A heartbeat is saved every minute. On the next start, a gap in heartbeats is reported as "Not monitoring from 11:42 PM to 7:05 AM (PC asleep or off)". This is how sleep and shutdown become visible afterwards, since nothing can run during them.
- The phone shows the PC's last heartbeat time. If it's older than two minutes the phone says "Your PC isn't reachable. Nothing is being monitored that I can confirm," whatever the last known state was.

### 4.2 Markets and data (Stages 2 and 3)

| Market | Source | Freshness | Known limits |
|---|---|---|---|
| Futures | Yahoo continuous contracts (delayed, labelled as such); your TopstepX chart through the screen monitor | Yahoo: delayed. Screen: what's visible. | Yahoo data is never called live futures data. |
| Stocks | Yahoo stream and polling | Near real-time in market hours | Unofficial source. |
| Major crypto | Kraken, Coinbase, Bitstamp public data through ccxt (read-only) | Seconds | 8 coins today; Stage 2 decides the liquidity bar for adding more. |
| Memecoins | DexScreener; Solana public RPC | 10–30 s | Free RPC refuses some holder queries; rate limits measured in Stage 2. |

Stage 2 produces `docs/DATA_SOURCES_AUDIT.md`: for each source, the documented or measured rate limit, delay, coverage, licence and commercial-use terms, and what breaks without it. Every endpoint gets called before it's relied on, as was done for DexScreener.

### 4.3 Memecoin discovery (Stage 4)

A scanner of its own, running every 30–60 seconds while memecoins are switched on.

- Intake: DexScreener's newest profiles, boosts and search for pump.fun and PumpSwap pairs; later, new-pool events from the chain if the free RPC allows it.
- Each token gets a snapshot per scan (price, pool size, volume, buys, sells, holders where available) so changes over time can be measured. Snapshots are pruned after a few days.
- Activity score from several things together: unique-looking trade counts, buy/sell balance, volume against pool size, pool growth, age, and whether price is rising on rising or falling activity. Price change alone never ranks a token, and a token with thin or missing data is ranked below one with complete data.
- Fields the free sources can't give (creator wallet history, wallet relationships) are listed as "not available" on the token, and count against it.

### 4.4 Memecoin risk engine (Stage 4)

Separate from discovery; discovery can't promote what risk has rejected.

- Scale: LOWER DETECTED RISK, MODERATE RISK, HIGH RISK, EXTREME RISK, INSUFFICIENT INFORMATION. The word "safe" doesn't appear anywhere.
- Kept: mint authority, freeze authority, Token-2022 traps, pool size, age, selling pressure, top holders, links, stage.
- Added, each only as far as free data honestly supports it:
  - Liquidity withdrawal: pool size falling fast between snapshots (available).
  - Concentration and creator share: from largest-holder data (available when the RPC answers).
  - Bundled buys and coordinated wallets: many buys in the same moment at launch (needs transaction history; Stage 2 decides whether the free RPC can supply it).
  - Wash trading and artificial volume: volume far above what the pool and trade counts could produce, and buys matching sells too neatly (heuristic, labelled as such).
  - Sell restrictions (honeypot): can't be proven without simulating a sale. Reported as a warning sign when buys happen but almost no sells succeed; otherwise "not tested".
- Missing checks lower confidence. Any unresolved critical item (mint or freeze authority, EXTREME, or INSUFFICIENT INFORMATION) blocks a BUY signal outright.

### 4.5 Unified signal engine (Stage 5)

One record shape for every market:

`asset, market, action, observed_price, observed_at, source, freshness, entry_zone, invalidation, targets, risk_reward, quality_score, risk_class, explanation, strategy, venue`

- Actions: BUY, SELL, SHORT, EXIT, WAIT, NO TRADE. SELL means "close or reduce something you hold". SHORT means "open a position that profits from a fall". They're different actions with different rules.
- SHORT is only issued where the paper venue supports it: futures yes, stocks yes (as now), spot crypto no, memecoins no.
- Quality score 0–100 says how many of a setup's own conditions are met and how clean the data is. It's labelled "setup quality, not a chance of winning" everywhere, including on the phone. No win probabilities are produced. The existing odds check stays what it is: a replay of past days, labelled as that.
- Each market keeps its own configuration: futures and stocks keep their existing setups; crypto gets a small, separate set tuned for a market that never closes; memecoins get activity-plus-risk rules.
- Stale or unreliable data produces WAIT or NO TRADE, never a confident action, and never a phone alert that sounds confident.
- Every signal is saved whether or not you act on it, and followed afterwards (did it reach target or invalidation first). That gives signal results independent of your own trades.

### 4.6 Exit intelligence (Stage 5)

A separate engine that looks at open paper positions and at signals still marked active.

- Watches: momentum fading, trend flip on the signal's timeframe, a support or resistance level failing, target or stop reached, volatility jumping, and for memecoins a risk event (pool shrinking, a large holder selling).
- Output is an EXIT or SELL signal with the reason in one sentence, or an "idea no longer valid" notice for a signal you didn't take.
- Exit calls are scored on their own: what happened to price after each one.

### 4.7 Paper trading (Stage 6)

- New: a crypto paper account (spot, long only) with exchange-style fees and spread-based slippage, daily loss limit and trade limits like the others.
- Existing stock, futures and memecoin accounts stay as they are.
- A fill is always shown as "simulated fill", next to the observed price it was based on.
- One risk gate checks every order from every door (PC screen, phone). The phone's requests are previews first, then a confirm.

### 4.8 Companion API and pairing (Stage 7)

- A second listener, separate from the app's own local one, off until you switch on "Phone access". It serves only `/companion/v1/*`. The main app stays on 127.0.0.1.
- Encryption: the PC creates its own certificate on first use. The pairing QR code carries the PC's address, a one-time code that expires in a few minutes, and the certificate's fingerprint. The phone only ever trusts that fingerprint, so a different machine on the network can't pose as your PC.
- Each paired phone gets its own key (stored in the iPhone Keychain; only a hash on the PC). The PC lists paired devices with last-seen time; removing one cuts it off at once.
- Every request is authenticated; there's no open endpoint, not even a "hello". Repeated failures lock out the sender, as the current phone API does.
- Endpoints (read): status and monitor state, markets, opportunities, signal detail, positions, account summaries, journal, alerts history, settings. (Write): pause/resume, emergency stop, paper order preview, paper order confirm, notification preferences. Not offered: risk-limit changes, clearing an emergency stop, anything about backups or data.
- The existing `/api/mobile/*` endpoints stay working for one release, then fold into v1.

### 4.9 iPhone app (Stage 8)

- Swift and SwiftUI only, Apple's own frameworks (URLSession, Keychain, UserNotifications, Swift Charts, camera for the QR code). No third-party packages unless a stage shows one is needed, and then only with a compatible open licence.
- Five tabs: Home, Markets, Opportunities, Journal, Settings, with the contents listed in the brief.
- Written for someone who has never traded: the same plain words as Simple mode on the PC, "practice money" on every screen that shows a balance, and every price with its age.
- The project file is generated from a small text spec in the repository, so the whole thing can be maintained from Windows.
- Tests that run on GitHub's Mac: decoding of every API reply, the freshness and status wording, pairing logic. What can't be tested there: the camera, real notifications, a real iPhone.

### 4.10 Notifications (Stage 9)

On the PC, one hub in front of every channel:

- The 13 categories from the brief, each with its own on/off switch and priority.
- Duplicate suppression per setup (same asset, action and setup don't alert twice), a cooldown per asset, quiet hours with an exception for stop-loss, rug warning and monitoring-stopped.
- A confident signal alert is never sent on stale data; it's held or downgraded to a plain "data is old" note.
- History kept on the PC and shown on the phone, each entry linking to the opportunity it's about.
- "Desktop monitoring stopped" can only be sent while the PC is still running (for example when a data source dies). If the PC loses power or sleeps, it can't send anything. The app covers that from the other side: when opened it shows how long ago the PC was last heard from. I won't describe this as guaranteed delivery.

Phone channel, depending on your choice in section 9:

- **Free route (ntfy):** PC posts to your private ntfy topic; the ntfy app shows the notification; tapping opens Study Terminal at the right place. Messages carry asset, action and one line of why, no balances.
- **$99-a-year route (Apple push):** PC signs and sends directly to Apple; the notification belongs to our app and opens it natively. If you start on the free route, moving later is a settings change and a re-install, not a rewrite: the hub is the same.

### 4.11 Reliability (all stages)

PC shutdown and sleep (heartbeat gaps, reported on next start and on the phone), internet loss, source outages, rate limits (back off, say so), phone disconnection (app reconnects on its own and shows last-updated time), expired or revoked device keys (clear message, re-pair), invalid data (dropped and counted), duplicates, stale prices, restart and recovery (existing backup and recovery system untouched; new tables are additions, so older data files open as they are).

## 5. What it costs

| Item | Free route | $99-a-year route |
|---|---|---|
| Monthly software and services | $0 | $0 |
| Apple | $0 | $99 per year, paid to Apple |
| Market data | $0 | $0 |
| Build machines (GitHub, public repo) | $0 | $0 |
| Notifications | $0 (ntfy public server) | $0 (Apple push direct from your PC) |
| Remote access (optional) | $0 (Tailscale Personal) | $0 |

Nothing paid is added without asking you first. Each stage's notes list every new dependency and its licence.

## 6. What I can and can't verify

| | Here (Linux) | GitHub Windows | GitHub Mac | Your PC / iPhone |
|---|---|---|---|---|
| Scanners, engines, API, paper accounts | Yes | Yes | – | Only you |
| Windows installer, upgrade, recovery | – | Yes | – | Only you |
| iOS app compiles, unit tests pass | – | – | Yes | – |
| App on a real iPhone, pairing by camera, notifications arriving | No | No | No | Only you |
| Strategy quality on real markets | Never by software tests. Only by tracked signals over time. | | | |

Synthetic tests prove the software does what it's written to do. They prove nothing about whether a setup makes money, and no setup will be called profitable or validated on their strength.

## 7. Stages and what ends each one

| Stage | Delivers | Done when |
|---|---|---|
| 1 | This plan | You've answered section 9. |
| 2 | `docs/DATA_SOURCES_AUDIT.md`: every free source called and measured; ntfy limits; APNs steps confirmed; sideloading tools confirmed | Each source has a verdict: use, use with limits, or don't use. |
| 3 | Monitor supervisor, five states per market, heartbeat and gap reporting, crypto scanning, autostart setting | Tests for every failure in brief section 2; Windows build passes. |
| 4 | Memecoin discovery scanner and five-level risk engine | Tests with recorded real responses; a week of real observations logged, labelled as observations. |
| 5 | Unified signal record, crypto setups, exit engine, tracking of untraded signals | Tests; SHORT impossible on venues without it; stale data can't produce a confident signal. |
| 6 | Crypto paper account; one risk gate for all doors | Tests for fills, fees, limits. |
| 7 | Companion API v1, encrypted listener, QR pairing, device list and revoke | Tests for every endpoint without a key, with a revoked key, with a wrong certificate. |
| 8 | SwiftUI app source and project, built on GitHub's Mac | Compiles; unit tests pass; unsigned IPA produced. |
| 9 | Notification hub, phone channel, quiet hours, history, deep links | Tests for duplicates, cooldown, quiet hours, stale-data hold; you confirm one arrives on your phone. |
| 10 | Signing, IPA, install guide from Windows, full test report | You install it and pair it. |

Each stage is released as its own Windows version, with the usual Windows checks, before the next begins.

## 8. Risks worth knowing now

- **The 7-day re-sign on the free route.** If it's skipped, our app stops opening until re-signed. ntfy notifications keep arriving because ntfy is a normal App Store app.
- **Free data can change or throttle without notice.** Every source has a fallback or an honest "unavailable" state; none is assumed permanent.
- **Memecoin checks are partial by nature.** Several of the brief's items (wallet relationships, honeypots, creator history) can only be approximated with free data. They'll be labelled as approximations or as not available.
- **The repository is public.** The iOS source and this plan are visible to anyone. No secrets go into it; device keys and certificates live only on your PC and phone.
- **ccxt.** It stays locked to public prices. Crypto paper trading in Stage 6 uses those prices and a simulated account; it adds no exchange account, keys or order code.

## 9. Four decisions I need from you

1. **Notifications:** free route (ntfy app delivers them, our app re-signed weekly) or $99-a-year route (our app receives them directly, yearly signing)? You can start free and switch later.
2. **FOMO:** is fomo.family the platform you meant? If so, it has no public API and I'd leave it out. If you meant something else, which?
3. **Away from home:** install Tailscale (free) on the PC and phone so the app works on cellular, or keep the app Wi-Fi-only and rely on notifications when you're out?
4. **Crypto coverage:** start crypto signals and paper trading with Bitcoin, Ethereum and Solana only, then add coins that pass a liquidity bar set in Stage 2? (My suggestion: yes.)

## Sources

- Apple Developer Forums, "Personal development teams do not support the Push Notifications capability": https://developer.apple.com/forums/thread/811929
- Free Personal Team limits (7 days, capabilities): https://takazudo-zudo-tauri.pages.dev/pj/zudo-tauri/docs/mobile/ios-signing-free-team
- GitHub-hosted runners, free for public repositories: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
- ntfy (open source, free public server, iOS app): https://github.com/binwiederhier/ntfy and https://docs.ntfy.sh/faq/
- Tailscale Personal plan limits: https://www.ssdnodes.com/learn/is-tailscale-free-plan-limits
- FOMO has no public API: https://docs.bitquery.io/docs/blockchain/Solana/fomo-api/
- pump.fun publishes program docs, not a data API: https://coinpaprika.com/education/pumpfun-api-solana-dex-data/
