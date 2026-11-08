"""Rule-based labelling of news headlines. These are the app's interpretation, shown as such:
plain keyword rules, not an AI model and not a judgment that a headline is true.

For each item we decide:
  category    what kind of event it is (earnings, guidance, FDA, analyst rating, deal, ...)
  certainty   confirmed (an official announcement or a reported fact), speculative (rumour,
              "reportedly", "in talks"), or opinion (commentary, lists, "should you buy")
  relevance   high / medium / low for the symbol you're looking at, with the reason
Direction is deliberately NOT inferred: good news can sell off ("priced in") and bad news can rally.
"""
from __future__ import annotations

import re

CATEGORIES: list[tuple[str, str, re.Pattern]] = [
    ("earnings", "Earnings", re.compile(r"\b(earnings|quarterly results|q[1-4] (results|profit|revenue|loss)|eps|beats?|miss(es|ed)? (estimates|expectations)|profit (rises|falls|jumps|drops)|revenue (rises|falls|tops|misses))\b", re.I)),
    ("guidance", "Guidance / outlook", re.compile(r"\b(guidance|outlook|forecasts?|raises (its )?(full-year|annual|fy)|cuts (its )?(full-year|annual|fy)|reaffirms|withdraws)\b", re.I)),
    ("fda", "FDA / regulatory approval", re.compile(r"\b(fda|pdufa|approval|approves|clearance|phase [123i]+|clinical (trial|hold)|complete response letter|ema)\b", re.I)),
    ("analyst", "Analyst rating / target", re.compile(r"\b(upgrades?|downgrades?|initiates?|price target|overweight|underweight|outperform|underperform|reiterat\w+|coverage)\b", re.I)),
    ("deal", "Merger / acquisition / partnership", re.compile(r"\b(acquir\w+|acquisition|merger|merge|buyout|takeover|to buy|deal (to|with)|partnership|stake in|spin-?off)\b", re.I)),
    ("capital", "Offering / buyback / dividend", re.compile(r"\b(offering|share sale|dilut\w+|buyback|repurchase|dividend|convertible|notes due|raises \$)\b", re.I)),
    ("legal", "Legal / regulatory action", re.compile(r"\b(lawsuit|sues|sued|probe|investigation|sec charges|antitrust|fine[sd]?|settle\w*|subpoena|recall|ban)\b", re.I)),
    ("macro", "Fed / economy", re.compile(r"\b(fed|fomc|powell|interest rates?|rate (cut|hike)|inflation|cpi|ppi|jobs report|payrolls|unemployment|gdp|recession|treasury yields?)\b", re.I)),
    ("geopolitical", "Geopolitical", re.compile(r"\b(tariffs?|sanctions?|export (controls?|curbs?|ban)|war|conflict|ceasefire|china|trade (war|talks|deal))\b", re.I)),
    ("management", "Management change", re.compile(r"\b(ceo|cfo|chief executive|steps down|resigns|appoints|named (as )?(ceo|cfo|chair))\b", re.I)),
    ("product", "Product / business update", re.compile(r"\b(launch\w*|unveil\w*|announces|introduces|contract|orders?|customers?|shipments?|deliveries)\b", re.I)),
]

SPECULATIVE = re.compile(r"\b(reportedly|report(s|ed)? (that|says)|according to (people|sources|a person)|sources say|people familiar|rumou?r\w*|"
                         r"in talks|considering|weighs?|exploring|could|may|might|potential(ly)?|eyes|mulls?|plans? to|expected to|"
                         r"set to|likely)\b", re.I)
OPINION = re.compile(r"(\?\s*$|\bshould you\b|\bhow to\b|\bstocks? to (buy|watch|avoid)\b|\b(top|best) \d+\b|\b\d+ (stocks|reasons|things)\b|"
                     r"\bwhy (i|we|this)\b|\bis it (time|too late)\b|\bbuy (the dip|now)\b|\bmy (top|favorite)\b|\bprediction\b|"
                     r"\bmillionaire\b|\bforever\b|\bno-brainer\b|\bhere'?s (why|how|what)\b|\bwhat (to|investors) (know|expect)\b)", re.I)
OPINION_PUBLISHERS = {"Motley Fool", "The Motley Fool", "InvestorPlace", "24/7 Wall St.", "Zacks", "Benzinga Insights",
                      "Simply Wall St.", "Simply Wall St", "GuruFocus.com", "Seeking Alpha", "TipRanks", "MarketBeat", "Insider Monkey"}
CONFIRMED = re.compile(r"\b(announces?|announced|reports?|reported|files?|filed|approves?|approved|completes?|completed|declares?|"
                       r"raises|cuts|beats?|misses|posts|rose|fell|jumps?|plunges?|surges?|says|said|confirms?|names?|appoints?)\b", re.I)

HIGH_IMPACT = {"earnings", "guidance", "fda", "deal", "capital", "legal", "analyst", "management"}


def categorize(text: str) -> tuple[str, str]:
    for code, label, rx in CATEGORIES:
        if rx.search(text):
            return code, label
    return "general", "General / market commentary"


def certainty(headline: str, publisher: str | None) -> tuple[str, str]:
    if (publisher or "") in OPINION_PUBLISHERS or OPINION.search(headline):
        return "opinion", "Commentary or opinion, not a reported event"
    if SPECULATIVE.search(headline):
        return "speculative", "Unconfirmed: the headline itself signals a report, rumour or possibility"
    if CONFIRMED.search(headline):
        return "confirmed", "Reported as a fact by the publisher (check the source for the official filing or release)"
    return "unclear", "Can't tell from the headline whether this is a confirmed event"


def relevance(symbol: str, headline: str, tickers: list[str], category: str, cert: str, company: str | None = None) -> tuple[str, str]:
    sym = symbol.upper()
    named = bool(re.search(rf"\b{re.escape(sym)}\b", headline)) or bool(company and company.lower() in headline.lower())
    primary = bool(tickers) and tickers[0].upper() == sym
    only = tickers == [sym]
    if cert == "opinion":
        return "low", "Opinion/commentary piece"
    if category in HIGH_IMPACT and (named or primary or only):
        return "high", f"{category.capitalize()} news naming {sym} directly"
    if named or only:
        return "medium", f"Mentions {sym} directly"
    if category in ("macro", "geopolitical"):
        return "medium", "Market-wide news that can move most stocks"
    return "low", f"{sym} is one of several tickers tagged on this story" if tickers else "Not clearly about this symbol"


def company_hint(name: str | None) -> str | None:
    """'NVIDIA Corporation' -> 'NVIDIA' (for matching headlines)."""
    if not name:
        return None
    n = re.sub(r"[,.]?\s+(inc|corp|corporation|co|company|ltd|plc|holdings|group|class [a-z])\.?$", "", name.strip(), flags=re.I)
    n = re.sub(r"[,.]?\s+(inc|corp|corporation|co|company|ltd|plc|holdings|group)\.?$", "", n, flags=re.I)
    return n if len(n) >= 3 else None
