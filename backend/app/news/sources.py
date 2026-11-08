"""Where catalyst data comes from. All free, no keys. Every item keeps its source and link.

  Yahoo Finance (unofficial, via yfinance)
      news                 headlines, publisher, publish time, link, tagged tickers, publisher summary
      calendar             next earnings date (+ EPS/revenue estimate range)
      earnings_dates       past quarters: EPS estimate, reported EPS, surprise %
      upgrades_downgrades  analyst firm, action, old/new rating, old/new price target
  Federal Reserve          FOMC meeting dates, parsed live from federalreserve.gov
  BEA                      GDP / PCE / trade release dates, parsed live from bea.gov
  BLS                      CPI / jobs / PPI dates, bundled file (BLS refuses automated downloads)

Not covered (no reliable free source): FDA PDUFA dates (not officially published as a calendar),
company press-release wires, and real-time headlines faster than Yahoo publishes them.
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import httpx

from ..core.market_clock import ET
from .classify import categorize, certainty, company_hint, relevance

log = logging.getLogger(__name__)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StudyTerminal/0.5 (personal research app)"}


@dataclass
class NewsItem:
    id: str
    headline: str
    source: str
    published: str                 # ISO UTC, as given by the source
    url: str | None
    tickers: list[str]
    publisher_summary: str | None  # the publisher's own text, shown as theirs
    kind: str = "news"             # news | analyst | earnings | macro
    category: str = "general"
    category_label: str = ""
    certainty: str = "unclear"
    certainty_label: str = ""
    relevance: str = "low"
    relevance_reason: str = ""
    symbol: str | None = None      # the symbol this item was fetched for
    via: str = "Yahoo Finance"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def label(item: NewsItem, symbol: str, company: str | None = None) -> NewsItem:
    item.category, item.category_label = categorize(item.headline + " " + (item.publisher_summary or "")[:200])
    item.certainty, item.certainty_label = certainty(item.headline, item.source)
    item.relevance, item.relevance_reason = relevance(symbol, item.headline, item.tickers, item.category, item.certainty, company)
    item.symbol = symbol
    return item


def parse_yahoo_news(raw: list[dict], symbol: str, company: str | None = None) -> list[NewsItem]:
    out = []
    for r in raw or []:
        c = r.get("content") or r            # yfinance >= 0.2.50 nests everything under "content"
        title = (c.get("title") or "").strip()
        if not title:
            continue
        pub = c.get("pubDate") or c.get("displayTime")
        if not pub and r.get("providerPublishTime"):
            pub = datetime.fromtimestamp(r["providerPublishTime"], timezone.utc).isoformat()
        url = ((c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url") or r.get("link"))
        prov = (c.get("provider") or {}).get("displayName") or r.get("publisher") or "Unknown publisher"
        tick = [t.get("symbol") for t in ((c.get("finance") or {}).get("stockTickers") or []) if t.get("symbol")] or r.get("relatedTickers") or []
        it = NewsItem(id=f"yn:{r.get('id') or c.get('id') or url}", headline=title, source=prov, published=pub or "",
                      url=url, tickers=tick, publisher_summary=(c.get("summary") or c.get("description") or None))
        out.append(label(it, symbol, company))
    return out


def parse_analyst(df, symbol: str, days: int = 45, now: datetime | None = None) -> list[NewsItem]:
    """yfinance upgrades_downgrades -> items. The headline is assembled from the fields, word for word."""
    if df is None or getattr(df, "empty", True):
        return []
    now = now or datetime.now(timezone.utc)
    acts = {"up": "upgrades", "down": "downgrades", "init": "initiates coverage on", "main": "maintains", "reit": "reiterates"}
    out = []
    for ts, row in df.iterrows():
        t = ts.to_pydatetime()
        t = t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
        if now - t > timedelta(days=days):
            continue
        firm, act = str(row.get("Firm", "")), str(row.get("Action", ""))
        to_g, from_g = str(row.get("ToGrade") or ""), str(row.get("FromGrade") or "")
        cur, prior = row.get("currentPriceTarget"), row.get("priorPriceTarget")
        pta = str(row.get("priceTargetAction") or "")
        h = f"{firm} {acts.get(act, act)} {symbol}"
        if act in ("up", "down") and from_g and to_g:
            h += f" from {from_g} to {to_g}"
        elif to_g:
            h += f" at {to_g}"
        ok = lambda x: x is not None and x == x and float(x) > 0  # noqa: E731
        if ok(cur):
            h += (f"; price target {pta.lower()} ${float(prior):,.0f} → ${float(cur):,.0f}" if ok(prior) and float(prior) != float(cur)
                  else f"; price target ${float(cur):,.0f}")
        it = NewsItem(id=f"ya:{symbol}:{t.isoformat()}:{firm}", headline=h, source=firm or "Analyst", published=t.isoformat(),
                      url=f"https://finance.yahoo.com/quote/{symbol}/analysis", tickers=[symbol], publisher_summary=None,
                      kind="analyst", category="analyst", category_label="Analyst rating / target",
                      certainty="confirmed", certainty_label="Rating action recorded by Yahoo Finance's analyst feed",
                      relevance="high" if act in ("up", "down", "init") else "medium",
                      relevance_reason="Rating change" if act in ("up", "down") else "New coverage" if act == "init" else "Rating maintained",
                      symbol=symbol, extra={"action": act, "from": from_g, "to": to_g, "pt_prior": prior if ok(prior) else None,
                                            "pt_current": cur if ok(cur) else None})
        out.append(it)
    return out


def _f(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def parse_earnings(calendar: dict | None, dates_df, symbol: str, today: date | None = None) -> dict:
    """Next earnings date and the most recent reported quarters (with surprise)."""
    today = today or datetime.now(ET).date()
    out: dict = {"symbol": symbol, "next": None, "history": [], "source": "Yahoo Finance (calendar, earnings_dates)",
                 "url": f"https://finance.yahoo.com/quote/{symbol}/analysis"}
    times: dict[date, datetime] = {}
    if dates_df is not None and not getattr(dates_df, "empty", True):
        for ts, row in dates_df.iterrows():
            t = ts.to_pydatetime()
            d = t.astimezone(ET).date() if t.tzinfo else t.date()
            times[d] = t
            rep, est, sur = _f(row.get("Reported EPS")), _f(row.get("EPS Estimate")), _f(row.get("Surprise(%)"))
            if rep is not None and d <= today:
                out["history"].append({"date": d.isoformat(), "eps_estimate": est, "eps_reported": rep, "surprise_pct": sur,
                                       "beat": None if est is None else rep > est})
        out["history"] = sorted(out["history"], key=lambda h: h["date"], reverse=True)[:6]
    cal = calendar or {}
    ed = cal.get("Earnings Date") or []
    ed = [d for d in ed if isinstance(d, date)]
    upcoming = sorted(d for d in ed if d >= today)
    if upcoming:
        d = upcoming[0]
        t = times.get(d)
        when = None
        if t is not None and t.tzinfo:
            hm = t.astimezone(ET).time()
            when = "before the open" if hm < time(9, 30) else "after the close" if hm >= time(16, 0) else f"at {hm:%H:%M} ET"
        out["next"] = {
            "date": d.isoformat(), "when": when, "days_away": (d - today).days,
            "confirmed": len(ed) == 1,
            "status": ("scheduled date listed by Yahoo (confirm on the company's investor-relations site)" if len(ed) == 1 else
                       f"estimated window {ed[0]} to {ed[-1]}: not yet confirmed by the company"),
            "eps_estimate": _f(cal.get("Earnings Average")), "eps_range": [_f(cal.get("Earnings Low")), _f(cal.get("Earnings High"))],
            "revenue_estimate": _f(cal.get("Revenue Average")),
        }
    return out


# ---------------- macro calendar ----------------

MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September",
                                      "October", "November", "December"], 1)}
SHORT = {k[:3]: v for k, v in MONTHS.items()}


def parse_fomc(html: str) -> list[dict]:
    """FOMC meetings from federalreserve.gov/monetarypolicy/fomccalendars.htm. The decision is released on the
    meeting's last day at 14:00 ET; '*' marks meetings with a Summary of Economic Projections."""
    out = []
    for y in re.finditer(r"(\d{4}) FOMC Meetings</a>", html):
        year = int(y.group(1))
        seg = html[y.end():]
        nxt = re.search(r"\d{4} FOMC Meetings</a>", seg)
        seg = seg[:nxt.start()] if nxt else seg
        for mon, days in re.findall(r'fomc-meeting__month[^>]*><strong>([^<]+)</strong></div>\s*<div class="fomc-meeting__date[^>]*>([^<]+)</div>', seg):
            if "notation" in days.lower() or "unscheduled" in days.lower():
                continue
            m = re.match(r"\s*(\d{1,2})(?:-(\d{1,2}))?(\*)?", days)
            if not m:
                continue
            last_day = int(m.group(2) or m.group(1))
            mon_last = mon.split("/")[-1].strip()
            month = MONTHS.get(mon_last) or SHORT.get(mon_last[:3])
            if not month:
                continue
            d = date(year, month, last_day)
            out.append({"date": d.isoformat(), "time_et": "14:00", "event": "FOMC rate decision" + (" + projections" if m.group(3) else ""),
                        "kind": "fomc", "importance": "high", "source": "Federal Reserve",
                        "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm", "confirmed": True,
                        "detail": "Statement at 2:00 PM ET, press conference at 2:30 PM ET."})
    return sorted(out, key=lambda e: e["date"])


BEA_KEEP = re.compile(r"\b(GDP|Gross Domestic Product|Personal Income and Outlays|PCE|Trade in Goods and Services)\b", re.I)
BEA_REGIONAL = re.compile(r"\b(by County|by Metropolitan|by State)\b", re.I)   # regional-only releases don't move the market


def parse_bea(html: str, today: date | None = None) -> list[dict]:
    today = today or datetime.now(ET).date()
    m = re.search(r"Year (\d{4})</th>", html)
    year = int(m.group(1)) if m else today.year
    out, prev_month = [], 0
    for mon, day, hhmm, ampm, title in re.findall(
            r'release-date">\s*([A-Z][a-z]+) (\d{1,2})\s*</div>\s*<small[^>]*>\s*(\d{1,2}:\d{2})\s*([AP]M)\s*</small>.*?release-title[^>]*>\s*([^<]+?)\s*</td>',
            html, flags=re.S):
        month = MONTHS.get(mon)
        if not month:
            continue
        if month < prev_month:   # the table runs into the next year
            year += 1
        prev_month = month
        title = re.sub(r"\s+", " ", title)
        if not BEA_KEEP.search(title) or (BEA_REGIONAL.search(title) and "Estimate" not in title):
            continue
        h, mi = map(int, hhmm.split(":"))
        h = h % 12 + (12 if ampm == "PM" else 0)
        out.append({"date": date(year, month, int(day)).isoformat(), "time_et": f"{h:02d}:{mi:02d}", "event": title, "kind": "bea",
                    "importance": "high" if re.search(r"GDP|Personal Income", title) else "medium", "source": "Bureau of Economic Analysis",
                    "url": "https://www.bea.gov/news/schedule", "confirmed": True, "detail": ""})
    return out


def bls_events() -> tuple[list[dict], dict]:
    data = json.loads((Path(__file__).parent / "bls_schedule.json").read_text())
    out = []
    for code, r in data["releases"].items():
        for d in r["dates"]:
            out.append({"date": d, "time_et": data["time_et"], "event": r["name"], "kind": f"bls_{code}", "importance": "high",
                        "source": "Bureau of Labor Statistics", "url": data["source_urls"][code], "confirmed": True,
                        "detail": f"Bundled schedule retrieved {data['retrieved']}."})
    meta = {"retrieved": data["retrieved"], "last_date": max(e["date"] for e in out), "note": data["note"]}
    return out, meta


async def fetch_text(url: str, timeout: float = 15.0) -> str:
    async with httpx.AsyncClient(headers=UA, timeout=timeout, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.text


def event_datetime(e: dict) -> datetime:
    h, m = map(int, e["time_et"].split(":"))
    return datetime.combine(date.fromisoformat(e["date"]), time(h, m), tzinfo=ET)


__all__ = ["NewsItem", "parse_yahoo_news", "parse_analyst", "parse_earnings", "parse_fomc", "parse_bea", "bls_events",
           "fetch_text", "event_datetime", "company_hint"]
