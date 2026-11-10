# Changelog

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
