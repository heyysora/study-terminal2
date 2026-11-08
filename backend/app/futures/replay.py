"""Historical replay: a past session bar by bar, with signals computed only from bars already shown.

* Separate simulated account; replay fills are stored under account "replay" and never mix with practice or sandbox trades.
* Source bars: 1-minute (last ~7 days on Yahoo) or 5-minute (last ~59 days). Signals always use completed 5-minute bars, so the
  forming 5-minute bar is dropped until it closes (no look-ahead).
* Optional automation in replay: the same decision pipeline, acting on APPROVED decisions (and, if you allow it, on experimental
  strategies that fail only validation), so you can practise and test automated rules on past sessions.
* The session survives restarts (bars, position and orders are saved).
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from ..market_data.types import Timeframe
from . import contracts as fc
from . import features as ff
from . import signals as fsig
from .feed import validate_bars
from .journal import journal_report
from .paper import FuturesPaperConfig, FuturesPaperEngine
from .risk import RiskEngine

REPLAY_ID = 2


def _ser(b: dict) -> dict:
    return {**b, "ts": b["ts"].isoformat()}


def _de(b: dict) -> dict:
    return {**b, "ts": datetime.fromisoformat(b["ts"])}


class Replayer:
    def __init__(self, svc, now=None):
        self.svc = svc
        self.rp: dict | None = None
        self._now = now or (lambda: datetime.now(timezone.utc))

    # ---------------- persistence ----------------

    def save(self) -> None:
        if not self.rp:
            return
        rp = self.rp
        self.svc._persist_fills(rp["engine"], "replay")
        self.svc._save(REPLAY_ID, {**{k: v for k, v in rp.items() if k not in ("engine", "bars", "end_ts")},
                                   "bars": [_ser(b) for b in rp["bars"]], "end_ts": rp["end_ts"].isoformat(),
                                   "engine": rp["engine"].to_state()})

    def restore(self, st: dict | None) -> None:
        if not st or "bars" not in st:
            return
        try:
            eng = FuturesPaperEngine(self.svc.engine.rules, self.svc.engine.personal,
                                     FuturesPaperConfig(**self.svc.engine.cfg.to_dict()), self.svc.fees_default)
            eng.load_state(st["engine"])
            self.rp = {**{k: v for k, v in st.items() if k not in ("engine", "bars", "end_ts")}, "engine": eng,
                       "bars": [_de(b) for b in st["bars"]], "end_ts": datetime.fromisoformat(st["end_ts"])}
        except Exception:  # noqa: BLE001
            self.rp = None

    # ---------------- control ----------------

    async def start(self, sym: str, trade_date: str, source_tf: str = "auto", auto: bool = False, auto_experimental: bool = False) -> dict:
        svc = self.svc
        contract, _ = svc.resolve(sym, date.fromisoformat(trade_date))
        clk = svc.clock(contract.root)
        w = clk.window(date.fromisoformat(trade_date))
        if not w:
            raise ValueError(f"{contract.root} didn't trade on {trade_date} (weekend or holiday).")
        age = (self._now() - w.open).days
        if age > 58:
            raise ValueError("Yahoo only keeps about 59 days of intraday futures bars; pick a more recent date.")
        if source_tf == "1Min" and age > 6:
            raise ValueError("1-minute bars are only available for about the last 7 days; use 5-minute bars for this date.")
        tf = Timeframe.M1 if (source_tf == "1Min" or (source_tf == "auto" and age <= 6)) else Timeframe.M5
        hist_start = (clk.prev_window(w.trade_date) or w).open - timedelta(days=4)
        raw, _ = await svc.data.yahoo.get_bars(contract.yahoo_symbol, tf, hist_start, w.close + timedelta(minutes=1))
        bars = [{"ts": b.ts, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in raw]
        bars, rep = validate_bars(bars, tf.seconds, contract.spec, clk, w.close + timedelta(minutes=1))
        if not any(w.contains(b["ts"]) for b in bars):
            raise ValueError(f"No {contract.code} bars for {trade_date} from Yahoo.")
        start_i = next(i for i, b in enumerate(bars) if w.contains(b["ts"]))
        eng = FuturesPaperEngine(svc.engine.rules, svc.engine.personal, FuturesPaperConfig(**svc.engine.cfg.to_dict()), svc.fees_default)
        self.rp = {"contract": contract.code, "root": contract.root, "trade_date": trade_date, "bars": bars, "i": start_i,
                   "start_i": start_i, "tf": tf.value, "engine": eng, "end_ts": w.close, "auto": bool(auto),
                   "auto_experimental": bool(auto_experimental), "started_at": datetime.now(timezone.utc).isoformat(),
                   "validation": rep["summary"], "auto_log": []}
        out = self.step(0)
        return out

    def _need(self) -> dict:
        if not self.rp:
            raise ValueError("No replay running. Load a session first.")
        return self.rp

    def step(self, n: int = 1) -> dict:
        rp = self._need()
        clk = self.svc.clock(rp["root"])
        eng: FuturesPaperEngine = rp["engine"]
        for _ in range(max(0, n)):
            if rp["i"] >= len(rp["bars"]) - 1 or rp["bars"][rp["i"] + 1]["ts"] >= rp["end_ts"]:
                break
            rp["i"] += 1
            b = rp["bars"][rp["i"]]
            eng.on_bar(rp["contract"], b["ts"], b["open"], b["high"], b["low"], b["close"], b["volume"], "replay", clk)
            if rp["auto"]:
                self._auto(clk)
        st = self.state(clk)
        self.save()
        return st

    def _frames(self, clk):
        rp = self.rp
        seen = rp["bars"][:rp["i"] + 1]
        minutes = 1 if rp["tf"] == "1Min" else 5
        from .service import resample
        five = resample(seen, 5) if minutes == 1 else list(seen)
        if minutes == 1 and five and five[-1]["ts"] + timedelta(minutes=5) > seen[-1]["ts"] + timedelta(minutes=1):
            five = five[:-1]                                   # forming 5-minute bar: not used until it closes
        spec = fc.get(rp["root"])
        F = ff.build(ff.bars_to_frame(five, clk), spec, clk)
        fifteen = resample(five, 15)
        if fifteen and five and fifteen[-1]["ts"] + timedelta(minutes=15) > five[-1]["ts"] + timedelta(minutes=5):
            fifteen = fifteen[:-1]
        F15 = ff.build(ff.bars_to_frame(fifteen, clk), spec, clk, bar_minutes=15) if fifteen else None
        now = seen[-1]["ts"] + timedelta(minutes=minutes)
        return seen, five, F, F15, now

    def _signal(self, clk):
        rp = self.rp
        seen, five, F, F15, now = self._frames(clk)
        eng: FuturesPaperEngine = rp["engine"]
        spec = fc.get(rp["root"])
        risk = RiskEngine(eng.rules, eng.personal)
        snap = eng.snapshot(now, clk)
        pos = eng.positions.get(rp["contract"])
        stop = next((o.stop_price for o in eng.orders.values() if o.active and o.role == "stop_loss"), None)
        sig = fsig.evaluate(F, spec, rp["contract"], {"status": "replay", "reason": "Replaying a past session", "provider": "yahoo (replay)",
                                                       "age_seconds": 0, "validation": {"ok": True}},
                            self.svc.evidence.get(rp["root"], {}).get("by_setup", {}), now=now,
                            position=asdict(pos) if pos and pos.qty else None, position_stop=stop, risk_engine=risk, snapshot=snap,
                            round_turn=eng.round_turn(rp["root"]), slippage_ticks=eng.cfg.slippage_ticks_market,
                            flat_by_min_from_rth=self.svc.flat_minutes(clk), F15=F15, current_price=seen[-1]["close"],
                            validated=self.svc.validated_strategies(rp["root"]), mode="replay")
        return sig, seen, five, F, now

    def _auto(self, clk) -> None:
        from .automation import AutomationEngine
        rp = self.rp
        sig, seen, five, F, now = self._signal(clk)
        dec = sig.get("decision") or {}
        ok = dec.get("outcome") == "APPROVED" or (rp["auto_experimental"] and AutomationEngine._sandbox_eligible(dec))
        if not ok or not dec.get("plan"):
            return
        eng: FuturesPaperEngine = rp["engine"]
        if any(o.signal_id == dec["id"] for o in eng.orders.values()):
            return
        if (eng.positions.get(rp["contract"]) and eng.positions[rp["contract"]].qty) or any(o.active and o.role == "entry" for o in eng.orders.values()):
            return
        plan = dec["plan"]
        d = 1 if plan["direction"] == "long" else -1
        qty = max(1, int(plan.get("suggested_contracts") or 1))
        o, pv = eng.submit(rp["contract"], d, qty, "limit", plan["entry"], None, {"stop": plan["stop"], "targets": [{"price": plan["target"], "qty": qty}]},
                           plan["entry"], now, clk, "replay", signal_id=dec["id"], origin="replay-auto")
        rp["auto_log"] = (rp["auto_log"] + [{"at": now.isoformat(), "decision": dec["id"], "setup": plan["setup"], "direction": plan["direction"],
                                             "result": "order " + o.id if o else "refused: " + "; ".join(pv.get("problems", [])[:2]),
                                             "experimental": dec.get("outcome") != "APPROVED"}])[-200:]

    def state(self, clk=None) -> dict:
        rp = self._need()
        clk = clk or self.svc.clock(rp["root"])
        sig, seen, five, F, now = self._signal(clk)
        spec = fc.get(rp["root"])
        eng: FuturesPaperEngine = rp["engine"]
        total = sum(1 for b in rp["bars"] if b["ts"] < rp["end_ts"]) - rp["start_i"]
        return {"contract": rp["contract"], "trade_date": rp["trade_date"], "bar_time": seen[-1]["ts"].isoformat(), "timeframe": rp["tf"],
                "progress": {"i": rp["i"] - rp["start_i"], "of": total, "finished": rp["i"] - rp["start_i"] >= total - 1},
                "last": seen[-1]["close"], "levels": fsig.levels_snapshot(F, spec) if len(F) else {}, "signal": sig,
                "account": eng.summary(now, clk), "auto": rp["auto"], "auto_experimental": rp["auto_experimental"], "auto_log": rp["auto_log"][-20:][::-1],
                "validation": rp.get("validation"),
                "chart": [{"t": int(b["ts"].timestamp()), "o": b["open"], "h": b["high"], "l": b["low"], "c": b["close"], "v": b["volume"]}
                          for b in five[-300:]],
                "note": "Replay: a past session bar by bar. Signals use only bars already shown; fills use the replayed bars. Separate account."}

    def order(self, body: dict) -> dict:
        rp = self._need()
        if not body.get("confirm"):
            raise PermissionError("Confirm the replay order first.")
        eng: FuturesPaperEngine = rp["engine"]
        b = rp["bars"][rp["i"]]
        now = b["ts"] + timedelta(minutes=1 if rp["tf"] == "1Min" else 5)
        o, pv = eng.submit(rp["contract"], body["side"], int(body["qty"]), body.get("type", "market"), body.get("limit_price"),
                           body.get("stop_price"), body.get("bracket"), b["close"], now, self.svc.clock(rp["root"]), "replay", origin="replay")
        self.save()
        return {"order": asdict(o) if o else None, "preview": pv}

    def flatten(self) -> dict:
        rp = self._need()
        b = rp["bars"][rp["i"]]
        fills = rp["engine"].flatten(rp["contract"], b["ts"], "Flattened by you (replay)", price=b["close"], ts_basis="replay bar close")
        self.save()
        return {"fills": [asdict(f) for f in fills]}

    def review(self) -> dict:
        """Every replay trade so far (all sessions), with automated and manual replay trades measured separately."""
        fills = self.svc.all_fills("replay")
        orders = dict(self.rp["engine"].orders) if self.rp else {}
        return journal_report(fills, orders, [])
