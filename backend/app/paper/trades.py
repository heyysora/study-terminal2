"""Groups paper fills into round-trip trades (flat -> position -> flat).

A "trade" is everything between a position opening and returning to zero, including scale-ins
and partial exits. Used by the risk checks (consecutive losing trades) and by the journal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RoundTrip:
    symbol: str
    direction: str                 # long | short
    opened_at: datetime
    closed_at: datetime | None = None
    max_qty: int = 0
    entry_qty: int = 0
    entry_value: float = 0.0       # sum(price*qty) of opening fills
    exit_qty: int = 0
    exit_value: float = 0.0
    gross_pnl: float = 0.0
    commissions: float = 0.0
    slippage: float = 0.0
    fill_ids: list[str] = field(default_factory=list)
    entry_order_ids: list[str] = field(default_factory=list)
    exit_roles: list[str] = field(default_factory=list)
    first_entry_order: str | None = None

    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    @property
    def avg_entry(self) -> float | None:
        return self.entry_value / self.entry_qty if self.entry_qty else None

    @property
    def avg_exit(self) -> float | None:
        return self.exit_value / self.exit_qty if self.exit_qty else None

    @property
    def net_pnl(self) -> float:
        return self.gross_pnl - self.commissions

    def to_dict(self) -> dict:
        return {"symbol": self.symbol, "direction": self.direction, "opened_at": self.opened_at.isoformat(),
                "closed_at": self.closed_at.isoformat() if self.closed_at else None, "open": self.is_open,
                "max_qty": self.max_qty, "entry_qty": self.entry_qty, "exit_qty": self.exit_qty,
                "avg_entry": round(self.avg_entry, 4) if self.avg_entry else None,
                "avg_exit": round(self.avg_exit, 4) if self.avg_exit else None,
                "gross_pnl": round(self.gross_pnl, 2), "commissions": round(self.commissions, 2),
                "slippage": round(self.slippage, 2), "net_pnl": round(self.net_pnl, 2),
                "fill_ids": self.fill_ids, "entry_order_ids": self.entry_order_ids, "exit_roles": self.exit_roles,
                "first_entry_order": self.first_entry_order}


def _get(f, k):
    v = f[k] if isinstance(f, dict) else getattr(f, k)
    return getattr(v, "value", v)


def round_trips(fills) -> list[RoundTrip]:
    """fills: Fill objects or dicts with symbol, side, qty, price, commission, realized_pnl, ts, order_id, role, id.
    Must be in time order. Returns trades in the order they were opened (open ones last per symbol)."""
    pos: dict[str, int] = {}
    cur: dict[str, RoundTrip] = {}
    out: list[RoundTrip] = []
    for f in fills:
        sym, side, qty, price = _get(f, "symbol"), _get(f, "side"), int(_get(f, "qty")), float(_get(f, "price"))
        ts = _get(f, "ts")
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        signed = qty if side == "buy" else -qty
        q0 = pos.get(sym, 0)
        remaining = signed
        # closing part
        if q0 != 0 and (q0 > 0) != (signed > 0):
            closing = min(abs(signed), abs(q0))
            t = cur[sym]
            frac = closing / abs(signed)
            t.exit_qty += closing
            t.exit_value += price * closing
            t.gross_pnl += float(_get(f, "realized_pnl"))
            t.commissions += float(_get(f, "commission")) * frac
            t.slippage += float(_get(f, "slippage_cost") if _has(f, "slippage_cost") else 0.0) * frac
            t.fill_ids.append(_get(f, "id"))
            t.exit_roles.append(_get(f, "role"))
            q0 += closing if signed > 0 else -closing
            remaining = signed + (closing if signed < 0 else -closing)
            if q0 == 0:
                t.closed_at = ts
                out.append(t)
                del cur[sym]
            frac_open = 1 - frac
        else:
            frac_open = 1.0
        # opening part
        if remaining != 0:
            t = cur.get(sym)
            if t is None:
                t = cur[sym] = RoundTrip(symbol=sym, direction="long" if remaining > 0 else "short", opened_at=ts,
                                         first_entry_order=_get(f, "order_id"))
            n = abs(remaining)
            t.entry_qty += n
            t.entry_value += price * n
            t.commissions += float(_get(f, "commission")) * frac_open
            t.slippage += float(_get(f, "slippage_cost") if _has(f, "slippage_cost") else 0.0) * frac_open
            if _get(f, "id") not in t.fill_ids:
                t.fill_ids.append(_get(f, "id"))
            t.entry_order_ids.append(_get(f, "order_id"))
            q0 += remaining
            t.max_qty = max(t.max_qty, abs(q0))
        pos[sym] = q0
    out.sort(key=lambda t: t.closed_at)
    return out + sorted(cur.values(), key=lambda t: t.opened_at)


def _has(f, k) -> bool:
    return (k in f) if isinstance(f, dict) else hasattr(f, k)
