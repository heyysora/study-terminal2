# Removing Alpaca (Nov 7, 2026)

Alpaca was removed completely. The app now needs no brokerage account, no brokerage integration, and no API keys.

## Inventory: every Alpaca dependency and what replaced it

| Where | What it did | Disposition |
|---|---|---|
| `market_data/alpaca_rest.py` | REST client: bars, snapshots, account, clock, calendar, data-plan check | **Deleted.** Bars and polling → `providers/yahoo.py`. Account → paper simulator. Calendar → local `exchange_calendars`. |
| `market_data/alpaca_stream.py` | Authenticated WebSocket trades/quotes/bars | **Deleted.** → `providers/yahoo_stream.py` (no auth). |
| `config.py` | `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, feed, URLs, 30-symbol limit, paper-URL guard | **Removed.** No credential settings remain. Old `ALPACA_*` values in `.env` are ignored. The paper-only guard is now structural: there is no broker client at all. |
| `market_data/service.py` | Alpaca connection, account verification, calendar load | **Rewritten** as `MarketMonitor`, which works with any provider. |
| `market_data/freshness.py` | IEX/SIP/delayed-SIP feed labels | **Rewritten** for provider-agnostic labels: REALTIME, NEAR_REALTIME, POLLING, DELAYED, HISTORICAL, STALE, UNAVAILABLE. |
| `market_data/types.py` | Alpaca feed coverage strings | **Replaced** with `ProviderInfo`, `SymbolFeedInfo`, `Tick`. |
| `core/market_clock.py` | Loaded holidays from Alpaca `/v2/calendar` | **Replaced** with the local NYSE calendar (no network). |
| `api/routes.py` | Alpaca error mapping, account in `/health` | **Rewritten.** Provider errors are generic. Paper routes added. |
| `cli.py` | `check` verified Alpaca keys, `stream --test` used Alpaca's test feed | **Rewritten.** `check` uses Yahoo. `stream BTC-USD` tests streaming on weekends. |
| `logging_setup.py` | Regex for `APCA-API-*` headers | **Generalized** to key/token/secret/password patterns. |
| `db/models.py` | `bars.feed` (iex/sip) | **Changed** to `bars.provider`. The old bar cache table is dropped and rebuilt on first start (watchlists kept). |
| `tests/` | Alpaca REST mocks, fake Alpaca WebSocket server | **Deleted.** Replaced with Yahoo provider tests, a fake Yahoo stream server, paper engine tests, and end-to-end tests with a fake provider. |
| `.env.example`, `scripts/setup.ps1`, `scripts/check.ps1` | Asked for Alpaca keys | **Rewritten.** `.env` is optional. |
| `README.md`, `FEATURES.md`, `docs/ARCHITECTURE.md` | Alpaca setup, pricing, limits | **Rewritten.** |

What remains: one comment in `db/session.py` explains the migration of the old bar cache.

## Features affected

None were removed. Here's what changed underneath:

- **Live monitoring:** Yahoo's unofficial streaming socket plus 1-minute polling, instead of Alpaca's IEX stream.
- **Paper trading:** a local simulator instead of Alpaca's paper account. It's now available *earlier* (originally Stage 9).
- **Short-sale data:** without a broker, borrow availability, borrow fees, and short-sale restrictions can't be checked. The simulator says so on every short.
