"""Live signal loop: evaluates monitored symbols on closed bars, tracks signal changes,
manages open positions and raises entry / position / market alerts."""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone

from ..analysis.engine import snapshot, to_jsonable
from ..analysis.service import AnalysisService
from ..backtest.engine import _ml_row
from ..market_data.providers.base import ProviderError
from ..market_data.types import Timeframe
from .engine import apply_events, evaluate, manage_position, market_context
from .setups import SetupParams

log = logging.getLogger(__name__)
ALERT_ACTIONS = {"STRONG BUY", "STRONG SHORT", "BUY", "SHORT", "WAIT FOR CONFIRMATION", "POTENTIAL BUY", "POTENTIAL SHORT"}


class SignalService:
    def __init__(self, monitor, analysis: AnalysisService, paper, alerts, backtests, models, settings_store):
        self.monitor, self.analysis, self.paper = monitor, analysis, paper
        self.alerts, self.backtests, self.models, self.settings = alerts, backtests, models, settings_store
        self.latest: dict[str, dict] = {}          # symbol -> evaluation
        self.position_advice: dict[str, dict] = {}
        self.market: dict = {}
        self._prev: dict[str, tuple] = {}
        self.recent_features: deque = deque(maxlen=500)
        self.focus: set[str] = set()                # e.g. the symbol on screen
        self._task: asyncio.Task | None = None
        self.cycles = 0
        self.journal = None                         # JournalService, set by main
        self.news = None                            # NewsService, set by main

    @property
    def params(self) -> SetupParams:
        return SetupParams(**self.settings.get("signals.params", {}))

    @property
    def timeframes(self) -> list[Timeframe]:
        return [Timeframe(t) for t in self.settings.get("signals.timeframes", ["5Min", "15Min", "1Hour"])]

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _market(self, tf: Timeframe):
        try:
            spy = await self.analysis.frame("SPY", tf)
        except ProviderError:
            spy = None
        mc = market_context(spy)
        self.market = {"timeframe": tf.value, **mc.to_dict()}
        return mc

    async def evaluate_symbol(self, symbol: str, tf: Timeframe | None = None):
        tf = tf or self.timeframes[0]
        ff = await self.analysis.frame(symbol, tf)
        snap = to_jsonable(snapshot(ff))
        mc = await self._market(tf)
        mtf = None
        htfs = [t for t in self.timeframes if t.seconds > tf.seconds][:2]
        if htfs:
            from ..analysis.engine import mtf_summary
            snaps = {tf.value: snap}
            for h in htfs:
                try:
                    snaps[h.value] = to_jsonable(snapshot(await self.analysis.frame(symbol, h)))
                except ProviderError:
                    pass
            mtf = mtf_summary(snaps)
        tick = self.monitor.tracker.latest(symbol)
        live = tick.price if tick else None
        gate = self.monitor.signals_allowed(symbol) if tick else (True, "using last closed bar (symbol not monitored live)", tf.value)
        if ff.served_from_cache:
            gate = (False, f"chart data could not be refreshed ({ff.refresh_error}); an older cached copy is shown", None)
        eq = self.paper.engine.equity()
        ev = evaluate(symbol, ff, live_price=live, params=self.params, market=mc, mtf=mtf, equity=eq,
                      risk_pct=self.paper.risk.max_per_trade_pct, min_rr=self.paper.risk.min_reward_risk, data_gate=gate,
                      calibration=self.backtests.calibration,
                      suspect=set((ff.quality or {}).get("suspect", [])))
        enabled = set(self.settings.get("signals.enabled_setups", []) or [])
        if enabled:
            ev["signals"] = [s for s in ev["signals"] if s["setup"] in enabled]
        if not ff.df.empty:
            feats = _ml_row(ff.df.iloc[-1])
            self.recent_features.append(feats)
            for s in ev["signals"]:
                s["confidence"]["model_probability"] = self.models.predict(feats, s["setup"], s["direction"]) or {
                    "available": False, "note": (self.models.meta or {}).get("reason", "No model trained yet.")}
        ev["mtf"] = mtf
        ev["data"] = self.analysis.data_info(ff)
        if self.news is not None:
            apply_events(ev, self.news.event_risk(symbol))
        ev["data_label"] = self.monitor.label(symbol).model_dump(mode="json") if tick else None
        ev["evaluated_at"] = datetime.now(timezone.utc).isoformat()
        return ev, snap, ff

    def symbols(self) -> list[str]:
        return list(dict.fromkeys([*self.focus, *self.monitor.monitored_symbols()]))

    async def _loop(self) -> None:
        await asyncio.sleep(8)
        while True:
            try:
                if self.monitor.monitoring_enabled and self.monitor.clock.session_at().session.value != "closed":
                    await self.cycle()
            except Exception:
                log.exception("signal cycle failed")
            await asyncio.sleep(max(30, min(self.timeframes[0].seconds / 2, 150)))

    async def cycle(self) -> None:
        self.cycles += 1
        tf = self.timeframes[0]
        for sym in self.symbols():
            try:
                ev, _, ff = await self.evaluate_symbol(sym, tf)
            except ProviderError as e:
                log.info("signal eval %s skipped: %s", sym, e)
                continue
            self.latest[sym] = ev
            if self.journal is not None:
                try:
                    self.journal.log_signals(ev)
                except Exception:  # noqa: BLE001 - logging must never stop the signal loop
                    log.exception("signal journal write failed")
            self._alert_signals(ev)
            self._market_alerts(sym, ff)
        await self.manage_positions()
        self.monitor.broadcaster.publish({"type": "signals", "data": {"market": self.market,
                                                                     "summary": [self.brief(e) for e in self.latest.values()]}})

    @staticmethod
    def brief(ev: dict) -> dict:
        b = ev.get("best")
        return {"symbol": ev["symbol"], "timeframe": ev["timeframe"], "action": ev["action"], "price": ev.get("price"),
                "setup": b["setup_name"] if b else None, "state": b["state"] if b else None,
                "quality": b["confidence"]["setup_quality"]["score"] if b else None, "reasons": ev["reasons"][:2]}

    def _alert_signals(self, ev: dict) -> None:
        from ..alerts.service import signal_alert_text

        for s in ev["signals"]:
            key = f"signal|{s['id']}"
            atr_bucket = round((s["trigger"] or 0), 1)
            fp = f"{s['action']}|{s['state']}|{atr_bucket}|{s['stop']}"
            prev = self._prev.get(key)
            self._prev[key] = (s["action"], s["state"])
            watch_only = not s.get("tradeable") and not self.settings.get("alerts.watch_only_ideas", False)
            if s["action"] in ALERT_ACTIONS and not watch_only:
                sev = "high" if s["action"] in ("STRONG BUY", "STRONG SHORT", "BUY", "SHORT") else "medium" if s["action"] == "WAIT FOR CONFIRMATION" else "low"
                title, body = signal_alert_text(s)
                self.alerts.emit("entry", sev, title, body, key=key, fingerprint=fp, symbol=s["symbol"], data={"signal": s},
                                 link=f"/#/chart/{s['symbol']}")
            elif prev and prev[0] in ALERT_ACTIONS and s["action"] == "NO TRADE":
                self.alerts.emit("entry", "medium", f"Setup no longer valid - {s['symbol']} ({s['setup_name']})",
                                 f"{s['state'].upper()}: {s['state_reason']}", key=key, fingerprint=fp, symbol=s["symbol"],
                                 data={"signal": s})

    def _market_alerts(self, sym: str, ff) -> None:
        if ff.df.empty:
            return
        row = ff.df.iloc[-1]
        ts = ff.df.index[-1].isoformat()
        rv = row.get("rvol")
        if rv == rv and rv is not None and rv >= 3:
            self.alerts.emit("market", "medium", f"Unusual volume - {sym}", f"Volume is {rv:.1f}x normal for this time of day.",
                             key=f"rvol|{sym}", fingerprint=str(int(rv)), symbol=sym)
        if row.get("atr") and (row["high"] - row["low"]) >= 3 * row["atr"]:
            self.alerts.emit("market", "medium", f"Sudden volatility - {sym}",
                             f"The last {ff.timeframe.value} bar spanned {(row['high'] - row['low']) / row['atr']:.1f}x the average range.",
                             key=f"vol|{sym}", fingerprint=ts, symbol=sym)
        if sym == "SPY" and self.market.get("high_risk"):
            self.alerts.emit("market", "high", "High-risk market conditions", " ".join(self.market.get("reasons", [])) +
                             " Consider sitting out or reducing size.", key="market|risk", fingerprint="|".join(self.market.get("reasons", [])))

    async def manage_positions(self) -> None:
        tf = self.timeframes[0]
        advice = {}
        for pos in self.paper.positions():
            sym = pos["symbol"]
            try:
                ff = await self.analysis.frame(sym, tf)
            except ProviderError:
                continue
            tick = self.monitor.tracker.latest(sym)
            price = tick.price if tick else float(ff.df["close"].iloc[-1])
            adv = manage_position(pos, ff, price)
            advice[sym] = adv
            for a in adv["alerts"]:
                self.alerts.emit("position", a["severity"], f"{adv['action']} - {sym}: {a['type'].replace('_', ' ')}", a["text"],
                                 key=f"pos|{sym}|{a['type']}", fingerprint=adv["action"], symbol=sym, data={"advice": adv})
        self.position_advice = advice
