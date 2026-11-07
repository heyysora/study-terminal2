"""Runs backtests in a worker thread, stores results, and maintains setup calibration."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import desc, select

from ..analysis.features import build
from ..core.market_clock import MarketClock
from ..db.models import BacktestRunRecord, SetupStatRecord
from ..db.session import Database
from ..market_data.providers.base import MarketDataProvider, ProviderError
from ..market_data.types import Timeframe
from ..signals.setups import SetupParams
from .engine import BacktestConfig, breakdown, metrics, run
from .walkforward import combine_equity, optimize, walk_forward

log = logging.getLogger(__name__)
MIN_CALIBRATION_TRADES = 20


class BacktestService:
    def __init__(self, db: Database, provider: MarketDataProvider, clock: MarketClock):
        self.db, self.provider, self.clock = db, provider, clock
        self.running: dict | None = None
        self._calibration: dict = {}
        self.reload_calibration()

    async def _frames(self, symbols: list[str], tf: Timeframe, days: int) -> tuple[dict, list[str]]:
        frames, notes = {}, []
        for s in symbols:
            try:
                bars, n = await self.provider.get_bars(s, tf, datetime.now(timezone.utc) - timedelta(days=days))
                frames[s] = build(bars, tf)
                notes += [f"{s}: {x}" for x in n[:1]]
            except ProviderError as e:
                notes.append(f"{s}: skipped ({e})")
        return frames, notes

    async def execute(self, req: dict) -> dict:
        if self.running:
            raise RuntimeError("A backtest is already running")
        self.running = {"started": datetime.now(timezone.utc).isoformat(), "request": req}
        try:
            tf = Timeframe(req.get("timeframe", "5Min"))
            symbols = [s.upper() for s in req["symbols"]][:20]
            frames, notes = await self._frames(symbols, tf, int(req.get("days", 58)))
            if not frames:
                raise ValueError("No data for any symbol")
            p = SetupParams(**{k: v for k, v in (req.get("params") or {}).items() if k in SetupParams.__dataclass_fields__})
            cfg = BacktestConfig(setups=req.get("setups") or None, params=p,
                                 starting_cash=float(req.get("starting_cash", 25_000)), risk_pct=float(req.get("risk_pct", 0.5)),
                                 slippage_bps=float(req.get("slippage_bps", 1.0)), slippage_min=float(req.get("slippage_min", 0.01)),
                                 commission_per_share=float(req.get("commission_per_share", 0)),
                                 allow_short=bool(req.get("allow_short", True)), flatten_eod=tf != Timeframe.D1)
            kind = req.get("mode", "backtest")
            result = await asyncio.to_thread(self._run_sync, kind, frames, cfg, req)
            result["notes"] = notes + [
                "Survivorship bias: symbols you pick today exclude companies that were delisted, which flatters results.",
                "Past results do not predict future results. A profitable backtest is not a guarantee.",
            ]
            result["config"] = {**cfg.to_dict(), "symbols": symbols, "timeframe": tf.value, "days": req.get("days", 58), "mode": kind}
            rid = self._store(kind, result)
            result["id"] = rid
            if kind == "walk_forward":
                self._update_calibration(result["trades"], tf.value)
            return result
        finally:
            self.running = None

    def _run_sync(self, kind: str, frames: dict, cfg: BacktestConfig, req: dict) -> dict:
        if kind == "walk_forward":
            wf = walk_forward(frames, cfg, self.clock, req.get("grid"), int(req.get("train_sessions", 20)), int(req.get("test_sessions", 5)))
            trades = wf["oos_trades"]
            return {"metrics": wf["oos_metrics"], "equity": wf["oos_equity"], "trades": trades, "folds": wf["folds"],
                    "by_setup": breakdown(trades, "setup"), "by_regime": breakdown(trades, "regime"),
                    "by_symbol": breakdown(trades, "symbol"), "out_of_sample": True, "explanation": wf["note"]}
        if kind == "optimize":
            res = optimize(frames, cfg, self.clock, req.get("grid"))
            return {"results": [{"params": r["params"], "metrics": r["metrics"]} for r in res], "trades": [], "equity": [],
                    "warning": "These are in-sample results. The top row is partly best by luck - confirm with walk-forward."}
        # plain backtest with a chronological in-sample / out-of-sample split
        split = float(req.get("oos_fraction", 0.3))
        trades, curves = [], []
        for sym, ff in frames.items():
            r = run(sym, ff, cfg, self.clock)
            trades += r["trades"]
            curves.append(pd.Series([e for _, e in r["equity"]], index=pd.to_datetime([t for t, _ in r["equity"]], utc=True)))
        eq = combine_equity(curves, cfg.starting_cash)
        trades.sort(key=lambda t: t["entry_ts"])
        cut_ts = eq[int(len(eq) * (1 - split))][0] if eq and split > 0 else None
        ins = [t for t in trades if cut_ts is None or t["entry_ts"] < cut_ts]
        oos = [t for t in trades if cut_ts is not None and t["entry_ts"] >= cut_ts]
        return {"metrics": metrics(trades, eq, cfg.starting_cash), "in_sample": metrics(ins, [], cfg.starting_cash),
                "out_of_sample_period": metrics(oos, [], cfg.starting_cash), "split_at": cut_ts, "equity": eq, "trades": trades,
                "by_setup": breakdown(trades, "setup"), "by_regime": breakdown(trades, "regime"), "by_symbol": breakdown(trades, "symbol"),
                "out_of_sample": False,
                "explanation": "Same rules on all data; the last part is reported separately. Use walk-forward for calibrated confidence."}

    def _store(self, kind: str, result: dict) -> int:
        summary = {"metrics": result.get("metrics"), "config": result.get("config")}
        with self.db.session() as s:
            rec = BacktestRunRecord(kind=kind, summary=json.dumps(summary, default=str), detail=json.dumps(result, default=str))
            s.add(rec)
            s.flush()
            return rec.id

    def _update_calibration(self, trades: list[dict], tf: str) -> None:
        by = breakdown(trades, "setup")
        with self.db.session() as s:
            for setup, st in by.items():
                pf_trades = [t for t in trades if t["setup"] == setup]
                m = metrics(pf_trades, [], 25_000)
                data = {"available": st["trades"] >= MIN_CALIBRATION_TRADES, "trades": st["trades"], "win_rate": st["win_rate"],
                        "expectancy_r": st["expectancy_r"], "profit_factor": m.get("profit_factor"),
                        "symbols": sorted({t["symbol"] for t in pf_trades}), "timeframe": tf,
                        "period": [min(t["entry_ts"] for t in pf_trades), max(t["entry_ts"] for t in pf_trades)],
                        "source": "walk-forward out-of-sample",
                        "note": (f"Out-of-sample: {st['trades']} trades, win rate {st['win_rate']}%, average {st['expectancy_r']:+.2f}R per trade."
                                 if st["trades"] >= MIN_CALIBRATION_TRADES else
                                 f"Only {st['trades']} out-of-sample trades - too few to trust (need {MIN_CALIBRATION_TRADES}).")}
                rec = s.scalar(select(SetupStatRecord).where(SetupStatRecord.setup == setup, SetupStatRecord.timeframe == tf))
                if rec:
                    rec.data = json.dumps(data)
                else:
                    s.add(SetupStatRecord(setup=setup, timeframe=tf, data=json.dumps(data)))
        self.reload_calibration()

    def reload_calibration(self) -> None:
        with self.db.session() as s:
            rows = s.scalars(select(SetupStatRecord)).all()
            self._calibration = {f"{r.setup}|{r.timeframe}": json.loads(r.data) for r in rows}

    @property
    def calibration(self) -> dict:
        return self._calibration

    def runs(self, limit: int = 30) -> list[dict]:
        with self.db.session() as s:
            rows = s.scalars(select(BacktestRunRecord).order_by(desc(BacktestRunRecord.id)).limit(limit)).all()
            return [{"id": r.id, "created_at": r.created_at.isoformat(), "kind": r.kind, **json.loads(r.summary)} for r in rows]

    def get_run(self, rid: int) -> dict | None:
        with self.db.session() as s:
            r = s.get(BacktestRunRecord, rid)
            return json.loads(r.detail) if r else None
