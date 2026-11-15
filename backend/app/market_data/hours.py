"""Which market a symbol belongs to and whether it's open right now, so prices are labelled by their OWN hours.

- Stocks and ETFs (SPY, AAPL): NYSE hours from the market clock (pre-market, regular, after hours, closed).
- Futures (Yahoo's NQ=F, ES=F, MNQ=F...): CME Globex, Sunday 6 PM to Friday 5 PM New York time with a daily break, holidays
  from exchange_calendars (app/futures/sessions.py). They trade on weekday evenings when stocks are closed.
- Crypto (BTC-USD, ETH-USD...): trades 24 hours a day, 7 days a week, including weekends.

Nothing here invents a price: a closed market keeps its last real price, labelled with when it was and when trading resumes.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..core.market_clock import MarketClock, Session

ET = ZoneInfo("America/New_York")
CRYPTO = re.compile(r"^[A-Z0-9]{2,10}-(USD|USDT|USDC|EUR|GBP)$")
FUTURES = re.compile(r"^([A-Z0-9]{1,4})=F$")
WEEKEND_MARKETS = [("BTC-USD", "Bitcoin"), ("ETH-USD", "Ethereum")]


def asset_kind(symbol: str) -> str:
    s = symbol.upper()
    if CRYPTO.match(s):
        return "crypto"
    if FUTURES.match(s):
        return "futures"
    return "stock"


def when_text(t: datetime) -> str:
    t = t.astimezone(ET)
    return f"{t:%a} {t.hour % 12 or 12}:{t:%M} {'AM' if t.hour < 12 else 'PM'} ET"


def _futures_state(symbol: str, now: datetime) -> dict:
    from ..futures import contracts as fc
    from ..futures.sessions import FuturesClock
    root = FUTURES.match(symbol.upper()).group(1)
    try:
        spec = fc.get(root)
    except Exception:  # noqa: BLE001 - unknown root: use a CME equity index product's hours
        spec = fc.get("ES")
    st = FuturesClock(spec).state(now)
    nxt = datetime.fromisoformat(st["next_open"]) if st.get("next_open") else None
    if st["state"] == "closed":
        weekend = "Weekend" in (st.get("reason") or "")
        return {"open": False, "label": "Closed for the weekend" if weekend else "Closed (daily break or holiday)",
                "reason": st.get("reason"), "next_open": nxt.isoformat() if nxt else None}
    closes = None
    if st.get("minutes_to_close") is not None:
        closes = (now + timedelta(minutes=st["minutes_to_close"])).isoformat()
    return {"open": True, "label": "Futures are trading", "reason": st.get("label"), "next_open": None, "closes_at": closes}


def market_state(symbol: str, clock: MarketClock | None = None, now: datetime | None = None) -> dict:
    """{"kind", "open", "label", "reason", "next_open" (ISO or None), "session" (for the price-label rules)}"""
    now = now or datetime.now(timezone.utc)
    kind = asset_kind(symbol)
    if kind == "crypto":
        return {"kind": kind, "open": True, "label": "Trades 24/7", "reason": "Crypto trades around the clock, weekends too.",
                "next_open": None, "session": Session.REGULAR}
    if kind == "futures":
        st = _futures_state(symbol, now)
        return {"kind": kind, **st, "session": Session.REGULAR if st["open"] else Session.CLOSED}
    if clock is None:
        from ..core.market_clock import shared_clock
        clock = shared_clock()
    s = clock.session_at(now)
    if s.session == Session.CLOSED:
        nxt = s.next_regular_open_et
        weekend = now.astimezone(ET).weekday() >= 5
        return {"kind": kind, "open": False, "label": "Closed for the weekend" if weekend else "Market closed",
                "reason": "The stock market is closed.", "next_open": nxt.isoformat() if nxt else None, "session": s.session}
    label = {Session.REGULAR: "Market open", Session.PREMARKET: "Pre-market", Session.AFTER_HOURS: "After hours"}.get(s.session, "Open")
    return {"kind": kind, "open": True, "label": label, "reason": None, "next_open": None, "session": s.session}


def closed_note(state: dict) -> str | None:
    if state.get("open") or not state.get("next_open"):
        return None
    return f"Opens {when_text(datetime.fromisoformat(state['next_open']))}"


def public(state: dict) -> dict:
    """For the API: the same, without the internal session enum."""
    out = {k: v for k, v in state.items() if k != "session"}
    out["session"] = state["session"].value if state.get("session") is not None else None
    out["opens_text"] = closed_note(state)
    return out
