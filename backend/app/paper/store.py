"""Persists the paper simulator to SQLite so positions/orders survive restarts and crashes."""
from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import delete, select

from ..db.models import PaperFillRecord, PaperOrderRecord, PaperStateRecord
from ..db.session import Database
from .engine import TIF, Account, Fill, Order, OrderRole, OrderStatus, OrderType, PaperEngine, Position, Side


def _dt(v):
    return datetime.fromisoformat(v) if v else None


class PaperStore:
    def __init__(self, db: Database):
        self.db = db

    def save(self, eng: PaperEngine) -> None:
        a = eng.account
        state = {
            "account": {"starting_cash": a.starting_cash, "cash": a.cash, "created_at": a.created_at.isoformat(),
                        "realized_pnl": a.realized_pnl, "commissions": a.commissions, "borrow_fees": a.borrow_fees,
                        "day": a.day.isoformat() if a.day else None, "day_start_equity": a.day_start_equity},
            "positions": [{"symbol": p.symbol, "qty": p.qty, "avg_price": p.avg_price, "opened_at": p.opened_at.isoformat(),
                           "mark": p.mark, "mark_ts": p.mark_ts.isoformat() if p.mark_ts else None,
                           "realized_pnl": p.realized_pnl} for p in eng.positions.values()],
        }
        dirty = [eng.orders[i] for i in eng.dirty_orders if i in eng.orders]
        fills, eng.new_fills = eng.new_fills, []
        eng.dirty_orders.clear()
        with self.db.session() as s:
            row = s.get(PaperStateRecord, 1)
            if row is None:
                s.add(PaperStateRecord(id=1, data=json.dumps(state)))
            else:
                row.data = json.dumps(state)
            for o in dirty:
                rec = s.get(PaperOrderRecord, o.id)
                d = json.dumps(o.to_dict())
                if rec is None:
                    s.add(PaperOrderRecord(id=o.id, symbol=o.symbol, status=o.status.value, created_at=o.created_at, data=d))
                else:
                    rec.status, rec.data = o.status.value, d
            for f in fills:
                s.add(PaperFillRecord(id=f.id, order_id=f.order_id, symbol=f.symbol, ts=f.ts, data=json.dumps(f.to_dict())))

    def wipe(self) -> None:
        with self.db.session() as s:
            s.execute(delete(PaperFillRecord))
            s.execute(delete(PaperOrderRecord))
            s.execute(delete(PaperStateRecord))

    def load_into(self, eng: PaperEngine) -> bool:
        with self.db.session() as s:
            row = s.get(PaperStateRecord, 1)
            if row is None:
                return False
            state = json.loads(row.data)
            orders = [json.loads(r.data) for r in s.scalars(select(PaperOrderRecord).order_by(PaperOrderRecord.created_at)).all()]
            fills = [json.loads(r.data) for r in s.scalars(select(PaperFillRecord).order_by(PaperFillRecord.ts)).all()]
        a = state["account"]
        eng.account = Account(starting_cash=a["starting_cash"], cash=a["cash"], created_at=_dt(a["created_at"]),
                              realized_pnl=a["realized_pnl"], commissions=a["commissions"], borrow_fees=a["borrow_fees"],
                              day=date.fromisoformat(a["day"]) if a["day"] else None, day_start_equity=a["day_start_equity"])
        eng.positions = {p["symbol"]: Position(symbol=p["symbol"], qty=p["qty"], avg_price=p["avg_price"],
                                               opened_at=_dt(p["opened_at"]), mark=p["mark"], mark_ts=_dt(p["mark_ts"]),
                                               realized_pnl=p["realized_pnl"]) for p in state["positions"]}
        eng.orders = {}
        for d in orders:
            o = Order(id=d["id"], symbol=d["symbol"], side=Side(d["side"]), qty=d["qty"], type=OrderType(d["type"]),
                      role=OrderRole(d["role"]), tif=TIF(d["tif"]), created_at=_dt(d["created_at"]),
                      limit_price=d["limit_price"], stop_price=d["stop_price"], extended_hours=d["extended_hours"],
                      status=OrderStatus(d["status"]), updated_at=_dt(d["updated_at"]), expires_at=_dt(d["expires_at"]),
                      parent_id=d["parent_id"], oco_group=d["oco_group"], bracket_stop=d["bracket_stop"],
                      bracket_target=d["bracket_target"], triggered=d["triggered"], filled_at=_dt(d["filled_at"]),
                      fill_price=d["fill_price"], reject_reason=d["reject_reason"], note=d["note"])
            eng.orders[o.id] = o
        eng.fills = [Fill(id=d["id"], order_id=d["order_id"], symbol=d["symbol"], side=Side(d["side"]), qty=d["qty"],
                          price=d["price"], ref_price=d["ref_price"], slippage_cost=d["slippage_cost"],
                          commission=d["commission"], realized_pnl=d["realized_pnl"], ts=_dt(d["ts"]),
                          price_basis=d["price_basis"], role=OrderRole(d["role"])) for d in fills]
        eng.dirty_orders.clear()
        eng.new_fills = []
        return True
