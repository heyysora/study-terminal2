"""Futures paper simulator. Separate from the stock simulator: contracts, ticks, per-contract fees, 23-hour
sessions, trade dates that start at 17:00 CT, end-of-day trailing drawdown.

Never sends anything anywhere. There is no code path to a broker or to TopstepX order endpoints.

Fill model (deliberately conservative, documented in the UI):
  * Market: next price seen, plus adverse slippage (default 1 tick).
  * Stop (stop-market): triggers when price trades at/through the stop; fills at the stop or the gap price,
    whichever is worse, plus slippage.
  * Limit: fills only when price trades THROUGH the limit by at least one tick (a touch is not a fill, since
    you'd be at the back of the queue). Gaps through the limit fill at the better open.
  * Partial fills: with bar volume available, each bar fills at most `participation` of that bar's volume.
  * A bar that reaches both the stop and the target counts as a stop (worst case).
  * Prices can only fill on data marked tradable (live), unless you turn on delayed practice or use replay,
    and every such fill is labeled with what it was filled against.
"""
from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from . import contracts as fc
from .risk import AccountSnapshot, PersonalRisk, PropRules, RiskEngine, mini_equivalent, next_eod_floor, next_intraday_floor
from .sessions import FuturesClock

TRADABLE = {"realtime", "near_realtime", "polling"}


@dataclass
class FuturesPaperConfig:
    slippage_ticks_market: float = 1.0
    slippage_ticks_stop: float = 1.0
    participation: float = 0.10          # max share of a bar's volume one order can take
    fees_round_turn: dict = field(default_factory=dict)   # root -> USD per contract round turn
    auto_flatten: bool = True            # flatten at the prop rules' flat time
    allow_delayed_practice: bool = False # fill against delayed quotes (labeled) when no live feed exists

    @classmethod
    def from_dict(cls, d: dict | None) -> "FuturesPaperConfig":
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (d or {}).items() if k in names})

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FOrder:
    id: str
    contract: str
    root: str
    side: int                 # +1 buy, -1 sell
    qty: int
    type: str                 # market | limit | stop
    limit_price: float | None = None
    stop_price: float | None = None
    role: str = "entry"       # entry | stop_loss | take_profit | exit | flatten
    parent_id: str | None = None
    oco: str | None = None
    status: str = "working"   # working | partial | filled | canceled | rejected
    filled_qty: int = 0
    avg_fill: float | None = None
    created_at: str = ""
    updated_at: str = ""
    reason: str | None = None
    bracket: dict | None = None   # entry only: {"stop": px, "targets": [{"price":, "qty":}]}
    signal_id: str | None = None
    note: str | None = None

    @property
    def remaining(self) -> int:
        return self.qty - self.filled_qty

    @property
    def active(self) -> bool:
        return self.status in ("working", "partial")


@dataclass
class FFill:
    id: str
    order_id: str
    contract: str
    root: str
    side: int
    qty: int
    price: float
    ts: str
    trade_date: str | None
    fee: float
    slippage_ticks: float
    basis: str
    role: str
    realized: float = 0.0
    fee_note: str | None = None


@dataclass
class FPosition:
    contract: str
    root: str
    qty: int = 0              # signed
    avg_price: float = 0.0
    mark: float | None = None
    mark_ts: str | None = None
    mark_status: str | None = None
    opened_at: str | None = None
    trip_net: float = 0.0     # net P&L (after fees) of the round trip in progress


def _iso(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).isoformat()


class FuturesPaperEngine:
    def __init__(self, rules: PropRules, personal: PersonalRisk, cfg: FuturesPaperConfig | None = None, fees_default: dict | None = None):
        self.rules, self.personal = rules, personal
        self.cfg = cfg or FuturesPaperConfig()
        self.fees_default = fees_default or {}
        self.reset()

    # ---------------- state ----------------

    def reset(self, now: datetime | None = None) -> None:
        self.balance = float(self.rules.starting_balance)
        self.fees_paid = 0.0
        self.orders: dict[str, FOrder] = {}
        self.fills: list[FFill] = []
        self.positions: dict[str, FPosition] = {}
        self.daily: dict[str, float] = {}         # closed trade date -> net P&L
        self.day_realized: dict[str, float] = {}  # running realized (net of fees) per trade date
        self.trades_today: dict[str, list[float]] = {}
        self.mll_floor = self.rules.initial_floor()
        self.equity_high = self.balance
        self.current_trade_date: str | None = None
        self.locks: dict = {}
        self.review_log: list[dict] = []
        self.events: list[dict] = []
        self.created_at = _iso(now or datetime.now(timezone.utc))

    def to_state(self) -> dict:
        return {"balance": self.balance, "fees_paid": self.fees_paid, "orders": [asdict(o) for o in self.orders.values()],
                "fills": [asdict(f) for f in self.fills[-2000:]], "positions": [asdict(p) for p in self.positions.values()],
                "daily": self.daily, "day_realized": self.day_realized, "trades_today": self.trades_today,
                "mll_floor": self.mll_floor, "equity_high": self.equity_high, "current_trade_date": self.current_trade_date,
                "locks": self.locks, "review_log": self.review_log[-200:], "events": self.events[-300:], "created_at": self.created_at}

    def load_state(self, st: dict) -> None:
        self.balance, self.fees_paid = st["balance"], st.get("fees_paid", 0.0)
        self.orders = {o["id"]: FOrder(**o) for o in st.get("orders", [])}
        self.fills = [FFill(**f) for f in st.get("fills", [])]
        self.positions = {p["contract"]: FPosition(**p) for p in st.get("positions", [])}
        self.daily, self.day_realized = st.get("daily", {}), st.get("day_realized", {})
        self.trades_today = st.get("trades_today", {})
        self.mll_floor, self.equity_high = st.get("mll_floor"), st.get("equity_high", self.balance)
        self.current_trade_date = st.get("current_trade_date")
        self.locks, self.review_log = st.get("locks", {}), st.get("review_log", [])
        self.events, self.created_at = st.get("events", []), st.get("created_at", "")

    def _event(self, level: str, text: str, ts: datetime | None = None) -> None:
        self.events.append({"at": _iso(ts or datetime.now(timezone.utc)), "level": level, "text": text})

    # ---------------- money ----------------

    def fee_per_side(self, root: str) -> tuple[float, str | None]:
        spec = fc.get(root)
        rt = self.cfg.fees_round_turn.get(root)
        if rt is None:
            rt = self.fees_default.get(root)
        if rt is not None:
            return float(rt) / 2, None
        commission = 0.50 if spec.micro_of else 1.00
        return commission / 2, f"Exchange fee for {root} isn't set; only the ${commission:.2f} round-turn commission is charged. Set it in Settings."

    def round_turn(self, root: str) -> float:
        return round(self.fee_per_side(root)[0] * 2, 2)

    def unrealized(self) -> float:
        tot = 0.0
        for p in self.positions.values():
            if p.qty and p.mark is not None:
                tot += fc.pnl_usd(p.avg_price, p.mark, abs(p.qty), 1 if p.qty > 0 else -1, fc.get(p.root))
        return round(tot, 2)

    def open_risk(self) -> tuple[float | None, list[str]]:
        total, missing = 0.0, []
        for p in self.positions.values():
            if not p.qty:
                continue
            stops = [o for o in self.orders.values() if o.active and o.contract == p.contract and o.role == "stop_loss"]
            if not stops:
                missing.append(p.contract)
                continue
            spec = fc.get(p.root)
            for o in stops:
                total += max(0.0, -fc.pnl_usd(p.avg_price, o.stop_price, o.remaining, 1 if p.qty > 0 else -1, spec))
        return (None if missing else round(total, 2)), missing

    def open_mini_eq(self) -> float:
        return sum(mini_equivalent(fc.get(p.root), abs(p.qty), self.rules) for p in self.positions.values() if p.qty)

    def snapshot(self, now: datetime, clock: FuturesClock | None = None) -> AccountSnapshot:
        td = self.current_trade_date
        risk, missing = self.open_risk()
        unreal = self.unrealized()
        day = self.day_realized.get(td, 0.0) + unreal if td else unreal
        tlist = self.trades_today.get(td or "", [])
        consec = 0
        for x in reversed(tlist):
            if x < 0:
                consec += 1
            else:
                break
        return AccountSnapshot(now=now, trade_date=td, balance=self.balance, unrealized=unreal, day_pnl=round(day, 2),
                               mll_floor=self.mll_floor, daily_results=dict(self.daily), consecutive_losses=consec,
                               open_mini_equivalent=self.open_mini_eq(), open_risk_usd=risk, unprotected=missing, locks=self.locks,
                               rth=clock.is_rth(now) if clock else True)

    def risk_status(self, now: datetime, clock: FuturesClock | None = None) -> dict:
        return RiskEngine(self.rules, self.personal).evaluate(self.snapshot(now, clock))

    # ---------------- day boundaries ----------------

    def on_clock(self, now: datetime, trade_date: str | None) -> None:
        """Advance trade dates. Closing a trade date records its P&L and moves the trailing floor (end of day)."""
        if trade_date and trade_date != self.current_trade_date:
            prev = self.current_trade_date
            if prev is not None:
                self.close_trade_date(prev, now)
            self.current_trade_date = trade_date
            self.locks = {k: v for k, v in self.locks.items() if k in ("mll_breached", "consecutive")}
            self.locks.pop("consecutive", None)

    def close_trade_date(self, td: str, now: datetime) -> None:
        net = round(self.day_realized.get(td, 0.0), 2)
        self.daily[td] = net
        eod = self.balance + self.unrealized()
        old = self.mll_floor
        self.mll_floor = next_eod_floor(self.rules, self.mll_floor, eod)
        msg = f"Trade date {td} closed: net ${net:,.2f}, end-of-day balance ${eod:,.2f}."
        if old is not None and self.mll_floor != old:
            msg += f" Maximum Loss Limit floor moved ${old:,.2f} -> ${self.mll_floor:,.2f}."
        self._event("info", msg, now)

    # ---------------- orders ----------------

    def preview(self, contract: str, side: int, qty: int, type_: str, limit_price: float | None, stop_price: float | None,
                bracket: dict | None, ref_price: float | None, now: datetime, clock: FuturesClock | None = None,
                data_status: str | None = None) -> dict:
        p = fc.parse_symbol(contract)
        if not p or not p.contract:
            return {"ok": False, "problems": [f"'{contract}' isn't a specific futures contract (e.g. MESZ26)."]}
        spec = fc.get(p.root)
        problems, warns = [], []
        if qty <= 0:
            problems.append("Quantity must be at least 1 contract.")
        for name, v in (("limit", limit_price), ("stop", stop_price)):
            if v is not None and fc.round_to_tick(v, spec) != round(v, spec.decimals + 2):
                problems.append(f"The {name} price {v} isn't on {spec.root}'s {spec.tick_size} tick grid.")
        if type_ == "limit" and limit_price is None:
            problems.append("A limit order needs a limit price.")
        if type_ == "stop" and stop_price is None:
            problems.append("A stop order needs a stop price.")
        if p.contract.to_dict(now.astimezone(fc.CT).date())["expired"]:
            problems.append(f"{p.contract.code} has expired.")
        elif p.contract.to_dict(now.astimezone(fc.CT).date())["in_roll_window"]:
            warns.append(f"{p.contract.code} is past its roll date; most volume has moved to the next contract.")
        if clock and not clock.window_at(now):
            problems.append(f"{spec.root} isn't trading right now (maintenance break, weekend or holiday).")
        if data_status and data_status not in TRADABLE:
            if data_status == "delayed" and self.cfg.allow_delayed_practice:
                warns.append("Practice mode: fills use delayed prices, so they won't match what the live market did.")
            elif data_status not in ("replay",):
                problems.append(f"Market data for {spec.root} is {data_status}. The simulator only fills on live data. Turn on delayed "
                                "practice in Settings, use replay, or connect a live futures feed.")
        entry_est = {"market": ref_price, "limit": limit_price, "stop": stop_price}.get(type_)
        slip = self.cfg.slippage_ticks_market if type_ == "market" else self.cfg.slippage_ticks_stop if type_ == "stop" else 0
        stop = (bracket or {}).get("stop")
        targets = [t["price"] for t in (bracket or {}).get("targets", [])]
        pos = self.positions.get(p.contract.code)
        reducing = pos and pos.qty and (pos.qty > 0) != (side > 0) and qty <= abs(pos.qty)
        risk = None
        if not reducing:
            chk = RiskEngine(self.rules, self.personal).check_entry(self.snapshot(now, clock), spec, qty, entry_est, stop, targets,
                                                                   self.round_turn(spec.root), slip, side)
            problems += chk["problems"]
            warns += chk["warnings"]
            risk = chk["risk"]
        if bracket:
            tq = sum(int(t.get("qty", 0)) for t in bracket.get("targets", []))
            if tq > qty:
                problems.append("Target quantities add up to more than the order quantity.")
            for t in targets + ([stop] if stop is not None else []):
                if fc.round_to_tick(t, spec) != round(t, spec.decimals + 2):
                    problems.append(f"Bracket price {t} isn't on the {spec.tick_size} tick grid.")
        fee, fee_note = self.fee_per_side(spec.root)
        if fee_note:
            warns.append(fee_note)
        return {"ok": not problems, "problems": problems, "warnings": warns, "contract": p.contract.code, "risk": risk,
                "entry_estimate": entry_est, "est_fees_round_turn": round(fee * 2 * qty, 2), "slippage_ticks": slip,
                "reducing": bool(reducing), "sim_only": True}

    def submit(self, contract: str, side: int, qty: int, type_: str, limit_price: float | None = None, stop_price: float | None = None,
               bracket: dict | None = None, ref_price: float | None = None, now: datetime | None = None,
               clock: FuturesClock | None = None, data_status: str | None = None, signal_id: str | None = None,
               role: str = "entry") -> tuple[FOrder | None, dict]:
        now = now or datetime.now(timezone.utc)
        pv = self.preview(contract, side, qty, type_, limit_price, stop_price, bracket, ref_price, now, clock, data_status)
        if not pv["ok"]:
            return None, pv
        p = fc.parse_symbol(contract)
        o = FOrder(id=uuid.uuid4().hex[:12], contract=p.contract.code, root=p.root, side=side, qty=qty, type=type_,
                   limit_price=limit_price, stop_price=stop_price, role="exit" if pv["reducing"] and role == "entry" else role,
                   bracket=bracket, created_at=_iso(now), updated_at=_iso(now), signal_id=signal_id)
        self.orders[o.id] = o
        self._event("info", f"Paper order: {'BUY' if side > 0 else 'SELL'} {qty} {o.contract} {type_}"
                    + (f" @ {limit_price}" if limit_price else "") + (f" stop {stop_price}" if stop_price else ""), now)
        return o, pv

    def cancel(self, order_id: str, now: datetime | None = None, reason: str = "Canceled by you") -> FOrder:
        o = self.orders[order_id]
        if o.active:
            o.status, o.reason, o.updated_at = "canceled", reason, _iso(now or datetime.now(timezone.utc))
            if o.role == "entry":   # canceling an entry cancels its unfilled bracket children too
                for c in self.orders.values():
                    if c.parent_id == o.id and c.active and not self.positions.get(o.contract, FPosition(o.contract, o.root)).qty:
                        c.status, c.reason = "canceled", "Entry canceled"
        return o

    def flatten(self, contract: str | None, now: datetime, reason: str = "Flattened by you", price: float | None = None,
                ts_basis: str = "last price") -> list[FFill]:
        out = []
        for c, p in list(self.positions.items()):
            if contract and c != contract or not p.qty:
                continue
            for o in self.orders.values():
                if o.contract == c and o.active:
                    o.status, o.reason, o.updated_at = "canceled", reason, _iso(now)
            px = price if price is not None else p.mark
            if px is None:
                continue
            o = FOrder(id=uuid.uuid4().hex[:12], contract=c, root=p.root, side=-1 if p.qty > 0 else 1, qty=abs(p.qty), type="market",
                       role="flatten", created_at=_iso(now), updated_at=_iso(now), reason=reason)
            self.orders[o.id] = o
            f = self._fill(o, px, abs(p.qty), now, f"{reason}; filled at {ts_basis}", self.cfg.slippage_ticks_market)
            if f:
                out.append(f)
        return out

    # ---------------- matching ----------------

    def on_bar(self, contract: str, ts: datetime, o: float, h: float, lo: float, c: float, volume: float | None,
               status: str, clock: FuturesClock | None = None) -> list[FFill]:
        """Feed one bar (or one price as o=h=l=c). Updates marks, fills working orders, applies flat time."""
        pos = self.positions.get(contract)
        if pos:
            pos.mark, pos.mark_ts, pos.mark_status = c, _iso(ts), status
        if clock:
            w = clock.window_at(ts)
            self.on_clock(ts, w.trade_date.isoformat() if w else None)
        can_fill = status in TRADABLE or status == "replay" or (status == "delayed" and self.cfg.allow_delayed_practice)
        fills: list[FFill] = []
        if can_fill:
            basis = {"replay": "replayed historical bar", "delayed": "DELAYED price (practice mode)"}.get(status, f"{status} market data")
            budget = None if not volume else max(1, int(volume * self.cfg.participation))
            work = sorted([x for x in self.orders.values() if x.active and x.contract == contract],
                          key=lambda x: (0 if x.role == "stop_loss" else 1 if x.role in ("take_profit", "exit", "flatten") else 2, x.created_at))
            for od in work:
                if not od.active:
                    continue
                px = self._match(od, o, h, lo, fc.get(od.root))
                if px is None:
                    continue
                qty = od.remaining if budget is None else min(od.remaining, budget)
                if od.role in ("stop_loss", "take_profit", "exit"):
                    pq = self.positions.get(contract)
                    qty = min(qty, abs(pq.qty) if pq else 0)
                    if qty <= 0:
                        od.status, od.reason = "canceled", "No position left to close"
                        continue
                slip = self.cfg.slippage_ticks_market if od.type == "market" else self.cfg.slippage_ticks_stop if od.type == "stop" else 0
                capped = budget is not None and qty < od.remaining
                f = self._fill(od, px, qty, ts, basis + (f"; partial: capped at {self.cfg.participation:.0%} of bar volume" if capped else ""), slip)
                if f:
                    fills.append(f)
                    if budget is not None:
                        budget -= qty
                        if budget <= 0:
                            break
        if pos is None:
            pos = self.positions.get(contract)
            if pos:
                pos.mark, pos.mark_ts, pos.mark_status = c, _iso(ts), status
        self._check_mll(ts)
        if clock and self.cfg.auto_flatten and self.rules.enabled and self.rules.flat_by_ct and any(p.qty for p in self.positions.values()):
            t = ts.astimezone(fc.CT)
            flat = fc.parse_hhmm(self.rules.flat_by_ct)
            if t.time() >= flat and t.time() < fc.parse_hhmm(self.rules.trade_day_start_ct) and t.weekday() < 5:
                fills += self.flatten(contract, ts, f"Flattened at {self.rules.flat_by_ct} CT ({self.rules.firm} flat-by rule)", price=c)
        return fills

    def _match(self, od: FOrder, o: float, h: float, lo: float, spec: fc.ProductSpec) -> float | None:
        t = float(spec.tick)
        if od.type == "market":
            return o
        if od.type == "limit":
            L = od.limit_price
            if od.side > 0:
                if o <= L - t + 1e-9:
                    return o                       # gapped below a buy limit: fill at the better open
                return L if lo <= L - t + 1e-9 else None
            if o >= L + t - 1e-9:
                return o
            return L if h >= L + t - 1e-9 else None
        if od.type == "stop":
            S = od.stop_price
            if od.side > 0:
                if o >= S:
                    return o                       # gapped through: worse price
                return S if h >= S else None
            if o <= S:
                return o
            return S if lo <= S else None
        return None

    def _fill(self, od: FOrder, px: float, qty: int, ts: datetime, basis: str, slip_ticks: float) -> FFill | None:
        spec = fc.get(od.root)
        price = fc.round_to_tick(px + od.side * slip_ticks * float(spec.tick), spec)
        fee_side, fee_note = self.fee_per_side(od.root)
        fee = round(fee_side * qty, 2)
        pos = self.positions.setdefault(od.contract, FPosition(od.contract, od.root))
        td = self.current_trade_date
        realized = 0.0
        finished: float | None = None
        if pos.qty and (pos.qty > 0) != (od.side > 0):    # reducing / closing / flipping
            close_q = min(qty, abs(pos.qty))
            realized = fc.pnl_usd(pos.avg_price, price, close_q, 1 if pos.qty > 0 else -1, spec)
            close_fee = round(fee * close_q / qty, 2)
            pos.trip_net += realized - close_fee
            pos.qty += od.side * close_q
            rest = qty - close_q
            if pos.qty == 0:
                finished, pos.trip_net = round(pos.trip_net, 2), 0.0
                pos.avg_price, pos.opened_at = 0.0, None
            if rest:
                pos.qty, pos.avg_price, pos.opened_at = od.side * rest, price, _iso(ts)
                pos.trip_net = -(fee - close_fee)
        else:
            new_q = abs(pos.qty) + qty
            pos.avg_price = (pos.avg_price * abs(pos.qty) + price * qty) / new_q
            pos.qty += od.side * qty
            pos.opened_at = pos.opened_at or _iso(ts)
            pos.trip_net -= fee
        pos.mark, pos.mark_ts = price, _iso(ts)
        self.balance = round(self.balance + realized - fee, 2)
        self.fees_paid = round(self.fees_paid + fee, 2)
        if td:
            self.day_realized[td] = round(self.day_realized.get(td, 0.0) + realized - fee, 2)
        f = FFill(id=uuid.uuid4().hex[:12], order_id=od.id, contract=od.contract, root=od.root, side=od.side, qty=qty, price=price,
                  ts=_iso(ts), trade_date=td, fee=fee, slippage_ticks=slip_ticks, basis=basis, role=od.role, realized=realized, fee_note=fee_note)
        self.fills.append(f)
        od.filled_qty += qty
        od.avg_fill = price if od.avg_fill is None else (od.avg_fill * (od.filled_qty - qty) + price * qty) / od.filled_qty
        od.status = "filled" if od.remaining == 0 else "partial"
        od.updated_at = _iso(ts)
        if finished is not None:   # a round trip ended: it counts toward the consecutive-loss rule
            self.trades_today.setdefault(td or "", []).append(finished)
        self._after_fill(od, f, ts)
        return f

    def _after_fill(self, od: FOrder, f: FFill, ts: datetime) -> None:
        pos = self.positions[od.contract]
        if od.role == "entry" and od.bracket:
            self._sync_bracket(od, ts)
        if od.role in ("stop_loss", "take_profit"):
            # resize or cancel the siblings protecting the same position
            for c in self.orders.values():
                if c.active and c.contract == od.contract and c.id != od.id and c.role in ("stop_loss", "take_profit"):
                    if pos.qty == 0:
                        c.status, c.reason, c.updated_at = "canceled", f"Position closed by {od.role.replace('_', ' ')}", _iso(ts)
                    elif c.role == "stop_loss":
                        c.qty = c.filled_qty + abs(pos.qty)
        if pos.qty == 0:
            for c in self.orders.values():
                if c.active and c.contract == od.contract and c.role in ("stop_loss", "take_profit"):
                    c.status, c.reason, c.updated_at = "canceled", "Position is flat", _iso(ts)

    def _sync_bracket(self, entry: FOrder, ts: datetime) -> None:
        """Protective orders always cover what's actually filled (partial fills included)."""
        b = entry.bracket or {}
        kids = [c for c in self.orders.values() if c.parent_id == entry.id and c.active]
        filled = entry.filled_qty
        stop = next((c for c in kids if c.role == "stop_loss"), None)
        if b.get("stop") is not None:
            if stop:
                stop.qty = stop.filled_qty + filled - sum(c.filled_qty for c in self.orders.values() if c.parent_id == entry.id and c.role == "take_profit")
            else:
                sid = uuid.uuid4().hex[:12]
                self.orders[sid] = FOrder(id=sid, contract=entry.contract, root=entry.root, side=-entry.side, qty=filled,
                                                                    type="stop", stop_price=b["stop"], role="stop_loss", parent_id=entry.id,
                                                                    oco=entry.id, created_at=_iso(ts), updated_at=_iso(ts))
        targets = b.get("targets") or []
        if not targets:
            return
        want_total = sum(int(t["qty"]) for t in targets)
        scale = min(1.0, filled / max(want_total, 1)) if entry.remaining else 1.0
        for i, t in enumerate(targets):
            q = max(0, int(int(t["qty"]) * scale)) if entry.remaining else int(t["qty"])
            ex = next((c for c in self.orders.values() if c.parent_id == entry.id and c.role == "take_profit" and c.note == f"T{i + 1}"), None)
            if ex:
                ex.qty = max(ex.filled_qty, q)
            elif q > 0:
                tid = uuid.uuid4().hex[:12]
                self.orders[tid] = FOrder(id=tid, contract=entry.contract, root=entry.root, side=-entry.side, qty=q,
                                                                    type="limit", limit_price=t["price"], role="take_profit", parent_id=entry.id,
                                                                    oco=entry.id, created_at=_iso(ts), updated_at=_iso(ts), note=f"T{i + 1}")

    def _check_mll(self, ts: datetime) -> None:
        if self.mll_floor is None or not self.rules.enabled:
            return
        eq = self.balance + self.unrealized()
        if self.rules.mll_type == "intraday_trailing":
            self.equity_high = max(self.equity_high, eq)
            self.mll_floor = next_intraday_floor(self.rules, self.mll_floor, self.equity_high)
        if eq <= self.mll_floor and not self.locks.get("mll_breached"):
            self.locks["mll_breached"] = _iso(ts)
            self._event("critical", f"Maximum Loss Limit hit: equity ${eq:,.2f} at or below the floor ${self.mll_floor:,.2f}. "
                        "Open positions were flattened and the simulated account is locked until you reset it.", ts)
            for c, p in self.positions.items():
                if p.qty and p.mark is not None:
                    self.flatten(c, ts, "Maximum Loss Limit reached (simulated liquidation)", price=p.mark)

    # ---------------- reviews ----------------

    def manual_review(self, note: str, now: datetime) -> dict:
        """Clear personal locks that need a review (e.g. consecutive losses) after you write down what happened.
        The Maximum Loss Limit lock is not cleared here: that needs a reset, as it would on Topstep."""
        if not note or len(note.strip()) < 10:
            raise ValueError("Write at least a sentence about what happened before unlocking.")
        cleared = []
        td = self.current_trade_date or ""
        n = len(self.trades_today.get(td, []))
        if n:
            self.trades_today[td] = self.trades_today[td] + [0.0]  # a review breaks the losing streak
            cleared.append("consecutive_losses")
        self.review_log.append({"at": _iso(now), "note": note.strip(), "cleared": cleared})
        self._event("info", f"Manual review logged; cleared: {', '.join(cleared) or 'nothing'}.", now)
        return {"cleared": cleared, "note": "The Maximum Loss Limit lock can only be cleared by resetting the simulated account."}

    def summary(self, now: datetime, clock: FuturesClock | None = None) -> dict:
        return {"balance": self.balance, "equity": round(self.balance + self.unrealized(), 2), "unrealized": self.unrealized(),
                "fees_paid": self.fees_paid, "starting_balance": self.rules.starting_balance,
                "positions": [asdict(p) | {"unrealized": fc.pnl_usd(p.avg_price, p.mark, abs(p.qty), 1 if p.qty > 0 else -1, fc.get(p.root))
                                           if p.mark is not None else None} for p in self.positions.values() if p.qty],
                "orders": [asdict(o) for o in sorted(self.orders.values(), key=lambda x: x.created_at, reverse=True)[:100]],
                "working_orders": [asdict(o) for o in self.orders.values() if o.active],
                "fills": [asdict(f) for f in self.fills[-100:]][::-1], "daily": self.daily, "current_trade_date": self.current_trade_date,
                "risk": self.risk_status(now, clock), "events": self.events[-50:][::-1], "review_log": self.review_log[-20:][::-1],
                "config": self.cfg.to_dict(), "execution": "paper only: no orders are ever sent to a broker or to TopstepX"}
