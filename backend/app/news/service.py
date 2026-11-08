"""News and catalyst monitoring.

Polls Yahoo news for your watchlist and open positions (every 10 minutes in premarket/regular hours),
refreshes earnings and analyst data every few hours, and keeps the macro calendar (FOMC, BEA, BLS).

How catalysts affect the rest of the app (all shown to you as reasons, never hidden):
  - Signals within 15 minutes before or after a high-importance scheduled release (FOMC decision,
    CPI, jobs report, GDP, PCE) become watch-only: the first minutes after a release are whipsaw.
  - Earnings today after the close or tomorrow before the open: a risk note on every signal
    (holding overnight means gap risk the stop can't protect against).
  - The session right after an earnings release: a note that ranges run larger than usual.
  - The scanner shows catalysts next to each symbol and gives a small, labelled boost for a fresh,
    confirmed, high-relevance catalyst. Direction is never inferred from the news.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import desc, select

from ..core.market_clock import ET
from ..db.models import NewsItemRecord
from .sources import (bls_events, event_datetime, fetch_text, parse_analyst, parse_bea, parse_earnings, parse_fomc,
                      parse_yahoo_news)

log = logging.getLogger(__name__)
NEWS_TTL = 600
SLOW_TTL = 6 * 3600
MACRO_TTL = 24 * 3600
GATE_MINUTES = 15
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BEA_URL = "https://www.bea.gov/news/schedule"


class NewsService:
    def __init__(self, db, provider, clock, alerts=None, symbols_fn=lambda: [], enabled: bool = True):
        self.db, self.provider, self.clock, self.alerts, self.symbols_fn = db, provider, clock, alerts, symbols_fn
        self._news: dict[str, tuple[float, list]] = {}
        self._slow: dict[str, tuple[float, dict]] = {}
        self._macro: dict = {"events": [], "fetched_at": None, "errors": {}, "bls": None}
        self._macro_t = 0.0
        self._task: asyncio.Task | None = None
        self.enabled = enabled
        self.errors: list[str] = []

    # ---------------- lifecycle ----------------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        await asyncio.sleep(20)
        while True:
            try:
                await self.macro()
                await self.econ_values()
                sess = self.clock.session_at().session.value
                if self.enabled and sess in ("premarket", "regular"):
                    for sym in list(self.symbols_fn())[:40]:
                        await self.catalysts(sym)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("news loop failed")
            await asyncio.sleep(NEWS_TTL)

    async def _limit(self, n: int = 1) -> None:
        lim = getattr(self.provider, "limiter", None)
        if lim is not None:
            await lim.acquire(n)

    # ---------------- per-symbol ----------------

    @staticmethod
    def _yf_news(symbol: str):
        import yfinance as yf
        return yf.Ticker(symbol).news

    @staticmethod
    def _yf_slow(symbol: str):
        import yfinance as yf
        t = yf.Ticker(symbol)
        out = {}
        for k in ("calendar", "earnings_dates", "upgrades_downgrades"):
            try:
                out[k] = getattr(t, k)
            except Exception as e:  # noqa: BLE001 - Yahoo returns odd errors for ETFs etc.
                out[k] = None
                out[f"{k}_error"] = f"{type(e).__name__}: {e}"[:200]
        return out

    async def news(self, symbol: str, force: bool = False) -> list[dict]:
        symbol = symbol.upper()
        now = asyncio.get_running_loop().time()
        hit = self._news.get(symbol)
        if hit and not force and now - hit[0] < NEWS_TTL:
            return hit[1]
        await self._limit()
        try:
            raw = await asyncio.to_thread(self._yf_news, symbol)
            items = [i.to_dict() for i in parse_yahoo_news(raw, symbol)]
        except Exception as e:  # noqa: BLE001
            msg = f"{symbol} news: {type(e).__name__}: {e}"[:200]
            self.errors = (self.errors + [msg])[-20:]
            if hit:
                return hit[1]
            raise
        new = self._store(items)
        self._news[symbol] = (now, items)
        self._alert_new(symbol, [i for i in items if i["id"] in new])
        return items

    async def slow(self, symbol: str, force: bool = False) -> dict:
        symbol = symbol.upper()
        now = asyncio.get_running_loop().time()
        hit = self._slow.get(symbol)
        if hit and not force and now - hit[0] < SLOW_TTL:
            return hit[1]
        await self._limit(3)
        raw = await asyncio.to_thread(self._yf_slow, symbol)
        earnings = parse_earnings(raw.get("calendar"), raw.get("earnings_dates"), symbol)
        analyst = [i.to_dict() for i in parse_analyst(raw.get("upgrades_downgrades"), symbol)]
        data = {"earnings": earnings, "analyst": analyst,
                "errors": {k: v for k, v in raw.items() if k.endswith("_error")}}
        self._slow[symbol] = (now, data)
        return data

    def cached(self, symbol: str) -> dict:
        """What's already loaded for a symbol (no network)."""
        sym = symbol.upper()
        slow = (self._slow.get(sym) or (0, {}))[1] or {}
        out = {"symbol": sym, "news": (self._news.get(sym) or (0, []))[1], "earnings": slow.get("earnings"),
               "analyst": slow.get("analyst", []), "events": self.event_risk(sym, earnings=slow.get("earnings"))}
        if not self.enabled:
            out["disabled"] = True
        return out

    async def catalysts(self, symbol: str, force: bool = False) -> dict:
        symbol = symbol.upper()
        if not self.enabled:
            return {**self.cached(symbol), "news_error": "News monitoring is turned off (NEWS_ENABLED=false)."}
        out: dict = {"symbol": symbol, "fetched_at": datetime.now(timezone.utc).isoformat()}
        try:
            out["news"] = await self.news(symbol, force)
        except Exception as e:  # noqa: BLE001
            out["news"], out["news_error"] = [], f"Couldn't load news from Yahoo ({type(e).__name__}). This doesn't mean there is none."
        try:
            s = await self.slow(symbol, force)
            out["earnings"], out["analyst"] = s["earnings"], s["analyst"]
            if s["errors"]:
                out["partial"] = s["errors"]
        except Exception as e:  # noqa: BLE001
            out["earnings"], out["analyst"] = None, []
            out["slow_error"] = f"Couldn't load earnings/analyst data ({type(e).__name__})."
        out["events"] = self.event_risk(symbol, earnings=out.get("earnings"))
        if not out["news"] and "news_error" not in out:
            out["news_note"] = f"Yahoo returned no recent headlines for {symbol}. That doesn't mean nothing happened."
        return out

    def _store(self, items: list[dict]) -> set[str]:
        if not items:
            return set()
        with self.db.session() as s:
            have = set(s.scalars(select(NewsItemRecord.id).where(NewsItemRecord.id.in_([i["id"] for i in items]))).all())
            new = [i for i in items if i["id"] not in have]
            for i in new:
                try:
                    pub = datetime.fromisoformat(i["published"].replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    pub = datetime.now(timezone.utc)
                s.add(NewsItemRecord(id=i["id"][:200], symbol=i["symbol"], published=pub, data=json.dumps(i)))
        return {i["id"] for i in new}

    def history(self, symbol: str | None = None, limit: int = 200) -> list[dict]:
        with self.db.session() as s:
            q = select(NewsItemRecord).order_by(desc(NewsItemRecord.published))
            if symbol:
                q = q.where(NewsItemRecord.symbol == symbol.upper())
            return [json.loads(r.data) for r in s.scalars(q.limit(limit)).all()]

    def _alert_new(self, symbol: str, items: list[dict]) -> None:
        if not self.alerts:
            return
        now = datetime.now(timezone.utc)
        for i in items:
            if i["relevance"] != "high" or i["certainty"] == "opinion":
                continue
            try:
                age = now - datetime.fromisoformat(i["published"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if age > timedelta(hours=2):
                continue
            tag = "UNCONFIRMED: " if i["certainty"] == "speculative" else ""
            self.alerts.emit("market", "medium", f"News: {symbol} ({i['category_label']})",
                             f"{tag}{i['headline']} ({i['source']}). Not a buy or sell signal by itself.",
                             key=f"news|{i['id']}", fingerprint="1", symbol=symbol, data={"news": i}, link=f"/#/chart/{symbol}")

    # ---------------- macro calendar ----------------

    async def econ_values(self, force: bool = False) -> dict:
        if getattr(self, "econ", None) is None:
            import os
            from .econ_data import EconData
            self.econ = EconData(os.environ.get("STUDY_BLS_API_KEY"))
        if not self.enabled:
            return {**self.econ.snapshot(), "error": "news disabled"}
        return await self.econ.refresh(force)

    async def macro(self, force: bool = False) -> dict:
        now = asyncio.get_running_loop().time()
        if not self.enabled:
            bls, meta = bls_events()
            self._macro = {"events": bls, "errors": {"fomc": "news disabled", "bea": "news disabled"}, "bls": meta, "fetched_at": None}
            return self._macro
        if not force and self._macro_t and now - self._macro_t < MACRO_TTL:
            return self._macro
        events, errors = [], {}
        for name, url, parse in (("fomc", FOMC_URL, parse_fomc), ("bea", BEA_URL, parse_bea)):
            try:
                events += parse(await fetch_text(url))
            except Exception as e:  # noqa: BLE001
                errors[name] = f"{type(e).__name__}: {e}"[:200]
                events += [e for e in self._macro["events"] if e["kind"] == name]   # keep the last good copy
        bls, meta = bls_events()
        events += bls
        self._macro = {"events": sorted(events, key=lambda e: (e["date"], e["time_et"])), "errors": errors, "bls": meta,
                       "fetched_at": datetime.now(timezone.utc).isoformat()}
        self._macro_t = now
        return self._macro

    def upcoming(self, days: int = 14, today: date | None = None) -> list[dict]:
        today = today or datetime.now(ET).date()
        end = today + timedelta(days=days)
        return [self._with_values(e) for e in self._macro["events"] if today.isoformat() <= e["date"] <= end.isoformat()]

    RELEVANCE = {"fomc": "high for index futures (rates)", "bls_cpi": "high for index futures", "bls_jobs": "high for index futures",
                 "bls_ppi": "medium", "bea": "medium (GDP/PCE high)"}

    def _with_values(self, e: dict) -> dict:
        """Attach the latest published BLS values (actual/previous) to BLS events; forecasts are never invented."""
        out = {**e, "market_relevance": self.RELEVANCE.get(e["kind"], "medium")}
        econ = getattr(self, "econ", None)
        if econ is not None and e["kind"].startswith("bls_"):
            out["published_values"] = econ.for_kind(e["kind"])
        return out

    def event_risk(self, symbol: str | None = None, now: datetime | None = None, earnings: dict | None = None) -> dict:
        """Notes for the signal engine and UI. gate=True makes new signals watch-only for now."""
        now = now or datetime.now(timezone.utc)
        notes, gate = [], False
        for e in self._macro["events"]:
            if e["importance"] != "high":
                continue
            t = event_datetime(e)
            mins = (t - now).total_seconds() / 60
            if -GATE_MINUTES <= mins <= GATE_MINUTES:
                gate = True
                when = f"in {int(mins)} min" if mins > 0 else f"{int(-mins)} min ago"
                notes.append({"type": "macro_window", "text": f"{e['event']} at {e['time_et']} ET ({when}). Signals are watch-only from "
                              f"{GATE_MINUTES} min before to {GATE_MINUTES} min after a major release: prices whipsaw.", "source": e["source"],
                              "url": e["url"]})
            elif 0 < mins <= 24 * 60 and t.astimezone(ET).date() == now.astimezone(ET).date():
                notes.append({"type": "macro_today", "text": f"{e['event']} today at {e['time_et']} ET.", "source": e["source"], "url": e["url"]})
        if symbol:
            ear = earnings or (self._slow.get(symbol.upper(), (0, {}))[1] or {}).get("earnings")
            nxt = (ear or {}).get("next")
            today = now.astimezone(ET).date()
            if nxt:
                d = date.fromisoformat(nxt["date"])
                conf = "" if nxt.get("confirmed") else " (date not confirmed)"
                if d == today and nxt.get("when") == "after the close" or d == today + timedelta(days=1) and nxt.get("when") == "before the open":
                    notes.append({"type": "earnings_soon", "text": f"{symbol} reports earnings {nxt['date']} {nxt['when']}{conf}. Holding overnight "
                                  "means a gap the stop can't protect against.", "source": "Yahoo Finance", "url": ear.get("url")})
                elif 0 <= (d - today).days <= 5:
                    notes.append({"type": "earnings_upcoming", "text": f"{symbol} earnings {nxt['date']}{' ' + nxt['when'] if nxt.get('when') else ''}{conf}.",
                                  "source": "Yahoo Finance", "url": ear.get("url")})
            hist = (ear or {}).get("history") or []
            if hist:
                last = date.fromisoformat(hist[0]["date"])
                if (today - last).days <= 1:
                    s = hist[0]
                    sur = f" (EPS {s['eps_reported']} vs {s['eps_estimate']} expected, {s['surprise_pct']:+.1f}%)" if s.get("surprise_pct") is not None else ""
                    notes.append({"type": "post_earnings", "text": f"{symbol} just reported{sur}. Post-earnings sessions run bigger ranges; "
                                  "pre-earnings levels may not hold.", "source": "Yahoo Finance", "url": ear.get("url")})
        return {"gate": gate, "notes": notes}

    def scanner_tag(self, symbol: str) -> dict | None:
        """Fresh catalysts for the scanner (cache only, no network)."""
        sym = symbol.upper()
        items = (self._news.get(sym) or (0, []))[1]
        now = datetime.now(timezone.utc)
        fresh = []
        for i in items:
            try:
                age = now - datetime.fromisoformat(i["published"].replace("Z", "+00:00"))
            except ValueError:
                continue
            if age <= timedelta(hours=24) and i["relevance"] == "high" and i["certainty"] != "opinion":
                fresh.append(i)
        ear = ((self._slow.get(sym) or (0, {}))[1] or {}).get("earnings") or {}
        nxt = ear.get("next")
        soon = nxt if nxt and nxt.get("days_away", 99) <= 1 else None
        if not fresh and not soon:
            return None
        parts = [f"{len(fresh)} high-relevance headline(s) in 24h" if fresh else None,
                 f"earnings {nxt['date']}{' ' + nxt['when'] if nxt.get('when') else ''}" if soon else None]
        return {"text": "; ".join(p for p in parts if p), "headlines": [{"headline": i["headline"], "source": i["source"], "url": i["url"],
                                                                         "certainty": i["certainty"]} for i in fresh[:3]],
                "confirmed": any(i["certainty"] == "confirmed" for i in fresh) or bool(soon)}
