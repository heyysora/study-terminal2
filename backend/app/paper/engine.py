"""Paper trading simulator. Pure Python, no broker, no network.

Simulates a margin account with:
  - market, limit, stop, stop-limit orders; DAY / GTC; optional extended hours (limit orders)
  - bracket orders: an entry with a stop-loss and/or take-profit that become an OCO pair on fill
  - long and short positions, average cost, realized and unrealized P&L
  - commissions (per share + per order), adverse slippage on market and stop fills
  - simulated short borrow fees (real borrow rates aren't available without a broker)
  - pre-trade risk checks: daily loss limit, max open positions, required stop,
    max risk per trade, buying power, minimum reward:risk (warning)

Fill rules (deliberately conservative):
  - Limit orders fill only when price trades *through* the limit (touching isn't enough).
  - Stops fill at the stop price or worse if price gapped past it, plus slippage.
  - When a bar touches both a stop-loss and a take-profit, the stop-loss is assumed first.
  - A stop-limit that triggers on a bar can only fill on a later update.
  - Orders fill completely or not at all (no partial fills).
  - Orders never fill against DELAYED, STALE, HISTORICAL or UNAVAILABLE data.

Every order comes from an explicit user action. Nothing here places orders on its own.
"""
from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from enum import Enum

from pydantic import BaseModel, field_validator, model_validator

from ..core.market_clock import ET, MarketClock, Session
from ..market_data.types import TRADABLE_STATUSES, DataStatus


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class TIF(str, Enum):
    DAY = "day"
    GTC = "gtc"


class OrderStatus(str, Enum):
    OPEN = "open"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderRole(str, Enum):
    ENTRY = "entry"            # opens or adds to a position
    EXIT = "exit"              # reduces or closes a position
    STOP_LOSS = "stop_loss"    # bracket child
    TAKE_PROFIT = "take_profit"  # bracket child


@dataclass
class PaperConfig:
    starting_cash: float = 25_000.0
    margin_multiplier: float = 2.0
    allow_short: bool = True
    commission_per_share: float = 0.0
    commission_per_order: float = 0.0
    slippage_bps: float = 1.0
    slippage_min: float = 0.01      # never less than 1 cent per share
    borrow_fee_annual_pct: float = 3.0


@dataclass
class RiskConfig:
    max_per_trade_pct: float = 0.5
    max_daily_loss_pct: float = 2.0
    max_open_positions: int = 3
    min_reward_risk: float = 2.0
    require_stop: bool = True
    max_consecutive_losses: int = 3      # losing trades in a row today before new entries are blocked
    max_exposure_pct: float = 100.0      # total position value as % of equity


class OrderRequest(BaseModel):
    symbol: str
    side: Side
    qty: int
    type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    tif: TIF = TIF.DAY
    extended_hours: bool = False
    stop_loss: float | None = None     # bracket: protective stop for the new position
    take_profit: float | None = None   # bracket: profit target for the new position
    note: str | None = None

    @field_validator("symbol")
    @classmethod
    def _sym(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def _check(self):
        if self.qty <= 0:
            raise ValueError("qty must be a positive whole number of shares")
        if self.type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and not self.limit_price:
            raise ValueError(f"{self.type.value} orders need limit_price")
        if self.type in (OrderType.STOP, OrderType.STOP_LIMIT) and not self.stop_price:
            raise ValueError(f"{self.type.value} orders need stop_price")
        for name in ("limit_price", "stop_price", "stop_loss", "take_profit"):
            v = getattr(self, name)
            if v is not None and v <= 0:
                raise ValueError(f"{name} must be positive")
        if self.extended_hours and self.type != OrderType.LIMIT:
            raise ValueError("extended-hours orders must be limit orders")
        return self


@dataclass
class PriceRef:
    price: float
    ts: datetime
    status: DataStatus
    bid: float | None = None
    ask: float | None = None


@dataclass
class Order:
    id: str
    symbol: str
    side: Side
    qty: int
    type: OrderType
    role: OrderRole
    tif: TIF
    created_at: datetime
    limit_price: float | None = None
    stop_price: float | None = None
    extended_hours: bool = False
    status: OrderStatus = OrderStatus.OPEN
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    parent_id: str | None = None
    oco_group: str | None = None
    bracket_stop: float | None = None
    bracket_target: float | None = None
    triggered: bool = False
    filled_at: datetime | None = None
    fill_price: float | None = None
    reject_reason: str | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Enum):
                d[k] = v.value
            elif isinstance(v, datetime):
                d[k] = v.isoformat()
        return d


@dataclass
class Fill:
    id: str
    order_id: str
    symbol: str
    side: Side
    qty: int
    price: float
    ref_price: float
    slippage_cost: float
    commission: float
    realized_pnl: float  # gross, before commission; 0 for opening fills
    ts: datetime
    price_basis: str     # data status the fill was based on
    role: OrderRole

    def to_dict(self) -> dict:
        d = asdict(self)
        for k, v in d.items():
            if isinstance(v, Enum):
                d[k] = v.value
            elif isinstance(v, datetime):
                d[k] = v.isoformat()
        return d


@dataclass
class Position:
    symbol: str
    qty: int  # positive long, negative short
    avg_price: float
    opened_at: datetime
    mark: float | None = None
    mark_ts: datetime | None = None
    realized_pnl: float = 0.0

    @property
    def side(self) -> str:
        return "long" if self.qty > 0 else "short"

    def market_value(self) -> float:
        return self.qty * (self.mark if self.mark is not None else self.avg_price)

    def unrealized(self) -> float:
        return (self.mark - self.avg_price) * self.qty if self.mark is not None else 0.0


@dataclass
class Account:
    starting_cash: float
    cash: float
    created_at: datetime
    realized_pnl: float = 0.0
    commissions: float = 0.0
    borrow_fees: float = 0.0
    day: date | None = None
    day_start_equity: float | None = None


@dataclass
class Preview:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    intent: str | None = None              # open_long | open_short | close_long | close_short
    est_fill_price: float | None = None
    est_notional: float | None = None
    est_commission: float | None = None
    risk_dollars: float | None = None
    max_risk_dollars: float | None = None
    reward_risk: float | None = None
    suggested_qty: int | None = None
    buying_power: float | None = None
    price_status: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def position_size(equity: float, risk_pct: float, entry: float, stop: float) -> int:
    """Shares such that hitting the stop loses about risk_pct% of equity."""
    per_share = abs(entry - stop)
    if per_share <= 0 or equity <= 0:
        return 0
    return max(0, math.floor(equity * risk_pct / 100 / per_share))


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class PaperEngine:
    def __init__(self, cfg: PaperConfig, risk: RiskConfig, clock: MarketClock, now: datetime | None = None):
        self.cfg, self.risk, self.clock = cfg, risk, clock
        now = now or datetime.now(timezone.utc)
        self.account = Account(starting_cash=cfg.starting_cash, cash=cfg.starting_cash, created_at=now)
        self.orders: dict[str, Order] = {}
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []
        self.events: list[dict] = []       # drained by the service for broadcast
        self.dirty_orders: set[str] = set()  # drained by the store for persistence
        self.new_fills: list[Fill] = []
        self.roll(now)

    # ---------------- account math ----------------

    def equity(self) -> float:
        return self.account.cash + sum(p.market_value() for p in self.positions.values())

    def unrealized(self) -> float:
        return sum(p.unrealized() for p in self.positions.values())

    def gross_exposure(self) -> float:
        return sum(abs(p.market_value()) for p in self.positions.values())

    def _reserved_for_entries(self) -> float:
        total = 0.0
        for o in self.orders.values():
            if o.status == OrderStatus.OPEN and o.role == OrderRole.ENTRY:
                px = o.limit_price or o.stop_price or self._mark(o.symbol) or 0.0
                total += px * o.qty
        return total

    def buying_power(self) -> float:
        return max(0.0, self.equity() * self.cfg.margin_multiplier - self.gross_exposure() - self._reserved_for_entries())

    def day_pnl(self) -> float:
        return self.equity() - (self.account.day_start_equity or self.account.starting_cash)

    def _mark(self, symbol: str) -> float | None:
        p = self.positions.get(symbol)
        return p.mark if p else None

    def summary(self) -> dict:
        eq = self.equity()
        dse = self.account.day_start_equity or self.account.starting_cash
        limit = dse * self.risk.max_daily_loss_pct / 100
        return {
            "mode": "paper (local simulator - no broker)",
            "starting_cash": round(self.account.starting_cash, 2),
            "cash": round(self.account.cash, 2),
            "equity": round(eq, 2),
            "buying_power": round(self.buying_power(), 2),
            "margin_multiplier": self.cfg.margin_multiplier,
            "gross_exposure": round(self.gross_exposure(), 2),
            "unrealized_pnl": round(self.unrealized(), 2),
            "realized_pnl": round(self.account.realized_pnl, 2),
            "commissions": round(self.account.commissions, 2),
            "borrow_fees": round(self.account.borrow_fees, 2),
            "total_pnl": round(eq - self.account.starting_cash, 2),
            "day_pnl": round(eq - dse, 2),
            "day_start_equity": round(dse, 2),
            "daily_loss_limit": round(limit, 2),
            "daily_loss_limit_hit": (eq - dse) <= -limit,
            "open_positions": len(self.positions),
            "open_orders": sum(1 for o in self.orders.values() if o.status == OrderStatus.OPEN),
            "week_pnl": round(self._period_realized(7) + self.unrealized(), 2),
            "consecutive_losses_today": self.consecutive_losses_today(),
            "max_consecutive_losses": self.risk.max_consecutive_losses,
            "exposure_pct": round(100 * self.gross_exposure() / eq, 1) if eq > 0 else None,
        }

    def _period_realized(self, days: int) -> float:
        """Realized P&L net of commissions since the start of this ISO week (days=7) or today (days=1)."""
        now_et = datetime.now(timezone.utc).astimezone(ET)
        start = now_et.date() - timedelta(days=now_et.weekday()) if days == 7 else now_et.date()
        return sum(f.realized_pnl - f.commission for f in self.fills if f.ts.astimezone(ET).date() >= start)

    def consecutive_losses_today(self) -> int:
        today = (self.account.day or datetime.now(timezone.utc).astimezone(ET).date())
        n = 0
        for f in reversed(self.fills):
            if f.ts.astimezone(ET).date() != today:
                break
            if f.role == OrderRole.ENTRY:
                continue
            if f.realized_pnl - f.commission < 0:
                n += 1
            else:
                break
        return n

    # ---------------- day handling ----------------

    def roll(self, now: datetime) -> None:
        """Call regularly. Starts a new trading day, charges borrow fees, expires DAY orders."""
        today = now.astimezone(ET).date()
        if self.account.day != today:
            if self.account.day is not None:
                days = (today - self.account.day).days
                for p in self.positions.values():
                    if p.qty < 0:
                        fee = abs(p.market_value()) * self.cfg.borrow_fee_annual_pct / 100 / 360 * days
                        self.account.cash -= fee
                        self.account.borrow_fees += fee
            self.account.day = today
            self.account.day_start_equity = self.equity()
            self.events.append({"type": "paper_account", "data": self.summary()})
        for o in list(self.orders.values()):
            if o.status == OrderStatus.OPEN and o.expires_at and now >= o.expires_at:
                self._set_status(o, OrderStatus.EXPIRED, now, "Day order expired at session end")

    def _day_order_expiry(self, now: datetime, extended: bool) -> datetime | None:
        now_et = now.astimezone(ET)
        for i in range(0, 10):
            d = now_et.date() + timedelta(days=i)
            td, _ = self.clock.trading_day(d)
            if not td:
                continue
            end = datetime.combine(d, td.session_close if extended else td.regular_close, tzinfo=ET)
            if end > now_et:
                return end.astimezone(timezone.utc)
        return None

    # ---------------- validation ----------------

    def _intent(self, req: OrderRequest) -> tuple[str | None, str | None]:
        pos = self.positions.get(req.symbol)
        q = pos.qty if pos else 0
        if req.side == Side.BUY:
            if q >= 0:
                return "open_long", None
            if req.qty > -q:
                return None, f"Buying {req.qty} would flip your {-q}-share short into a long. Cover {-q} first."
            return "close_short", None
        if q > 0:
            if req.qty > q:
                return None, f"Selling {req.qty} would flip your {q}-share long into a short. Sell {q} first."
            return "close_long", None
        return "open_short", None

    def _available_to_close(self, symbol: str) -> int:
        pos = self.positions.get(symbol)
        if not pos:
            return 0
        reserved, seen_groups = 0, set()
        for o in self.orders.values():
            if o.status != OrderStatus.OPEN or o.symbol != symbol or o.role == OrderRole.ENTRY:
                continue
            if o.oco_group:
                if o.oco_group in seen_groups:
                    continue
                seen_groups.add(o.oco_group)
            reserved += o.qty
        return abs(pos.qty) - reserved

    def _slip(self, px: float, side: Side) -> float:
        if self.cfg.slippage_bps <= 0 and self.cfg.slippage_min <= 0:
            return px
        s = max(px * self.cfg.slippage_bps / 10_000, self.cfg.slippage_min)
        return px + s if side == Side.BUY else px - s

    def _commission(self, qty: int) -> float:
        return self.cfg.commission_per_order + self.cfg.commission_per_share * qty

    def _est_fill(self, req: OrderRequest, ref: PriceRef | None) -> float | None:
        if req.type == OrderType.MARKET:
            if not ref:
                return None
            base = (ref.ask if req.side == Side.BUY else ref.bid) or ref.price
            return self._slip(base, req.side)
        if req.type == OrderType.LIMIT:
            return req.limit_price
        if req.type == OrderType.STOP:
            return self._slip(req.stop_price, req.side)
        return req.limit_price

    def _session_allows(self, ts: datetime, extended: bool) -> bool:
        s = self.clock.session_of(ts)
        return s == Session.REGULAR or (extended and s in (Session.PREMARKET, Session.AFTER_HOURS))

    def preview(self, req: OrderRequest, ref: PriceRef | None, now: datetime | None = None) -> Preview:
        now = now or datetime.now(timezone.utc)
        p = Preview(ok=False, buying_power=round(self.buying_power(), 2), price_status=ref.status.value if ref else None)

        intent, err = self._intent(req)
        if err:
            p.errors.append(err)
            return p
        p.intent = intent
        opening = intent.startswith("open")

        if req.type == OrderType.MARKET:
            if ref is None or ref.status not in TRADABLE_STATUSES:
                status = ref.status.value if ref else "unavailable"
                p.errors.append(f"No usable price for {req.symbol} (data is {status}). Market orders need fresh data.")
            if not self._session_allows(now, False):
                p.errors.append("Market is not in regular hours. Market orders fill only 09:30-16:00 ET; "
                                "use a limit order with extended hours, or wait for the open.")
        if req.extended_hours and req.tif != TIF.DAY:
            p.warnings.append("Extended-hours flag applies to DAY orders only in this simulator; order treated as DAY.")

        est = self._est_fill(req, ref)
        p.est_fill_price = round(est, 4) if est else None
        p.est_commission = round(self._commission(req.qty), 2)
        if est:
            p.est_notional = round(est * req.qty, 2)

        if not opening:
            avail = self._available_to_close(req.symbol)
            if req.qty > avail:
                p.errors.append(f"Only {max(avail, 0)} shares are free to close; the rest are held by working "
                                "stop-loss/take-profit orders. Cancel those or use Close Position.")
            if req.stop_loss or req.take_profit:
                p.warnings.append("stop_loss/take_profit are ignored on orders that reduce a position.")
            p.ok = not p.errors
            return p

        # ---- opening-order risk checks ----
        long = intent == "open_long"
        eq = self.equity()
        s = self.summary()
        if self.risk.max_consecutive_losses and s["consecutive_losses_today"] >= self.risk.max_consecutive_losses:
            p.errors.append(f"{s['consecutive_losses_today']} losing trades in a row today (limit {self.risk.max_consecutive_losses}). "
                            "New entries are paused for the day - this is when frustration trades happen.")
        if s["daily_loss_limit_hit"]:
            p.errors.append(f"Daily loss limit reached (day P&L ${s['day_pnl']:,.2f}, limit -${s['daily_loss_limit']:,.2f}). "
                            "New entries are disabled until tomorrow. Consider stopping for the day.")
        new_symbol = req.symbol not in self.positions
        pending_new = {o.symbol for o in self.orders.values()
                       if o.status == OrderStatus.OPEN and o.role == OrderRole.ENTRY and o.symbol not in self.positions}
        if new_symbol and req.symbol not in pending_new and len(self.positions) + len(pending_new) >= self.risk.max_open_positions:
            p.errors.append(f"Max open positions is {self.risk.max_open_positions} (including pending entries).")
        if not long:
            if not self.cfg.allow_short or self.cfg.margin_multiplier <= 1:
                p.errors.append("Short selling is disabled (cash account or PAPER_ALLOW_SHORT=false).")
            else:
                p.warnings.append("Short sale simulated: borrow availability, borrow fees and short-sale "
                                  "restrictions are NOT verified without a broker. Losses on shorts are unlimited.")

        stop = req.stop_loss
        if stop is None:
            if self.risk.require_stop:
                p.errors.append("Every entry needs a stop loss (risk setting). Add stop_loss.")
        elif est:
            if long and stop >= est:
                p.errors.append(f"Stop loss {stop} must be below the entry (~{est:.2f}) for a long.")
            elif not long and stop <= est:
                p.errors.append(f"Stop loss {stop} must be above the entry (~{est:.2f}) for a short.")
            else:
                per_share = abs(est - stop)
                p.risk_dollars = round(per_share * req.qty + 2 * self._commission(req.qty), 2)
                p.max_risk_dollars = round(eq * self.risk.max_per_trade_pct / 100, 2)
                p.suggested_qty = position_size(eq, self.risk.max_per_trade_pct, est, stop)
                if p.risk_dollars > p.max_risk_dollars * 1.0001:
                    p.errors.append(f"Risk ${p.risk_dollars:,.2f} exceeds the {self.risk.max_per_trade_pct}% per-trade limit "
                                    f"(${p.max_risk_dollars:,.2f}). Suggested size: {p.suggested_qty} shares.")
        if req.take_profit is not None and est:
            if long and req.take_profit <= est or not long and req.take_profit >= est:
                p.errors.append(f"Take profit {req.take_profit} is on the wrong side of the entry (~{est:.2f}).")
            elif stop is not None and abs(est - stop) > 0:
                p.reward_risk = round(abs(req.take_profit - est) / abs(est - stop), 2)
                if p.reward_risk < self.risk.min_reward_risk:
                    p.warnings.append(f"Reward:risk is {p.reward_risk}:1, below your preferred {self.risk.min_reward_risk}:1.")
        if est and eq > 0 and (self.gross_exposure() + est * req.qty) > eq * self.risk.max_exposure_pct / 100 + 1e-6:
            p.errors.append(f"Total exposure would be ${self.gross_exposure() + est * req.qty:,.0f}, above your "
                            f"{self.risk.max_exposure_pct:.0f}% of equity limit (${eq * self.risk.max_exposure_pct / 100:,.0f}).")
        if est and est * req.qty > self.buying_power():
            p.errors.append(f"Not enough buying power: need ${est * req.qty:,.2f}, have ${self.buying_power():,.2f}.")
        p.ok = not p.errors
        return p

    # ---------------- actions ----------------

    def submit(self, req: OrderRequest, ref: PriceRef | None, now: datetime | None = None) -> tuple[Order, Preview]:
        now = now or datetime.now(timezone.utc)
        pv = self.preview(req, ref, now)
        role = OrderRole.ENTRY if pv.intent and pv.intent.startswith("open") else OrderRole.EXIT
        o = Order(id=_new_id(), symbol=req.symbol, side=req.side, qty=req.qty, type=req.type, role=role, tif=req.tif,
                  created_at=now, updated_at=now, limit_price=req.limit_price, stop_price=req.stop_price,
                  extended_hours=req.extended_hours, note=req.note,
                  bracket_stop=req.stop_loss if role == OrderRole.ENTRY else None,
                  bracket_target=req.take_profit if role == OrderRole.ENTRY else None)
        self.orders[o.id] = o
        if not pv.ok:
            o.status, o.reject_reason = OrderStatus.REJECTED, " ".join(pv.errors)
            self._touch(o)
            return o, pv
        if o.tif == TIF.DAY:
            o.expires_at = self._day_order_expiry(now, o.extended_hours)
        self._touch(o)
        if o.type == OrderType.MARKET and ref is not None:
            base = (ref.ask if o.side == Side.BUY else ref.bid) or ref.price
            self._fill(o, self._slip(base, o.side), base, now, ref.status.value)
        return o, pv

    def cancel(self, order_id: str, now: datetime | None = None, reason: str = "Canceled by you") -> Order:
        o = self.orders.get(order_id)
        if o is None:
            raise KeyError(order_id)
        if o.status != OrderStatus.OPEN:
            raise ValueError(f"Order is already {o.status.value}")
        self._set_status(o, OrderStatus.CANCELED, now or datetime.now(timezone.utc), reason)
        return o

    def close_position(self, symbol: str, ref: PriceRef | None, now: datetime | None = None) -> tuple[Order, Preview]:
        now = now or datetime.now(timezone.utc)
        pos = self.positions.get(symbol.upper())
        if not pos:
            raise KeyError(symbol)
        for o in list(self.orders.values()):
            if o.status == OrderStatus.OPEN and o.symbol == pos.symbol and o.role != OrderRole.ENTRY:
                self._set_status(o, OrderStatus.CANCELED, now, "Canceled to close position")
        req = OrderRequest(symbol=pos.symbol, side=Side.SELL if pos.qty > 0 else Side.BUY, qty=abs(pos.qty),
                           type=OrderType.MARKET, note="close position")
        return self.submit(req, ref, now)

    # ---------------- market updates ----------------

    def on_price(self, symbol: str, last: float, ts: datetime, status: DataStatus,
                 high: float | None = None, low: float | None = None, open_: float | None = None,
                 bar_start: datetime | None = None) -> list[Fill]:
        """Feed a tick (high/low/open omitted) or a bar (ts = bar end, bar_start = bar open time).
        Marks positions and works open orders. An order placed partway through a bar is only
        checked against the bar's close, since its earlier high/low may predate the order."""
        hi = high if high is not None else last
        lo = low if low is not None else last
        pos = self.positions.get(symbol)
        if pos and (pos.mark_ts is None or ts >= pos.mark_ts):
            pos.mark, pos.mark_ts = last, ts
        if status not in TRADABLE_STATUSES:
            return []
        fills: list[Fill] = []
        order_rank = {OrderRole.STOP_LOSS: 0, OrderRole.EXIT: 1, OrderRole.ENTRY: 2, OrderRole.TAKE_PROFIT: 3}
        working = sorted((o for o in self.orders.values() if o.status == OrderStatus.OPEN and o.symbol == symbol
                          and o.created_at <= ts), key=lambda o: (order_rank[o.role], o.created_at))
        for o in working:
            if o.status != OrderStatus.OPEN:  # canceled by an OCO sibling during this loop
                continue
            if not self._session_allows(ts, o.extended_hours):
                continue
            if bar_start is not None and o.created_at > bar_start:
                m = self._match(o, last, last, None, last)
            else:
                m = self._match(o, hi, lo, open_, last)
            if m is not None:
                f = self._fill(o, m[0], m[1], ts, status.value)
                if f:
                    fills.append(f)
        return fills

    def _match(self, o: Order, hi: float, lo: float, bar_open: float | None, last: float) -> tuple[float, float] | None:
        """bar_open is None for ticks. A resting limit fills at its limit price; it only gets a
        better price when a bar *opens* beyond it (a gap). A stop that is jumped past fills at
        the worse price (the gap open, or the tick that crossed it)."""
        buy = o.side == Side.BUY
        op = bar_open if bar_open is not None else last
        if o.type == OrderType.MARKET:
            return self._slip(op, o.side), op
        if o.type in (OrderType.STOP, OrderType.STOP_LIMIT) and not o.triggered:
            hit = hi >= o.stop_price if buy else lo <= o.stop_price
            if not hit:
                return None
            if o.type == OrderType.STOP:
                base = max(o.stop_price, op) if buy else min(o.stop_price, op)
                return self._slip(base, o.side), o.stop_price
            o.triggered = True  # stop-limit becomes a limit; may fill on a later update
            self._touch(o)
            return None
        # limit (or triggered stop-limit): must trade through
        if buy and lo < o.limit_price:
            return (min(o.limit_price, bar_open) if bar_open is not None else o.limit_price), o.limit_price
        if not buy and hi > o.limit_price:
            return (max(o.limit_price, bar_open) if bar_open is not None else o.limit_price), o.limit_price
        return None

    def _fill(self, o: Order, price: float, ref_price: float, ts: datetime, basis: str) -> Fill | None:
        price = round(price, 4)
        signed = o.qty if o.side == Side.BUY else -o.qty
        pos = self.positions.get(o.symbol)
        realized = 0.0
        if pos is None or pos.qty == 0 or (pos.qty > 0) == (signed > 0):
            if pos is None:
                pos = self.positions[o.symbol] = Position(o.symbol, 0, 0.0, ts)
            new_qty = pos.qty + signed
            pos.avg_price = (pos.avg_price * abs(pos.qty) + price * o.qty) / abs(new_qty)
            pos.qty = new_qty
        else:
            closed = min(o.qty, abs(pos.qty))
            realized = (price - pos.avg_price) * closed * (1 if pos.qty > 0 else -1)
            pos.qty += signed
            pos.realized_pnl += realized
        if pos.mark is None:
            pos.mark, pos.mark_ts = price, ts

        commission = self._commission(o.qty)
        self.account.cash -= signed * price + commission
        self.account.commissions += commission
        self.account.realized_pnl += realized

        f = Fill(id=_new_id(), order_id=o.id, symbol=o.symbol, side=o.side, qty=o.qty, price=price, ref_price=round(ref_price, 4),
                 slippage_cost=round(max(0.0, (price - ref_price) if o.side == Side.BUY else (ref_price - price)) * o.qty, 2),
                 commission=round(commission, 2), realized_pnl=round(realized, 2), ts=ts, price_basis=basis, role=o.role)
        self.fills.append(f)
        self.new_fills.append(f)
        o.status, o.filled_at, o.fill_price, o.updated_at = OrderStatus.FILLED, ts, price, ts
        self._touch(o)
        self.events.append({"type": "paper_fill", "data": f.to_dict()})

        if pos.qty == 0:
            del self.positions[o.symbol]
            for other in list(self.orders.values()):
                if other.status == OrderStatus.OPEN and other.symbol == o.symbol and other.role != OrderRole.ENTRY:
                    self._set_status(other, OrderStatus.CANCELED, ts, "Position closed")
        if o.oco_group:
            for other in self.orders.values():
                if other.oco_group == o.oco_group and other.id != o.id and other.status == OrderStatus.OPEN:
                    self._set_status(other, OrderStatus.CANCELED, ts, "OCO: other side filled")
        if o.role == OrderRole.ENTRY and (o.bracket_stop or o.bracket_target):
            self._attach_bracket(o, ts)
        self.events.append({"type": "paper_account", "data": self.summary()})
        return f

    def _attach_bracket(self, entry: Order, ts: datetime) -> None:
        exit_side = Side.SELL if entry.side == Side.BUY else Side.BUY
        group = entry.id
        if entry.bracket_stop:
            o = Order(id=_new_id(), symbol=entry.symbol, side=exit_side, qty=entry.qty, type=OrderType.STOP,
                      role=OrderRole.STOP_LOSS, tif=TIF.GTC, created_at=ts, updated_at=ts, stop_price=entry.bracket_stop,
                      parent_id=entry.id, oco_group=group)
            self.orders[o.id] = o
            self._touch(o)
        if entry.bracket_target:
            o = Order(id=_new_id(), symbol=entry.symbol, side=exit_side, qty=entry.qty, type=OrderType.LIMIT,
                      role=OrderRole.TAKE_PROFIT, tif=TIF.GTC, created_at=ts, updated_at=ts, limit_price=entry.bracket_target,
                      parent_id=entry.id, oco_group=group)
            self.orders[o.id] = o
            self._touch(o)

    def _set_status(self, o: Order, status: OrderStatus, ts: datetime, reason: str) -> None:
        o.status, o.updated_at, o.reject_reason = status, ts, reason
        self._touch(o)

    def _touch(self, o: Order) -> None:
        self.dirty_orders.add(o.id)
        self.events.append({"type": "paper_order", "data": o.to_dict()})

    # ---------------- reset ----------------

    def reset(self, starting_cash: float | None = None, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        cash = starting_cash or self.cfg.starting_cash
        self.orders.clear()
        self.positions.clear()
        self.fills.clear()
        self.new_fills.clear()
        self.dirty_orders.clear()
        self.account = Account(starting_cash=cash, cash=cash, created_at=now)
        self.roll(now)
        self.events.append({"type": "paper_reset", "data": self.summary()})
