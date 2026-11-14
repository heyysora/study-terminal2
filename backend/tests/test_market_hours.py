"""Each market by its own hours: stocks (NYSE), futures (CME Globex, weekday evenings too), crypto (24/7, weekends included).
Prices are never invented: a closed market keeps its last real price, labelled with when trading resumes."""
from datetime import UTC, datetime, timedelta

import httpx

from app import home
from app.core.market_clock import MarketClock
from app.market_data.freshness import FreshnessTracker
from app.market_data.hours import asset_kind, closed_note, market_state, public
from app.market_data.providers.base import StreamState
from app.market_data.types import ProviderInfo, Tick

SAT = datetime(2026, 11, 14, 18, 30, tzinfo=UTC)       # Saturday 1:30 PM New York
SUN_EVE = datetime(2026, 11, 16, 1, 0, tzinfo=UTC)     # Sunday 8:00 PM New York
MON_BREAK = datetime(2026, 11, 16, 22, 30, tzinfo=UTC) # Monday 5:30 PM New York (CME daily break)
TUE = datetime(2026, 11, 17, 15, 0, tzinfo=UTC)        # Tuesday 10:00 AM New York


def st(sym, now):
    return public(market_state(sym, MarketClock(), now))


def test_kinds():
    assert [asset_kind(s) for s in ("SPY", "AAPL", "NQ=F", "MNQ=F", "BTC-USD", "ETH-USD")] == \
        ["stock", "stock", "futures", "futures", "crypto", "crypto"]


def test_each_market_by_its_own_hours():
    assert not st("SPY", SAT)["open"] and st("SPY", SAT)["opens_text"] == "Opens Mon 9:30 AM ET"
    assert not st("NQ=F", SAT)["open"] and st("NQ=F", SAT)["opens_text"] == "Opens Sun 6:00 PM ET"
    assert st("BTC-USD", SAT)["open"] and st("BTC-USD", SAT)["label"] == "Trades 24/7"
    assert not st("SPY", SUN_EVE)["open"] and st("NQ=F", SUN_EVE)["open"]          # futures reopen Sunday evening
    assert not st("NQ=F", MON_BREAK)["open"] and st("NQ=F", MON_BREAK)["opens_text"] == "Opens Mon 6:00 PM ET"
    assert all(st(s, TUE)["open"] for s in ("SPY", "NQ=F", "BTC-USD"))


def test_crypto_price_is_live_on_a_saturday_and_stocks_are_labelled_closed():
    tr = FreshnessTracker(ProviderInfo(name="yahoo", display_name="Yahoo"), poll_interval_s=30, streaming_enabled=True)
    tr.set_stream_state(StreamState.CONNECTED, "ok")
    tr.on_tick(Tick(symbol="BTC-USD", price=65900.0, ts=SAT - timedelta(seconds=3), received_at=SAT, provider="yahoo", source="yahoo-stream"))
    tr.on_tick(Tick(symbol="SPY", price=749.6, ts=SAT - timedelta(hours=17), received_at=SAT, provider="yahoo", source="yahoo-poll"))
    btc = market_state("BTC-USD", MarketClock(), SAT)
    spy = market_state("SPY", MarketClock(), SAT)
    assert tr.label("BTC-USD", btc["session"], SAT).status.value == "near_realtime"
    lab = tr.label("SPY", spy["session"], SAT, closed_note=closed_note(spy))
    assert lab.status.value == "historical" and "Opens Mon 9:30 AM ET" in lab.reason


def test_home_says_closed_with_the_real_last_result():
    hours = {"open": False, "label": "Closed for the weekend", "opens_text": "Opens Mon 9:30 AM ET", "next_open": "2026-11-16T09:30:00-05:00"}
    last = {"close": 754.37, "change_pct": -0.36, "day": "On Friday", "name": "S&P 500 fund, SPY", "as_of": None}
    mk = home.market(trades="stocks", visual=None, signals_market=None, hours=hours, last_session=last)
    assert mk["closed"] and mk["sentence"] == "The stock market is closed for the weekend. Opens Mon 9:30 AM ET."
    assert "finished down 0.36%" in mk["details"][0] and "754.37" in mk["details"][0] and mk["opens_at"]
    mk2 = home.market(trades="futures", visual=None, signals_market=None, hours=hours, last_session=None)
    assert mk2["sentence"].startswith("Futures are closed") and not any("finished" in d for d in mk2["details"])   # nothing made up
    h = home.health(trades="stocks", db_ok=True, monitor={"healthy": True}, visual=None, automation=None, profiles=0, backup=None,
                    hours=hours)
    assert "closed for the weekend" in h["sentence"] and "arriving" not in h["sentence"]


async def test_viewed_symbol_is_followed_then_lapses(settings):
    from app.main import create_app

    from .test_futures_api import FutProvider, always_open_clock
    app = create_app(settings, provider=FutProvider(), clock=always_open_clock(), start_loops=False)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers={"X-Study-Terminal": "1"}) as c:
            m = app.state.monitor
            r = (await c.post("/api/market/view/BTC-USD")).json()
            assert r["following"] and r["market"]["kind"] == "crypto" and "BTC-USD" in m.monitored_symbols()
            assert m.signals_allowed("BTC-USD")[0] is False                       # watch only
            s = (await c.get("/api/market/state/NQ=F")).json()
            assert s["kind"] == "futures" and {x["symbol"] for x in s["open_now"]} == {"BTC-USD", "ETH-USD"}
            m.viewing["BTC-USD"] = 0                                              # the page stopped renewing it
            assert "BTC-USD" not in m.monitored_symbols()
