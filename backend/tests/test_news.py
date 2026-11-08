"""Phase 5: news parsing and labelling, earnings and analyst data, macro calendar, and how catalysts
reach signals and the scanner. Fixtures are trimmed copies of the real Fed and BEA pages (2026-11-07)."""
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from app.core.market_clock import ET
from app.news.classify import certainty, relevance
from app.news.service import NewsService
from app.news.sources import bls_events, parse_analyst, parse_bea, parse_earnings, parse_fomc, parse_yahoo_news
from app.scanner.service import rank
from app.signals.engine import apply_events

FIX = Path(__file__).parent / "fixtures"

YAHOO_RAW = [
    {"id": "a1", "content": {"id": "a1", "title": "Nvidia beats estimates as data-center revenue jumps 60%", "summary": "Nvidia reported...",
                             "pubDate": "2026-11-20T21:05:00Z", "provider": {"displayName": "Reuters"},
                             "canonicalUrl": {"url": "https://example.com/a1"}, "finance": {"stockTickers": [{"symbol": "NVDA"}]}}},
    {"id": "a2", "content": {"id": "a2", "title": "Nvidia reportedly in talks to acquire chip startup", "pubDate": "2026-11-20T15:00:00Z",
                             "provider": {"displayName": "Bloomberg"}, "canonicalUrl": {"url": "https://example.com/a2"},
                             "finance": {"stockTickers": [{"symbol": "NVDA"}]}}},
    {"id": "a3", "content": {"id": "a3", "title": "3 AI Stocks to Buy Before 2027", "pubDate": "2026-11-20T12:00:00Z",
                             "provider": {"displayName": "Motley Fool"}, "canonicalUrl": {"url": "https://example.com/a3"},
                             "finance": {"stockTickers": [{"symbol": "MSFT"}, {"symbol": "NVDA"}]}}},
    {"id": "a4", "content": {"id": "a4", "title": "", "pubDate": "2026-11-20T12:00:00Z"}},   # empty: skipped, never invented
]


def test_yahoo_news_is_parsed_with_source_link_and_labels():
    items = parse_yahoo_news(YAHOO_RAW, "NVDA", "NVIDIA")
    assert len(items) == 3
    a, b, c = items
    assert (a.source, a.url, a.published, a.tickers) == ("Reuters", "https://example.com/a1", "2026-11-20T21:05:00Z", ["NVDA"])
    assert a.category == "earnings" and a.certainty == "confirmed" and a.relevance == "high"
    assert b.category == "deal" and b.certainty == "speculative"
    assert c.certainty == "opinion" and c.relevance == "low"
    assert a.publisher_summary == "Nvidia reported..."      # the publisher's words, labelled as theirs in the UI


def test_certainty_and_relevance_rules():
    assert certainty("FDA approves Acme's drug for lung cancer", "Reuters")[0] == "confirmed"
    assert certainty("Acme could be a takeover target, sources say", "CNBC")[0] == "speculative"
    assert certainty("Is it too late to buy Acme?", "Reuters")[0] == "opinion"
    assert relevance("TSLA", "Fed holds rates steady", ["SPY"], "macro", "confirmed")[0] == "medium"
    assert relevance("TSLA", "Ford recalls trucks", ["F", "TSLA"], "legal", "confirmed")[0] == "low"


def test_analyst_actions_are_built_from_fields_only():
    df = pd.DataFrame([
        {"Firm": "Needham", "ToGrade": "Buy", "FromGrade": "Hold", "Action": "up", "priceTargetAction": "Raises",
         "currentPriceTarget": 300.0, "priorPriceTarget": 250.0},
        {"Firm": "Old Firm", "ToGrade": "Sell", "FromGrade": "", "Action": "init", "priceTargetAction": "", "currentPriceTarget": 0.0,
         "priorPriceTarget": 0.0},
    ], index=pd.DatetimeIndex([datetime(2026, 11, 18, 12), datetime(2026, 6, 1, 12)], name="GradeDate"))
    items = parse_analyst(df, "NVDA", days=45, now=datetime(2026, 11, 20, tzinfo=timezone.utc))
    assert len(items) == 1                                 # the June action is outside the window
    assert items[0].headline == "Needham upgrades NVDA from Hold to Buy; price target raises $250 → $300"
    assert items[0].relevance == "high" and items[0].certainty == "confirmed"


def test_earnings_next_date_and_surprises():
    idx = pd.DatetimeIndex([pd.Timestamp("2026-11-17 16:00", tz=ET), pd.Timestamp("2026-08-26 16:00", tz=ET)])
    dates = pd.DataFrame({"EPS Estimate": [2.47, 2.09], "Reported EPS": [float("nan"), 2.22], "Surprise(%)": [float("nan"), 6.16]}, index=idx)
    cal = {"Earnings Date": [date(2026, 11, 17)], "Earnings Average": 2.47, "Earnings Low": 2.34, "Earnings High": 2.7}
    e = parse_earnings(cal, dates, "NVDA", today=date(2026, 11, 7))
    assert e["next"]["date"] == "2026-11-17" and e["next"]["when"] == "after the close" and e["next"]["confirmed"]
    assert e["history"][0] == {"date": "2026-08-26", "eps_estimate": 2.09, "eps_reported": 2.22, "surprise_pct": 6.16, "beat": True}
    unconf = parse_earnings({"Earnings Date": [date(2026, 11, 17), date(2026, 11, 21)]}, None, "X", today=date(2026, 11, 7))
    assert unconf["next"]["confirmed"] is False and "not yet confirmed" in unconf["next"]["status"]


def test_fomc_and_bea_parsers_on_real_pages():
    f = parse_fomc((FIX / "fomc_2026_2027.html").read_text())
    dates = [e["date"] for e in f]
    assert "2026-12-09" in dates and "2027-01-27" in dates and len(f) == 16
    assert next(e for e in f if e["date"] == "2026-12-09")["event"].endswith("projections")
    b = parse_bea((FIX / "bea_schedule.html").read_text(), today=date(2026, 11, 7))
    titles = [e["event"] for e in b]
    assert any(t.startswith("GDP (Second Estimate)") for t in titles) and any("Personal Income and Outlays" in t for t in titles)
    assert not any("by County" in t for t in titles)
    assert all(e["time_et"] in ("08:30", "10:00") for e in b)


def test_bls_bundle():
    ev, meta = bls_events()
    assert {"2026-11-10", "2026-12-04", "2026-12-15"} <= {e["date"] for e in ev}
    assert meta["retrieved"] == "2026-11-07" and meta["last_date"] == "2027-12-15"


def test_event_window_gates_signals_and_earnings_notes():
    n = NewsService(db=None, provider=None, clock=None)
    n._macro = {"events": parse_fomc((FIX / "fomc_2026_2027.html").read_text()), "errors": {}, "bls": None, "fetched_at": None}
    at = datetime(2026, 12, 9, 13, 50, tzinfo=ET)          # 10 min before the decision
    r = n.event_risk("SPY", now=at)
    assert r["gate"] and "FOMC" in r["notes"][0]["text"]
    assert not n.event_risk("SPY", now=datetime(2026, 12, 9, 13, 30, tzinfo=ET))["gate"]
    assert n.event_risk("SPY", now=datetime(2026, 12, 9, 13, 30, tzinfo=ET))["notes"][0]["type"] == "macro_today"
    ear = {"next": {"date": "2026-12-09", "when": "after the close", "confirmed": True}, "history": [], "url": "u"}
    r2 = n.event_risk("NVDA", now=datetime(2026, 12, 9, 11, 0, tzinfo=ET), earnings=ear)
    assert any(x["type"] == "earnings_soon" for x in r2["notes"])
    # a tradeable signal inside the window becomes watch-only, with the reason first
    sig = {"direction": "long", "tradeable": True, "action": "BUY", "risks": []}
    ev = apply_events({"signals": [sig], "best": sig, "action": "BUY", "reasons": []}, r)
    assert ev["action"] == "NO TRADE" and sig["action"] == "POTENTIAL BUY" and not sig["tradeable"] and "FOMC" in ev["reasons"][0]


def test_scanner_catalyst_boost_is_labelled_and_directionless():
    base = {"rvol": 2, "change_pct": 3, "bias_score": 50, "dollar_volume": 1e9,
            "watch_signal": {"confidence": {"setup_quality": {"score": 60}}, "evidence_tier": "inconclusive", "tradeable": False}}
    s0, _ = rank(base)
    s1, comp = rank({**base, "catalyst": {"confirmed": True, "text": "earnings 2026-11-17 after the close"}})
    assert s1 == round(s0 + 5, 1) and "direction not assumed" in comp["catalyst"]
    assert "watch only" in comp["evidence"]
