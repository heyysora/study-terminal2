"""Trading journal: records every signal and every paper trade, keeps your notes, and analyses
performance and mistakes.

- Signals are logged when they first appear and whenever their action or state changes, so the log
  shows each idea's life (developing -> confirmed -> invalidated...) without one row per cycle.
- Closed paper trades are snapshotted into their own table, so they survive a paper-account reset.
- The conditions at entry (signal, market, data status, trend, risk limit) are captured when you place
  the order. They're facts recorded at that moment, not reconstructed later.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone

from sqlalchemy import desc, select

from ..core.market_clock import ET
from ..db.models import JournalNoteRecord, JournalTradeRecord, SignalLogRecord
from ..db.session import Database
from ..paper.trades import round_trips
from .analysis import MISTAKES, build_trade, detect_mistakes, mistake_summary, performance

log = logging.getLogger(__name__)


def _compact_signal(s: dict) -> dict:
    keep = ("id", "symbol", "setup", "setup_name", "direction", "timeframe", "action", "state", "state_reason", "detected_at",
            "price", "entry_range", "trigger", "stop", "invalidation", "targets", "reward_risk", "position_size", "tradeable",
            "evidence_tier", "regime", "risks", "market")
    out = {k: s.get(k) for k in keep}
    c = s.get("confidence") or {}
    out["confidence"] = {
        "setup_quality": (c.get("setup_quality") or {}).get("score"),
        "historical": {k: (c.get("historical") or {}).get(k) for k in ("tier", "trades", "avg_r", "avg_r_ci95", "win_rate", "note")},
        "model_probability": c.get("model_probability"),
    }
    return out


class JournalService:
    def __init__(self, db: Database, paper, settings_store):
        self.db, self.paper, self.settings = db, paper, settings_store
        self._last_logged: dict[str, tuple] = {}
        self.signals_service = None   # set by main (avoids a construction cycle)
        self._load_last()

    def _load_last(self) -> None:
        with self.db.session() as s:
            for r in s.scalars(select(SignalLogRecord).order_by(desc(SignalLogRecord.id)).limit(2000)).all():
                self._last_logged.setdefault(r.signal_id, (r.action, r.state))

    # ---------------- signal log ----------------

    def log_signals(self, ev: dict) -> int:
        n = 0
        rows = []
        for s in ev.get("signals", []):
            k = (s["action"], s["state"])
            if self._last_logged.get(s["id"]) == k:
                continue
            self._last_logged[s["id"]] = k
            c = _compact_signal(s)
            c["data_label"] = ev.get("data_label")
            rows.append(SignalLogRecord(signal_id=s["id"], symbol=s["symbol"], setup=s["setup"], direction=s["direction"],
                                        timeframe=s["timeframe"], action=s["action"], state=s["state"],
                                        tradeable=int(bool(s.get("tradeable"))), evidence_tier=s.get("evidence_tier") or "none",
                                        data=json.dumps(c, default=str)))
            n += 1
        if rows:
            with self.db.session() as sess:
                sess.add_all(rows)
        return n

    def signals(self, symbol: str | None = None, setup: str | None = None, action: str | None = None,
                start: date | None = None, end: date | None = None, limit: int = 500) -> list[dict]:
        with self.db.session() as s:
            q = select(SignalLogRecord).order_by(desc(SignalLogRecord.id))
            if symbol:
                q = q.where(SignalLogRecord.symbol == symbol.upper())
            if setup:
                q = q.where(SignalLogRecord.setup == setup)
            if action:
                q = q.where(SignalLogRecord.action == action)
            if start:
                q = q.where(SignalLogRecord.ts >= datetime.combine(start, datetime.min.time(), tzinfo=ET).astimezone(timezone.utc))
            if end:
                q = q.where(SignalLogRecord.ts < datetime.combine(end, datetime.max.time(), tzinfo=ET).astimezone(timezone.utc))
            rows = s.scalars(q.limit(limit)).all()
            acted = self._acted_signal_ids()
            return [{"id": r.id, "ts": r.ts.isoformat(), "signal_id": r.signal_id, "symbol": r.symbol, "setup": r.setup,
                     "direction": r.direction, "timeframe": r.timeframe, "action": r.action, "state": r.state,
                     "tradeable": bool(r.tradeable), "evidence_tier": r.evidence_tier, "acted_on": r.signal_id in acted,
                     **{"detail": json.loads(r.data)}} for r in rows]

    def _acted_signal_ids(self) -> set[str]:
        ids = {o.signal_id for o in self.paper.engine.orders.values() if o.signal_id}
        with self.db.session() as s:
            for r in s.scalars(select(JournalTradeRecord)).all():
                sig = (json.loads(r.data).get("signal") or {})
                if sig.get("id"):
                    ids.add(sig["id"])
        return ids

    # ---------------- context capture at order time ----------------

    def capture_context(self, symbol: str, signal_id: str | None) -> dict:
        sv = self.signals_service
        ctx: dict = {"captured_at": datetime.now(timezone.utc).isoformat()}
        eng = self.paper.engine
        eq = eng.equity()
        ctx["equity"] = round(eq, 2)
        ctx["risk_pct"] = self.paper.risk.max_per_trade_pct
        ctx["max_risk_dollars"] = round(eq * self.paper.risk.max_per_trade_pct / 100, 2)
        try:
            ctx["data_label"] = self.paper.monitor.label(symbol).model_dump(mode="json")
        except Exception:  # noqa: BLE001 - context is best-effort, an order must never fail because of it
            ctx["data_label"] = None
        if sv is None:
            return ctx
        ctx["market"] = dict(sv.market) if sv.market else None
        ev = sv.latest.get(symbol)
        sig = None
        if ev:
            sig = next((s for s in ev.get("signals", []) if s["id"] == signal_id), None) if signal_id else None
            ctx["symbol_action"] = ev.get("action")
            try:
                from ..market_data.types import Timeframe
                cached = sv.analysis._cache.get((symbol, Timeframe(ev["timeframe"])))
                if cached:
                    row = cached[1].df.iloc[-1]
                    ext = row.get("ext_from_ema9_atr")
                    ctx["ext_from_ema9_atr"] = None if ext is None or ext != ext else round(float(ext), 2)
                    st, up, dn = row.get("structure"), row["ema9"] > row["ema21"] > row["ema50"], row["ema9"] < row["ema21"] < row["ema50"]
                    trend = 1 if (up or st == "uptrend") else -1 if (dn or st == "downtrend") else 0
                    ctx["trend"] = {1: "up", -1: "down", 0: "mixed"}[trend]
                    from ..signals.engine import regime
                    ctx["regime"] = regime(row) if "atr_pct_med" in row else None
            except Exception:  # noqa: BLE001
                log.debug("context capture: features unavailable for %s", symbol, exc_info=True)
        if sig:
            ctx["signal"] = _compact_signal(sig)
            ctx["regime"] = ctx.get("regime") or sig.get("regime")
        return ctx

    def trend_alignment(self, ctx: dict, direction: str) -> str | None:
        tr = ctx.get("trend")
        if not tr or tr == "mixed":
            return None
        return "with trend" if (tr == "up") == (direction == "long") else "against trend"

    # ---------------- trades ----------------

    def sync(self) -> int:
        """Snapshot newly closed round trips. Safe to call often."""
        eng = self.paper.engine
        rts = round_trips(eng.fills)
        closed = [rt for rt in rts if not rt.is_open]
        if not closed:
            return 0
        with self.db.session() as s:
            have = set(s.scalars(select(JournalTradeRecord.key)).all())
            n = 0
            for rt in closed:
                key = rt.fill_ids[0]
                if key in have:
                    continue
                t = build_trade(rt, eng.orders)
                t["context"]["trend_alignment"] = self.trend_alignment(t["context"], t["direction"])
                s.add(JournalTradeRecord(key=key, symbol=rt.symbol, opened_at=rt.opened_at, closed_at=rt.closed_at,
                                         data=json.dumps(t, default=str)))
                n += 1
        return n

    def _notes(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        with self.db.session() as s:
            for r in s.scalars(select(JournalNoteRecord).order_by(JournalNoteRecord.id)).all():
                d = out.setdefault(r.trade_key, {"notes": [], "tags": [], "followed_plan": None})
                if r.kind == "note":
                    d["notes"].append({"id": r.id, "ts": r.ts.isoformat(), "text": r.text})
                elif r.kind == "tags":
                    d["tags"] = json.loads(r.text or "[]")
                elif r.kind == "followed_plan":
                    d["followed_plan"] = None if r.text == "" else r.text == "yes"
        return out

    def all_trades(self) -> list[dict]:
        self.sync()
        with self.db.session() as s:
            trades = [json.loads(r.data) for r in s.scalars(select(JournalTradeRecord)).all()]
        eng = self.paper.engine
        for rt in round_trips(eng.fills):
            if rt.is_open:
                pos = eng.positions.get(rt.symbol)
                t = build_trade(rt, eng.orders, mark=pos.mark if pos else None)
                t["context"]["trend_alignment"] = self.trend_alignment(t["context"], t["direction"])
                trades.append(t)
        notes = self._notes()
        for t in trades:
            n = notes.get(t["key"], {})
            t["notes"], t["tags"] = n.get("notes", []), n.get("tags", [])
            t["followed_plan_user"] = n.get("followed_plan")
            t["followed_plan"] = t["followed_plan_user"] if t["followed_plan_user"] is not None else t["followed_plan_auto"]
        detect_mistakes(trades, int(self.settings.get("journal.max_trades_per_day", 3)))
        return trades

    @staticmethod
    def filter(trades: list[dict], start: date | None = None, end: date | None = None, symbol: str | None = None,
               strategy: str | None = None, direction: str | None = None, mistake: str | None = None,
               followed: bool | None = None, status: str | None = None) -> list[dict]:
        def day(t):
            return datetime.fromisoformat(t["opened_at"]).astimezone(ET).date()
        out = []
        for t in trades:
            if start and day(t) < start or end and day(t) > end:
                continue
            if symbol and t["symbol"] != symbol.upper():
                continue
            if strategy and t["strategy"] != strategy:
                continue
            if direction and t["direction"] != direction:
                continue
            if mistake and not any(m["code"] == mistake for m in t.get("mistakes", [])):
                continue
            if followed is not None and bool(t["followed_plan"]) != followed:
                continue
            if status == "open" and not t["open"] or status == "closed" and t["open"]:
                continue
            out.append(t)
        return out

    def trades(self, **f) -> list[dict]:
        ts = self.filter(self.all_trades(), **f)
        ts.sort(key=lambda t: t["opened_at"], reverse=True)
        return ts

    def trade(self, key: str) -> dict | None:
        return next((t for t in self.all_trades() if t["key"] == key), None)

    def performance(self, **f) -> dict:
        ts = self.filter(self.all_trades(), **f)
        perf = performance(ts)
        perf["mistakes"] = mistake_summary(ts)
        perf["mistake_labels"] = MISTAKES
        return perf

    # ---------------- your input ----------------

    def _exists(self, key: str) -> bool:
        return self.trade(key) is not None

    def add_note(self, key: str, text: str) -> dict:
        text = text.strip()
        if not text:
            raise ValueError("Note is empty")
        if not self._exists(key):
            raise KeyError(key)
        with self.db.session() as s:
            r = JournalNoteRecord(trade_key=key, kind="note", text=text[:5000])
            s.add(r)
            s.flush()
            return {"id": r.id, "ts": r.ts.isoformat(), "text": r.text}

    def delete_note(self, note_id: int) -> None:
        with self.db.session() as s:
            r = s.get(JournalNoteRecord, note_id)
            if r is None or r.kind != "note":
                raise KeyError(note_id)
            s.delete(r)

    def set_meta(self, key: str, tags: list[str] | None = None, followed_plan: bool | None | str = "unchanged") -> None:
        if not self._exists(key):
            raise KeyError(key)
        with self.db.session() as s:
            if tags is not None:
                clean = sorted({t.strip()[:32] for t in tags if t.strip()})[:20]
                s.add(JournalNoteRecord(trade_key=key, kind="tags", text=json.dumps(clean)))
            if followed_plan != "unchanged":
                s.add(JournalNoteRecord(trade_key=key, kind="followed_plan",
                                        text="" if followed_plan is None else ("yes" if followed_plan else "no")))
