"""Futures contract specifications, tick math, expirations and the roll calendar.

Every built-in spec carries the page it was checked against and the date. Values that are exchange
rules (tick size, tick value, termination) come from CME Group contract-spec pages. Values that are
only conventions (when most traders roll, which hours count as "RTH") are marked `convention` and are
editable. Products can be added or overridden with a JSON file (see `load_user_products`), and those
are flagged `user_defined` so the UI never presents them as verified.

All prices go through Decimal tick rounding: 0.1 + 0.2 style float error must never turn a stop that
is exactly on a tick into one that is a hair off it.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

CT = ZoneInfo("America/Chicago")
ET = ZoneInfo("America/New_York")

MONTH_CODES = "FGHJKMNQUVXZ"  # Jan..Dec
CODE_TO_MONTH = {c: i + 1 for i, c in enumerate(MONTH_CODES)}

VERIFIED_ON = "2026-11-07"
SRC_ES = "https://www.cmegroup.com/markets/equities/sp/e-mini-sandp500.contractSpecs.html"
SRC_MES = "https://www.cmegroup.com/markets/equities/sp/micro-e-mini-sandp-500.contractSpecs.html"
SRC_NQ = "https://www.cmegroup.com/markets/equities/nasdaq/e-mini-nasdaq-100.contractSpecs.html"
SRC_MNQ = "https://www.cmegroup.com/markets/equities/nasdaq/micro-e-mini-nasdaq-100.contractSpecs.html"
SRC_YM = "https://www.cmegroup.com/markets/equities/dow-jones/e-mini-dow.contractSpecs.html"
SRC_MYM = "https://www.cmegroup.com/markets/equities/dow-jones/micro-e-mini-dow.contractSpecs.html"
SRC_RTY = "https://www.cmegroup.com/markets/equities/russell/e-mini-russell-2000.contractSpecs.html"
SRC_M2K = "https://www.cmegroup.com/markets/equities/russell/micro-e-mini-russell-2000.contractSpecs.html"
SRC_CL = "https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.contractSpecs.html"
SRC_GC = "https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html"
SRC_ROLL = "https://www.cmegroup.com/trading/equity-index/rolldates.html"
SRC_GC_ACTIVE = "https://www.cmegroup.com/content/dam/cmegroup/notices/ser/2026/06/ser-9637r.pdf"


@dataclass(frozen=True)
class ProductSpec:
    root: str
    name: str
    exchange: str              # CME | CBOT | NYMEX | COMEX
    calendar: str              # exchange_calendars name
    tick_size: str             # string so Decimal math is exact
    tick_value: float          # USD per tick per contract
    multiplier: float          # USD per 1.0 point
    months: str                # listed month codes used for the front-month chain
    expiry_rule: str           # equity_quarterly | cl_monthly | gc_third_last
    roll_rule: str             # cme_equity_monday | business_days_before_expiry | gc_first_position_day
    roll_days: int = 0         # for business_days_before_expiry
    last_trade_time_ct: str | None = None   # only when the spec page states a time
    globex_open_ct: str = "17:00"           # session opens the evening before the trade date
    globex_close_ct: str = "16:00"
    rth_start_ct: str = "08:30"             # convention, editable
    rth_end_ct: str = "15:00"
    rth_note: str = ""
    yahoo_suffix: str = "CME"
    micro_of: str | None = None             # MES -> ES
    mini_equivalent: float = 1.0            # contracts of this product that equal one mini for prop limits
    group: str = "equity_index"
    sources: tuple[str, ...] = ()
    verified_on: str = VERIFIED_ON
    user_defined: bool = False
    notes: tuple[str, ...] = ()

    @property
    def tick(self) -> Decimal:
        return Decimal(self.tick_size)

    @property
    def decimals(self) -> int:
        return max(0, -self.tick.as_tuple().exponent)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["decimals"] = self.decimals
        d["point_value"] = self.multiplier
        d["ticks_per_point"] = float(Decimal(1) / self.tick)
        return d


_EQ = dict(months="HMUZ", expiry_rule="equity_quarterly", roll_rule="cme_equity_monday", last_trade_time_ct="08:30",
           rth_note="RTH here means the 8:30-15:00 CT cash-market hours, the common convention for index futures. Editable.")

BUILTIN: dict[str, ProductSpec] = {p.root: p for p in [
    ProductSpec("ES", "E-mini S&P 500", "CME", "CMES", "0.25", 12.50, 50.0, sources=(SRC_ES, SRC_ROLL), **_EQ),
    ProductSpec("MES", "Micro E-mini S&P 500", "CME", "CMES", "0.25", 1.25, 5.0, micro_of="ES", mini_equivalent=0.1,
                sources=(SRC_MES, SRC_ROLL), **_EQ),
    ProductSpec("NQ", "E-mini Nasdaq-100", "CME", "CMES", "0.25", 5.00, 20.0, sources=(SRC_NQ, SRC_ROLL), **_EQ),
    ProductSpec("MNQ", "Micro E-mini Nasdaq-100", "CME", "CMES", "0.25", 0.50, 2.0, micro_of="NQ", mini_equivalent=0.1,
                sources=(SRC_MNQ, SRC_ROLL), **_EQ),
    ProductSpec("YM", "E-mini Dow ($5)", "CBOT", "CBOT", "1", 5.00, 5.0, yahoo_suffix="CBT", sources=(SRC_YM, SRC_ROLL), **_EQ),
    ProductSpec("MYM", "Micro E-mini Dow", "CBOT", "CBOT", "1", 0.50, 0.5, yahoo_suffix="CBT", micro_of="YM", mini_equivalent=0.1,
                sources=(SRC_MYM, SRC_ROLL), **_EQ),
    ProductSpec("RTY", "E-mini Russell 2000", "CME", "CMES", "0.10", 5.00, 50.0, sources=(SRC_RTY, SRC_ROLL), **_EQ),
    ProductSpec("M2K", "Micro E-mini Russell 2000", "CME", "CMES", "0.10", 0.50, 5.0, micro_of="RTY", mini_equivalent=0.1,
                sources=(SRC_M2K, SRC_ROLL), **_EQ),
    ProductSpec("CL", "Crude Oil (WTI)", "NYMEX", "NYMEX", "0.01", 10.00, 1000.0, months=MONTH_CODES, expiry_rule="cl_monthly",
                roll_rule="business_days_before_expiry", roll_days=3, rth_start_ct="08:00", rth_end_ct="13:30",
                rth_note="RTH here means 8:00-13:30 CT, the former NYMEX floor hours most CL traders use. Editable.",
                yahoo_suffix="NYM", group="energy", sources=(SRC_CL,),
                notes=("Roll timing is a convention (3 business days before last trade by default), not an exchange rule. "
                       "CL is physically delivered; never hold into the last trading days.",)),
    ProductSpec("GC", "Gold", "COMEX", "COMEX", "0.10", 10.00, 100.0, months="GJMQVZ", expiry_rule="gc_third_last",
                roll_rule="gc_first_position_day", last_trade_time_ct="12:30", rth_start_ct="07:20", rth_end_ct="12:30",
                rth_note="RTH here means 7:20-12:30 CT, CME's reference day session for gold. Editable.",
                yahoo_suffix="CMX", group="metals", sources=(SRC_GC, SRC_GC_ACTIVE),
                notes=("Front month follows COMEX's active-month list (Feb, Apr, Jun, Aug, Oct, Dec); a month stops being "
                       "active on its First Position Date, two business days before the contract month starts.",)),
]}

_USER: dict[str, ProductSpec] = {}


def products() -> dict[str, ProductSpec]:
    return {**BUILTIN, **_USER}


def get(root: str) -> ProductSpec:
    p = products().get(root.upper())
    if not p:
        raise KeyError(f"Unknown futures product '{root}'. Known: {', '.join(sorted(products()))}")
    return p


def load_user_products(path: Path) -> list[str]:
    """Optional `futures_products.json`: a list of objects with ProductSpec fields. Overrides are allowed but
    always marked user_defined so they are never shown as exchange-verified."""
    _USER.clear()
    if not path.exists():
        return []
    try:
        items = json.loads(path.read_text(encoding="utf-8"))
        for it in items:
            base = BUILTIN.get(str(it.get("root", "")).upper())
            fields = {k: v for k, v in it.items() if k in ProductSpec.__dataclass_fields__}
            fields["root"] = fields["root"].upper()
            for k in ("sources", "notes"):
                if k in fields:
                    fields[k] = tuple(fields[k])
            spec = replace(base, **fields) if base else ProductSpec(**fields)
            _USER[spec.root] = replace(spec, user_defined=True, verified_on=it.get("verified_on", "user"))
    except Exception as e:  # noqa: BLE001
        log.warning("Could not load %s: %s", path, e)
        raise ValueError(f"futures_products.json is invalid: {e}") from e
    return sorted(_USER)


# ---------------- tick math ----------------

def round_to_tick(price: float, spec: ProductSpec, mode: str = "nearest") -> float:
    """Snap a price onto the tick grid. mode: nearest | down | up."""
    p, t = Decimal(str(price)), spec.tick
    n = p / t
    if mode == "down":
        n = n.to_integral_value(rounding="ROUND_FLOOR")
    elif mode == "up":
        n = n.to_integral_value(rounding="ROUND_CEILING")
    else:
        n = n.to_integral_value(rounding=ROUND_HALF_UP)
    return float((n * t).quantize(t))


def ticks_between(a: float, b: float, spec: ProductSpec) -> int:
    """Whole ticks from a to b (signed, b - a). Inputs are snapped first."""
    da, db = Decimal(str(round_to_tick(a, spec))), Decimal(str(round_to_tick(b, spec)))
    return int(((db - da) / spec.tick).to_integral_value(rounding=ROUND_HALF_UP))


def pnl_usd(entry: float, exit_: float, qty: int, side: int, spec: ProductSpec) -> float:
    """Gross P&L in dollars: ticks moved x tick value x contracts. side = +1 long, -1 short."""
    return round(side * ticks_between(entry, exit_, spec) * spec.tick_value * qty, 2)


def risk_per_contract(entry: float, stop: float, spec: ProductSpec, slippage_ticks: float = 0.0, round_turn_cost: float = 0.0) -> dict:
    ticks = abs(ticks_between(entry, stop, spec))
    gross = ticks * spec.tick_value
    slip = slippage_ticks * spec.tick_value
    return {"stop_ticks": ticks, "stop_points": float(ticks * spec.tick), "gross_usd": round(gross, 2),
            "slippage_usd": round(slip, 2), "costs_usd": round(round_turn_cost, 2), "total_usd": round(gross + slip + round_turn_cost, 2)}


def size_for_risk(budget_usd: float, entry: float, stop: float, spec: ProductSpec, slippage_ticks: float = 0.0,
                  round_turn_cost: float = 0.0, max_contracts: int | None = None) -> dict:
    """Contracts such that (stop distance + expected slippage + fees) x contracts <= budget. Never rounds up."""
    r = risk_per_contract(entry, stop, spec, slippage_ticks, round_turn_cost)
    if r["stop_ticks"] == 0:
        return {**r, "contracts": 0, "reason": "Stop is on the entry price (0 ticks)."}
    n = int(budget_usd // r["total_usd"]) if r["total_usd"] > 0 else 0
    reason = None
    if max_contracts is not None and n > max_contracts:
        n, reason = max_contracts, f"Capped at {max_contracts} by your limits."
    if n == 0:
        reason = (f"One contract risks ${r['total_usd']:,.2f} including slippage and fees, more than the ${budget_usd:,.2f} "
                  f"budget. Use a micro, a tighter stop that still makes sense, or skip the trade.")
    return {**r, "contracts": n, "risk_usd": round(n * r["total_usd"], 2), "reason": reason}


# ---------------- business days and expirations ----------------

@lru_cache(maxsize=8)
def _holidays(calendar: str = "XNYS") -> frozenset[date]:
    """Exchange holidays used for business-day counting in expiration rules. CME settlement holidays match
    the NYSE list closely; exchange_calendars covers about a year ahead of today."""
    try:
        import exchange_calendars as xc
        import pandas as pd

        cal = xc.get_calendar(calendar)
        days = pd.bdate_range(cal.first_session, cal.last_session)
        sessions = set(cal.sessions)
        return frozenset(d.date() for d in days if d not in sessions)
    except Exception:  # pragma: no cover
        log.exception("holiday calendar unavailable")
        return frozenset()


def holiday_coverage() -> tuple[date, date] | None:
    try:
        import exchange_calendars as xc

        cal = xc.get_calendar("XNYS")
        return cal.first_session.date(), cal.last_session.date()
    except Exception:  # pragma: no cover
        return None


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in _holidays()


def add_business_days(d: date, n: int) -> date:
    step = 1 if n >= 0 else -1
    left = abs(n)
    while left:
        d += timedelta(days=step)
        if is_business_day(d):
            left -= 1
    return d


def prev_business_day(d: date) -> date:
    while not is_business_day(d):
        d -= timedelta(days=1)
    return d


def third_friday(year: int, month: int) -> date:
    d = date(year, month, 15)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def last_trade_date(spec: ProductSpec, year: int, month: int) -> date:
    if spec.expiry_rule == "equity_quarterly":
        return prev_business_day(third_friday(year, month))  # e.g. June 2026: Juneteenth Friday -> Thursday June 18
    if spec.expiry_rule == "cl_monthly":
        y, m = (year, month - 1) if month > 1 else (year - 1, 12)
        d25 = date(y, m, 25)
        return add_business_days(d25, -3 if is_business_day(d25) else -4)
    if spec.expiry_rule == "gc_third_last":
        last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
        d = prev_business_day(last)
        return add_business_days(d, -2)
    raise ValueError(f"No expiration rule '{spec.expiry_rule}'")


def roll_date(spec: ProductSpec, year: int, month: int) -> date:
    """The first trade date on which the NEXT contract is treated as the front month."""
    ltd = last_trade_date(spec, year, month)
    if spec.roll_rule == "cme_equity_monday":
        tf = third_friday(year, month)
        monday = tf - timedelta(days=4)
        return monday if is_business_day(monday) else add_business_days(monday, 1)
    if spec.roll_rule == "business_days_before_expiry":
        return add_business_days(ltd, -spec.roll_days)
    if spec.roll_rule == "gc_first_position_day":
        first = date(year, month, 1)
        first_bd = first if is_business_day(first) else add_business_days(first, 1)
        return add_business_days(first_bd, -2)
    raise ValueError(f"No roll rule '{spec.roll_rule}'")


@dataclass(frozen=True)
class Contract:
    root: str
    year: int
    month: int

    @property
    def code(self) -> str:
        return f"{self.root}{MONTH_CODES[self.month - 1]}{self.year % 100:02d}"

    @property
    def short_code(self) -> str:
        """Single-digit year, as TopstepX/ProjectX and many platforms display it: NQZ6."""
        return f"{self.root}{MONTH_CODES[self.month - 1]}{self.year % 10}"

    @property
    def spec(self) -> ProductSpec:
        return get(self.root)

    @property
    def yahoo_symbol(self) -> str:
        return f"{self.code}.{self.spec.yahoo_suffix}"

    @property
    def last_trade(self) -> date:
        return last_trade_date(self.spec, self.year, self.month)

    @property
    def roll(self) -> date:
        return roll_date(self.spec, self.year, self.month)

    def to_dict(self, today: date | None = None) -> dict:
        today = today or datetime.now(CT).date()
        ltd = self.last_trade
        return {"code": self.code, "short_code": self.short_code, "root": self.root, "year": self.year, "month": self.month,
                "month_code": MONTH_CODES[self.month - 1], "yahoo_symbol": self.yahoo_symbol,
                "last_trade_date": ltd.isoformat(), "last_trade_time_ct": self.spec.last_trade_time_ct,
                "roll_date": self.roll.isoformat(), "days_to_last_trade": (ltd - today).days,
                "expired": today > ltd, "in_roll_window": today >= self.roll}


def _chain(spec: ProductSpec, start: date, n: int) -> list[Contract]:
    out, y, m = [], start.year, start.month
    while len(out) < n:
        if MONTH_CODES[m - 1] in spec.months:
            out.append(Contract(spec.root, y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def front_contract(root: str, on: date | None = None) -> Contract:
    """The contract most traders are on for trade date `on`: the nearest listed month whose roll date is still ahead."""
    spec = get(root)
    on = on or datetime.now(CT).date()
    for c in _chain(spec, date(on.year, on.month, 1) - timedelta(days=0), 14):
        if on < c.roll:
            return c
    raise RuntimeError(f"No front contract found for {root} on {on}")


def next_contracts(root: str, on: date | None = None, n: int = 3) -> list[Contract]:
    f = front_contract(root, on)
    spec = get(root)
    return _chain(spec, date(f.year, f.month, 1), n)


# ---------------- symbol parsing ----------------

_PARSE = [
    re.compile(r"^CON\.F\.US\.(?P<api>[A-Z0-9]+)\.(?P<m>[FGHJKMNQUVXZ])(?P<y>\d{2})$"),   # ProjectX contract id
    re.compile(r"^/?(?P<root>[A-Z0-9]{1,4}?)(?P<m>[FGHJKMNQUVXZ])(?P<y>\d{4}|\d{2}|\d)(?:\.[A-Z]{3})?$"),
    re.compile(r"^/?(?P<root>[A-Z0-9]{1,4})(?:1!|2!|=F)$"),                              # TradingView continuous / Yahoo
    re.compile(r"^/(?P<root>[A-Z0-9]{1,4})$"),                                           # TopstepX/thinkorswim root
]
# ProjectX uses its own symbol roots for some products (NQ shows as F.US.ENQ). Contract names ("NQZ6") still
# use the CME root, and Study Terminal always looks contracts up by name, so this map is only a parsing aid.
_API_ROOTS = {"ENQ": "NQ", "EP": "ES", "MES": "MES", "MNQ": "MNQ", "YM": "YM", "MYM": "MYM", "RTY": "RTY", "M2K": "M2K",
              "CLE": "CL", "GCE": "GC"}


@dataclass
class ParsedSymbol:
    root: str
    contract: Contract | None = None
    continuous: bool = False
    raw: str = ""
    year_ambiguous: bool = False
    note: str | None = None
    candidates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"root": self.root, "contract": self.contract.code if self.contract else None, "continuous": self.continuous,
                "raw": self.raw, "year_ambiguous": self.year_ambiguous, "note": self.note}


def _resolve_year(y: str, month: int, today: date) -> tuple[int, bool]:
    if len(y) == 4:
        return int(y), False
    if len(y) == 2:
        return 2000 + int(y), False
    # one digit: the nearest year ending in that digit that isn't more than ~1 year in the past
    base = today.year - today.year % 10 + int(y)
    for cand in (base - 10, base, base + 10):
        if date(cand, month, 28) >= today - timedelta(days=370):
            return cand, False
    return base, True


def parse_symbol(text: str, today: date | None = None, allow_bare_root: bool = False) -> ParsedSymbol | None:
    """Read futures symbols as platforms display them: ESZ6, ESZ26, ESZ2026, /ES, /ESZ6, ES1!, ES=F, ESZ26.CME,
    CON.F.US.ENQ.Z25. Returns None for anything that isn't a known product."""
    raw = (text or "").strip().upper().replace(" ", "")
    raw = raw.split(":")[-1]  # CME_MINI:ESZ2026
    today = today or datetime.now(CT).date()
    known = products()
    if allow_bare_root and raw in known:   # "ES" typed into Study Terminal; never used for screen text (ES is also a stock)
        return ParsedSymbol(raw, None, continuous=True, raw=raw, note="Root symbol: the front contract is used.")
    for pat in _PARSE:
        m = pat.match(raw)
        if not m:
            continue
        gd = m.groupdict()
        root = gd.get("root") or _API_ROOTS.get(gd.get("api", ""), gd.get("api", ""))
        if root not in known:
            continue
        if "m" in gd and gd.get("m"):
            month = CODE_TO_MONTH[gd["m"]]
            if MONTH_CODES[month - 1] not in known[root].months and known[root].expiry_rule != "gc_third_last":
                return ParsedSymbol(root, None, raw=raw, note=f"{root} doesn't list {gd['m']} contracts; ignoring the month.")
            year, amb = _resolve_year(gd["y"], month, today)
            return ParsedSymbol(root, Contract(root, year, month), raw=raw, year_ambiguous=amb)
        return ParsedSymbol(root, None, continuous=True, raw=raw,
                            note="Continuous or root symbol: the front contract is assumed, which can differ near a roll.")
    return None


def all_specs_dict() -> list[dict]:
    return [p.to_dict() for p in sorted(products().values(), key=lambda p: (p.group, p.root))]


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))
