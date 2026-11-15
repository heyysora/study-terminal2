"""Platform adapters for screen reading. Each adapter knows how to recognize its window and what kind of
symbols it shows. The rest of the pipeline (OCR, price axis, price tag, drawn lines) is shared.

TopstepX is the trading platform; Topstep is the prop firm. TopstepX's charts are built-in TradingView charts
(help.topstep.com "TopstepX Charting"), so the TradingView chart geometry applies; what differs is that the
symbols are futures contracts (ESZ6, /MNQ, MNQZ26) and the price must be checked against futures data.

Adapters are modular: add one by subclassing PlatformAdapter and listing it in ADAPTERS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..futures.contracts import ParsedSymbol, parse_symbol


# What the TopstepX tab is really called in the browser (seen on a real PC, 2026-11-14): "NQZ26 $27,927.25 ▼ -1.61%".
# No "TopstepX" anywhere: the tab title is the contract, its price and the day's change, and it changes with every tick.
_TSX_TITLE = re.compile(r"^\s*([A-Z0-9]{1,4}[FGHJKMNQUVXZ]\d{1,2})\s+\$\s?([\d,]+(?:\.\d+)?)(?=\s|$)")


def topstepx_title(title: str | None) -> dict | None:
    """{"contract", "root", "price"} when a window title is a TopstepX chart tab (a known futures contract, then a $ price)."""
    m = _TSX_TITLE.match(title or "")
    if not m:
        return None
    parsed = parse_symbol(m.group(1))
    if parsed is None or not getattr(parsed, "root", None):
        return None
    try:
        price = float(m.group(2).replace(",", ""))
    except ValueError:
        return None
    return {"contract": m.group(1), "root": parsed.root, "price": price}


@dataclass(frozen=True)
class PlatformAdapter:
    id: str
    name: str
    asset_class: str          # equities | futures | either
    title_words: tuple[str, ...] = ()
    process_words: tuple[str, ...] = ()
    chart_engine: str = "unknown"
    notes: str = ""

    def matches(self, title: str, process: str | None) -> bool:
        t, p = (title or "").lower(), (process or "").lower()
        return any(w in t for w in self.title_words) or any(w in p for w in self.process_words)

    def futures_symbol(self, text: str) -> ParsedSymbol | None:
        if self.asset_class == "equities":
            return None
        return parse_symbol(text)

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "asset_class": self.asset_class, "chart_engine": self.chart_engine, "notes": self.notes}


TOPSTEPX = PlatformAdapter(
    "topstepx", "TopstepX", "futures", title_words=("topstepx", "projectx", "topstep x"), process_words=("topstepx",),
    chart_engine="tradingview",
    notes=("Futures only. Charts are TradingView-based. Account and position panels are read only if you turn that on, and are "
           "always marked unverified. Not validated against real TopstepX screenshots; see docs/TOPSTEPX.md."))
TRADINGVIEW = PlatformAdapter(
    "tradingview", "TradingView", "either", title_words=("tradingview",), process_words=("tradingview",), chart_engine="tradingview",
    notes="Stocks and futures (futures symbols like ES1! or ESZ2026 are recognized).")
GENERIC = PlatformAdapter("generic", "Other / generic chart", "either", notes="Best effort: reads whatever chart text is visible.")
ADAPTERS = {a.id: a for a in (TOPSTEPX, TRADINGVIEW, GENERIC)}


def pick(title: str, process: str | None, override: str | None = None) -> PlatformAdapter:
    """The user's explicit choice wins; otherwise the window decides. TopstepX is checked first because its tab
    hosts a TradingView chart and could otherwise look like TradingView."""
    if override and override != "auto" and override in ADAPTERS:
        return ADAPTERS[override]
    if topstepx_title(title):
        return TOPSTEPX
    for a in (TOPSTEPX, TRADINGVIEW):
        if a.matches(title, process):
            return a
    return GENERIC


FUT_TOKEN = re.compile(r"^(?:[A-Z_]+:)?/?[A-Z0-9]{1,4}(?:[FGHJKMNQUVXZ]\d{1,4}|1!|2!)(?:\.[A-Z]{3})?$|^/[A-Z0-9]{1,4}$")


def futures_candidates(texts: list[str], adapter: PlatformAdapter) -> list[ParsedSymbol]:
    if adapter.asset_class == "equities":
        return []
    out, seen = [], set()
    for x in texts:
        x2 = x.strip("·|,()").upper()
        if not FUT_TOKEN.match(x2):
            continue
        p = parse_symbol(x2)
        if p and (p.contract.code if p.contract else p.root) not in seen:
            seen.add(p.contract.code if p.contract else p.root)
            out.append(p)
    # specific contracts before continuous/root symbols
    return sorted(out, key=lambda p: p.contract is None)
