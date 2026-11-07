"""Connects the paper simulator to live monitoring, persistence and the UI push channel."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from ..config import Settings
from ..core.events import Broadcaster
from ..db.session import Database
from ..market_data.service import MarketMonitor
from ..market_data.types import Bar, LabeledValue, Tick
from .engine import OrderRequest, OrderStatus, PaperConfig, PaperEngine, PriceRef, RiskConfig
from .store import PaperStore

log = logging.getLogger(__name__)


class PaperService:
    def __init__(self, settings: Settings, db: Database, monitor: MarketMonitor, broadcaster: Broadcaster):
        s = settings
        self.cfg = PaperConfig(starting_cash=s.paper_starting_cash, margin_multiplier=s.paper_margin_multiplier,
                               allow_short=s.paper_allow_short, commission_per_share=s.paper_commission_per_share,
                               commission_per_order=s.paper_commission_per_order, slippage_bps=s.paper_slippage_bps,
                               slippage_min=s.paper_slippage_min,
                               borrow_fee_annual_pct=s.paper_short_borrow_fee_annual_pct)
        self.risk = RiskConfig(max_per_trade_pct=s.risk_max_per_trade_pct, max_daily_loss_pct=s.risk_max_daily_loss_pct,
                               max_open_positions=s.risk_max_open_positions, min_reward_risk=s.risk_min_reward_risk,
                               require_stop=s.risk_require_stop)
        self.monitor, self.broadcaster = monitor, broadcaster
        self.store = PaperStore(db)
        self.engine = PaperEngine(self.cfg, self.risk, monitor.clock)
        if self.store.load_into(self.engine):
            log.info("paper account restored: equity $%.2f, %d positions", self.engine.equity(), len(self.engine.positions))
        self.engine.events.clear()
        self._save()
        monitor.extra_symbols = self.symbols
        monitor.tick_listeners.append(self._on_tick)
        monitor.bar_listeners.append(self._on_bar)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._roller())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        self._save()

    def symbols(self) -> list[str]:
        """Symbols the monitor must keep watching: open positions, then symbols with working orders."""
        syms = list(self.engine.positions)
        syms += [o.symbol for o in self.engine.orders.values() if o.status == OrderStatus.OPEN]
        return list(dict.fromkeys(syms))

    def price_ref(self, symbol: str) -> PriceRef | None:
        t = self.monitor.tracker.latest(symbol)
        if t is None:
            return None
        return PriceRef(price=t.price, ts=t.ts, status=self.monitor.label(symbol).status, bid=t.bid, ask=t.ask)

    # ---------------- market updates ----------------

    def _on_tick(self, tick: Tick, label: LabeledValue) -> None:
        self.engine.on_price(tick.symbol, tick.price, tick.ts, label.status)
        self._flush()

    def _on_bar(self, bar: Bar, label: LabeledValue) -> None:
        end = min(bar.ts + timedelta(seconds=60), datetime.now(timezone.utc))
        self.engine.on_price(bar.symbol, bar.close, end, label.status, high=bar.high, low=bar.low, open_=bar.open,
                             bar_start=bar.ts)
        self._flush()

    async def _roller(self) -> None:
        while True:
            await asyncio.sleep(15)
            self.engine.roll(datetime.now(timezone.utc))
            self._flush()

    # ---------------- user actions (each one is an explicit request from you) ----------------

    async def _ensure_price(self, symbol: str) -> PriceRef | None:
        ref = self.price_ref(symbol)
        if ref is None:
            await self.monitor.quote(symbol)
            ref = self.price_ref(symbol)
        return ref

    async def preview(self, req: OrderRequest) -> dict:
        ref = await self._ensure_price(req.symbol)
        return {"preview": self.engine.preview(req, ref).to_dict(), "price": self._ref_dict(ref)}

    async def submit(self, req: OrderRequest) -> dict:
        ref = await self._ensure_price(req.symbol)
        order, pv = self.engine.submit(req, ref)
        self._flush()
        await self.monitor.refresh_symbols()
        return {"order": order.to_dict(), "preview": pv.to_dict(), "price": self._ref_dict(ref)}

    async def cancel(self, order_id: str) -> dict:
        o = self.engine.cancel(order_id)
        self._flush()
        await self.monitor.refresh_symbols()
        return o.to_dict()

    async def close_position(self, symbol: str) -> dict:
        ref = await self._ensure_price(symbol)
        order, pv = self.engine.close_position(symbol, ref)
        self._flush()
        return {"order": order.to_dict(), "preview": pv.to_dict(), "price": self._ref_dict(ref)}

    async def reset(self, starting_cash: float | None) -> dict:
        self.engine.reset(starting_cash)
        self.store.wipe()
        self._flush()
        await self.monitor.refresh_symbols()
        return self.engine.summary()

    # ---------------- views ----------------

    def positions(self) -> list[dict]:
        out = []
        for p in self.engine.positions.values():
            kids = [o for o in self.engine.orders.values() if o.status == OrderStatus.OPEN and o.symbol == p.symbol]
            lab = self.monitor.label(p.symbol)
            out.append({"symbol": p.symbol, "side": p.side, "qty": p.qty, "avg_price": round(p.avg_price, 4),
                        "mark": p.mark, "mark_ts": p.mark_ts.isoformat() if p.mark_ts else None,
                        "mark_label": lab.model_dump(mode="json"), "market_value": round(p.market_value(), 2),
                        "unrealized_pnl": round(p.unrealized(), 2), "realized_pnl": round(p.realized_pnl, 2),
                        "opened_at": p.opened_at.isoformat(),
                        "stop_loss": next((o.stop_price for o in kids if o.role.value == "stop_loss"), None),
                        "take_profit": next((o.limit_price for o in kids if o.role.value == "take_profit"), None)})
        return out

    @staticmethod
    def _ref_dict(ref: PriceRef | None) -> dict | None:
        if ref is None:
            return None
        return {"price": ref.price, "ts": ref.ts.isoformat(), "status": ref.status.value, "bid": ref.bid, "ask": ref.ask}

    def _save(self) -> None:
        try:
            self.store.save(self.engine)
        except Exception:
            log.exception("failed to persist paper account")

    def _flush(self) -> None:
        if not (self.engine.events or self.engine.dirty_orders or self.engine.new_fills):
            return
        self._save()
        events, self.engine.events = self.engine.events, []
        for ev in events:
            self.broadcaster.publish(ev)
