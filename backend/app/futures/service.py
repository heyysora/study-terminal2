"""Futures service: wires contracts, sessions, data, levels, signals, prop-firm risk, the futures simulator,
replay and backtests together for the API. Equity code paths are untouched."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ..db.models import FuturesDecisionRecord, FuturesFillRecord, FuturesStateRecord
from ..market_data.types import Timeframe
from . import backtest as fbt
from . import contracts as fc
from . import features as ff
from . import signals as fsig
from .data import SOURCES, FuturesData
from .feed import DowntimeTracker
from .paper import FuturesPaperConfig, FuturesPaperEngine
from .projectx import ProjectXClient
from .risk import SIM_ONLY, PersonalRisk, PropRules, RiskEngine, load_presets
from .sessions import FuturesClock
from .contracts import fmt_num

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
ACCOUNT_ID, REPLAY_ID, EVIDENCE_ID, AUTOMATION_ID, SANDBOX_ID = 1, 2, 3, 4, 5


def resample(bars: list[dict], minutes: int) -> list[dict]:
    if not bars or minutes <= 1:
        return bars
    df = pd.DataFrame(bars).set_index("ts")
    df.index = pd.to_datetime(df.index, utc=True)
    agg = df.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["open"])
    return [{"ts": t.to_pydatetime(), **r} for t, r in zip(agg.index, agg.to_dict("records"), strict=True)]


class FuturesService:
    def __init__(self, settings, db, store, provider, alerts=None, broadcaster=None, news=None):
        self.settings, self.db, self.store, self.alerts, self.broadcaster, self.news = settings, db, store, alerts, broadcaster, news
        self.user_products_error = None
        try:
            fc.load_user_products(settings.data_dir / "futures_products.json")
        except ValueError as e:
            self.user_products_error = str(e)
        self.projectx = None
        key = settings.projectx_api_key.get_secret_value() if settings.projectx_api_key else None
        if settings.projectx_username and key:
            self.projectx = ProjectXClient(settings.projectx_username, key, settings.projectx_base_url,
                                           live=bool(store.get("futures.projectx_live_data", False)))
        self.data = FuturesData(provider, store, self.projectx)
        self.stream = None                          # LiveStream: TopstepX market hub (only with credentials + data source TopstepX)
        presets = load_presets()
        self.fees_default = {**presets["fees"]["round_turn"], **presets["fees"]["derived"]}
        self.engine = FuturesPaperEngine(self.rules(), self.personal(), self.paper_cfg(), self.fees_default)
        st = self._load(ACCOUNT_ID)
        if st:
            try:
                self.engine.load_state(st)
            except Exception:  # noqa: BLE001
                log.exception("futures paper state unreadable; starting fresh")
        self.evidence: dict = self._load(EVIDENCE_ID) or {}
        if not self.evidence:                       # first run: show the research results shipped with this version, clearly dated
            try:
                from pathlib import Path
                self.evidence = json.loads(Path(__file__).with_name("bundled_research.json").read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                log.exception("bundled research results unreadable")
        self.sandbox = FuturesPaperEngine(self.rules(), self.personal(), self.paper_cfg(), self.fees_default)
        sb = self._load(SANDBOX_ID)
        if sb:
            try:
                self.sandbox.load_state(sb)
            except Exception:  # noqa: BLE001
                log.exception("sandbox state unreadable; starting fresh")
        from .automation import AutomationEngine, AutomationState
        self.automation = AutomationEngine(self, AutomationState.from_dict(self._load(AUTOMATION_ID)))
        from .autoresearch import AutoResearch
        self.autoresearch = AutoResearch(self, store)
        from .replay import Replayer
        self.replayer = Replayer(self)
        self.replayer.restore(self._load(REPLAY_ID))
        self.last_actions: dict[str, str] = {}
        self._task: asyncio.Task | None = None
        self._bt_running: set[str] = set()
        self.downtime = DowntimeTracker(20.0)

    # ---------------- settings ----------------

    def rules(self) -> PropRules:
        d = self.store.get("futures.prop") or {}
        return PropRules.from_dict(d) if d else PropRules.from_preset("topstep_tc_50k")

    def personal(self) -> PersonalRisk:
        return PersonalRisk.from_dict(self.store.get("futures.personal") or {})

    def paper_cfg(self) -> FuturesPaperConfig:
        cfg = FuturesPaperConfig.from_dict(self.store.get("futures.paper") or {})
        cfg.fees_round_turn = {**(self.store.get("futures.fees") or {})}
        return cfg

    def apply(self, changes: dict | None = None) -> None:
        if changes is None or any(k.startswith("futures.") for k in changes):
            self.engine.rules, self.engine.personal, self.engine.cfg = self.rules(), self.personal(), self.paper_cfg()
            if self.sandbox is not None:
                self.sandbox.rules, self.sandbox.personal, self.sandbox.cfg = self.rules(), self.personal(), self.paper_cfg()
            if self.projectx:
                self.projectx.live = bool(self.store.get("futures.projectx_live_data", False))

    RULE_FIELDS = ("starting_balance", "max_loss_limit", "mll_type", "mll_lock_balance", "daily_loss_limit", "dll_behavior", "profit_target",
                   "consistency_pct", "consistency_basis", "max_minis", "micro_ratio", "flat_by_ct", "no_new_entries_after_ct",
                   "trade_day_start_ct", "account_type", "account_size", "enabled")
    ACCOUNT_FIELDS = ("starting_balance", "max_loss_limit", "mll_type", "mll_lock_balance", "account_type", "account_size")

    def set_prop(self, d: dict, confirm: bool = False) -> dict:
        cur = self.rules()
        r = PropRules.from_dict({**cur.to_dict(), **{k: v for k, v in d.items() if k not in ("confirmed", "confirmed_at")}})
        changed = [k for k in self.RULE_FIELDS if getattr(r, k) != getattr(cur, k)]
        if confirm:
            r.confirmed, r.confirmed_at = True, datetime.now(timezone.utc).isoformat()
        elif changed:
            r.confirmed, r.confirmed_at = False, None    # a confirmation covers the exact numbers you checked, nothing else
        self.store.update({"futures.prop": r.to_dict()})
        self._account_change(cur, r)
        return r.to_dict()

    def use_preset(self, preset_id: str) -> dict:
        cur = self.rules()
        r = PropRules.from_preset(preset_id)
        self.store.update({"futures.prop": r.to_dict()})
        self._account_change(cur, r)
        return r.to_dict()

    def profiles(self) -> dict:
        return {"profiles": self.store.get("futures.profiles") or {}, "active": self.rules().label}

    def save_profile(self, name: str) -> dict:
        name = name.strip()[:60]
        if not name:
            raise ValueError("Give the profile a name.")
        prof = dict(self.store.get("futures.profiles") or {})
        prof[name] = {"prop": self.rules().to_dict(), "personal": self.personal().to_dict(), "saved_at": datetime.now(timezone.utc).isoformat()}
        self.store.update({"futures.profiles": prof})
        return self.profiles()

    def load_profile(self, name: str) -> dict:
        prof = (self.store.get("futures.profiles") or {}).get(name)
        if not prof:
            raise KeyError(f"No profile named {name}")
        cur = self.rules()
        new = PropRules.from_dict(prof["prop"])
        self.store.update({"futures.prop": new.to_dict(), "futures.personal": prof["personal"]})
        self._account_change(cur, new)
        self.apply()
        return {**self.profiles(), "loaded": name}

    def delete_profile(self, name: str) -> dict:
        prof = dict(self.store.get("futures.profiles") or {})
        prof.pop(name, None)
        self.store.update({"futures.profiles": prof})
        return self.profiles()

    def _account_change(self, old: PropRules, new: PropRules) -> None:
        """A different account size or drawdown rule means a different account. A fresh account is re-based silently;
        one with history needs an explicit reset so old P&L never mixes with new rules."""
        if all(getattr(old, k) == getattr(new, k) for k in self.ACCOUNT_FIELDS):
            return
        e = self.engine
        fresh = not e.fills and not any(p.qty for p in e.positions.values()) and e.balance == old.starting_balance
        e.rules = new
        if fresh:
            e.reset()
        else:
            e.locks["reset_required"] = (f"The account rules changed ({old.label} -> {new.label}). Reset the simulated account to start "
                                         "under the new rules; until then new entries are blocked.")
        self.save()

    # ---------------- persistence ----------------

    def _load(self, rid: int) -> dict | None:
        with self.db.session() as s:
            row = s.get(FuturesStateRecord, rid)
            return json.loads(row.data) if row else None

    def _save(self, rid: int, data: dict) -> None:
        with self.db.session() as s:
            row = s.get(FuturesStateRecord, rid)
            if row is None:
                s.add(FuturesStateRecord(id=rid, data=json.dumps(data, default=str)))
            else:
                row.data = json.dumps(data, default=str)
            s.commit()

    def save(self) -> None:
        self._persist_fills(self.engine, "practice")
        self._save(ACCOUNT_ID, self.engine.to_state())
        if self.sandbox is not None:
            self._persist_fills(self.sandbox, "sandbox")
            self._save(SANDBOX_ID, self.sandbox.to_state())

    def save_automation(self, state: dict) -> None:
        self._save(AUTOMATION_ID, state)

    def _persist_fills(self, eng: FuturesPaperEngine, account: str) -> None:
        if not eng.new_fills:
            return
        rows, eng.new_fills = eng.new_fills, []
        with self.db.session() as s:
            for f in rows:
                if s.get(FuturesFillRecord, f.id) is None:
                    s.add(FuturesFillRecord(id=f.id, account=account, ts=f.ts, data=json.dumps(asdict(f), default=str)))
            s.commit()

    def all_fills(self, account: str = "practice") -> list:
        from sqlalchemy import select

        from .paper import FFill
        with self.db.session() as s:
            rows = s.scalars(select(FuturesFillRecord).where(FuturesFillRecord.account == account).order_by(FuturesFillRecord.ts)).all()
            out = [FFill(**json.loads(r.data)) for r in rows]
        known = {f.id for f in out}
        eng = self.engine if account == "practice" else self.sandbox if account == "sandbox" else None
        return out + ([f for f in eng.fills if f.id not in known] if eng else [])

    # ---------------- contracts / sessions ----------------

    def clock(self, root: str) -> FuturesClock:
        spec = fc.get(root)
        o = (self.store.get("futures.rth") or {}).get(spec.root)
        return FuturesClock(spec, (o[0], o[1]) if o else None)

    def resolve(self, sym: str, on: date | None = None) -> tuple[fc.Contract, fc.ParsedSymbol]:
        p = fc.parse_symbol(sym, allow_bare_root=True)
        if not p:
            raise KeyError(f"'{sym}' isn't a supported futures symbol. Try ES, MNQ, CL, GC or a contract like MESZ26.")
        c = p.contract or fc.front_contract(p.root, on or datetime.now(fc.CT).date())
        return c, p

    def contract_info(self, root: str) -> dict:
        spec = fc.get(root)
        today = datetime.now(fc.CT).date()
        front = fc.front_contract(spec.root, today)
        return {"spec": spec.to_dict(), "front": front.to_dict(today),
                "chain": [c.to_dict(today) for c in fc.next_contracts(spec.root, today, 3)],
                "fees_round_turn": self.engine.round_turn(spec.root), "fee_note": self.engine.fee_per_side(spec.root)[1],
                "session": self.clock(spec.root).state()}

    # ---------------- analysis ----------------

    async def frame(self, contract: fc.Contract, tf: Timeframe = Timeframe.M5, days: float = 6, completed_only: bool = False):
        clk = self.clock(contract.root)
        bars, label, notes = await self.data.bars(contract, tf, clk, days)
        if completed_only and bars and bars[-1].get("closed") is False:
            bars = bars[:-1]                         # never decide on a candle that's still forming
        F = ff.build(ff.bars_to_frame(bars, clk), contract.spec, clk, bar_minutes=tf.seconds // 60)
        return F, label, notes, clk

    def flat_minutes(self, clk: FuturesClock) -> float | None:
        r = self.engine.rules
        rs = clk.rth_start.hour * 60 + clk.rth_start.minute
        re_ = clk.rth_end.hour * 60 + clk.rth_end.minute
        if r.enabled and r.flat_by_ct:
            h, m = map(int, r.flat_by_ct.split(":"))
            return min(h * 60 + m, re_) - rs
        return re_ - rs

    def events(self) -> dict | None:
        if not self.news:
            return None
        try:
            ev = self.news.event_risk(None)
        except Exception:  # noqa: BLE001
            return None
        return {"gate": ev.get("gate"), "reason": next((n["text"] for n in ev.get("notes", []) if n["type"] == "macro_window"), None),
                "notes": ev.get("notes", [])}

    def validated_strategies(self, root: str) -> set[str] | None:
        """Strategy keys ('setup|direction') allowed to trade for this product. Filled by strategy research (P5)."""
        reg = (self.evidence.get(root) or {}).get("validated")
        return set(reg or [])          # nothing trades until a walk-forward research run validates it

    def last_plan(self, contract: str) -> dict | None:
        """The most recent not-yet-acted plan for this contract today (to detect invalidation before entry)."""
        from sqlalchemy import select
        with self.db.session() as s:
            row = s.scalars(select(FuturesDecisionRecord).where(FuturesDecisionRecord.contract == contract,
                                                                FuturesDecisionRecord.outcome.in_(["WATCH_ONLY", "WAIT", "APPROVED"]))
                            .order_by(FuturesDecisionRecord.last_seen.desc()).limit(1)).first()
            if not row or row.acted:
                return None
            d = json.loads(row.data)
        plan = d.get("plan")
        if not plan or (datetime.now(timezone.utc) - datetime.fromisoformat(d["evaluated_at"])).total_seconds() > 3 * 3600:
            return None
        return plan

    def record_decision(self, dec: dict) -> None:
        with self.db.session() as s:
            row = s.get(FuturesDecisionRecord, dec["id"])
            if row is None:
                s.add(FuturesDecisionRecord(id=dec["id"], contract=dec["contract"], bar_time=dec["bar_time"], outcome=dec["outcome"],
                                            mode=dec["mode"], first_seen=dec["evaluated_at"], last_seen=dec["evaluated_at"],
                                            data=json.dumps(dec, default=str)))
            else:
                row.outcome, row.last_seen, row.data = dec["outcome"], dec["evaluated_at"], json.dumps(dec, default=str)
            s.commit()

    def mark_acted(self, decision_id: str, order_id: str) -> None:
        with self.db.session() as s:
            row = s.get(FuturesDecisionRecord, decision_id)
            if row:
                row.acted = order_id
                s.commit()

    def decisions(self, contract: str | None = None, outcome: str | None = None, limit: int = 100) -> list[dict]:
        from sqlalchemy import select
        q = select(FuturesDecisionRecord).order_by(FuturesDecisionRecord.last_seen.desc()).limit(min(limit, 1000))
        if contract:
            q = q.where(FuturesDecisionRecord.contract == contract)
        if outcome:
            q = q.where(FuturesDecisionRecord.outcome == outcome)
        with self.db.session() as s:
            return [{**json.loads(r.data), "first_seen": r.first_seen, "last_seen": r.last_seen, "acted": r.acted} for r in s.scalars(q).all()]

    def all_decisions(self) -> list[dict]:
        """Every stored decision (for the Trust & Validation dashboard)."""
        from sqlalchemy import select
        with self.db.session() as s:
            return [{**json.loads(r.data), "acted": r.acted} for r in s.scalars(select(FuturesDecisionRecord)).all()]

    async def evaluate_contract(self, contract: fc.Contract, tf: Timeframe = Timeframe.M5, mode: str = "assisted", record: bool = True):
        F, label, notes, clk = await self.frame(contract, tf, completed_only=True)
        cur, _, clk, _lab1 = await self._ref(contract)            # also feeds the simulator with the newest 1-minute bars
        now = datetime.now(timezone.utc)
        self.refresh_events()
        snap = self.engine.snapshot(now, clk)
        risk = RiskEngine(self.engine.rules, self.engine.personal)
        st = risk.evaluate(snap)
        pos = self.engine.positions.get(contract.code)
        stop = next((o.stop_price for o in self.engine.orders.values() if o.active and o.contract == contract.code and o.role == "stop_loss"), None)
        F15 = None
        if len(F) and tf == Timeframe.M5:
            five = [{"ts": r.ts.to_pydatetime(), "open": r.o, "high": r.h, "low": r.l, "close": r.c, "volume": r.v} for r in F.itertuples()]
            fifteen = resample(five, 15)
            if fifteen and fifteen[-1]["ts"] + timedelta(minutes=15) > F["ts"].iloc[-1].to_pydatetime() + timedelta(minutes=5):
                fifteen = fifteen[:-1]                                # still forming
            F15 = ff.build(ff.bars_to_frame(fifteen, clk), contract.spec, clk, bar_minutes=15) if fifteen else None
        sig = fsig.evaluate(F, contract.spec, contract.code, label, self.evidence.get(contract.root, {}).get("by_setup", {}), now=now,
                            position=asdict(pos) if pos and pos.qty else None, position_stop=stop, risk_engine=risk, snapshot=snap,
                            round_turn=self.engine.round_turn(contract.root), slippage_ticks=self.engine.cfg.slippage_ticks_market,
                            flat_by_min_from_rth=self.flat_minutes(clk), minutes_to_flat=st["official"].get("minutes_to_flat"),
                            events=self.events(), F15=F15, current_price=cur if _lab1.get("status") in ("realtime", "near_realtime", "polling") else None,
                            validated=self.validated_strategies(contract.root), prev_plan=self.last_plan(contract.code), mode=mode)
        safety = getattr(self, "safety", None)             # the global safety controller can only turn an idea into NO TRADE
        if safety is not None:
            ok, why = safety.permit("futures", f"{contract.spec.root}=F")
            sig["data_health"] = {"allowed": ok, "reason": why}
            if not ok and sig.get("action") not in ("NO TRADE", "WAIT"):
                sig["suppressed_action"] = sig.get("action")
                sig["action"], sig["signal"] = "NO TRADE", None
                sig["reasons"] = [f"Data check: {why}"] + list(sig.get("reasons") or [])
                if isinstance(sig.get("decision"), dict) and "action" in sig["decision"]:
                    sig["decision"] = {**sig["decision"], "action": "NO TRADE", "suppressed_by": "data_health", "suppressed_reason": why}
        if record and sig.get("decision"):
            self.record_decision(sig["decision"])
        return sig, F, label, notes, clk

    async def analysis(self, sym: str, tf: Timeframe = Timeframe.M5) -> dict:
        contract, parsed = self.resolve(sym)
        sig, F, label, notes, clk = await self.evaluate_contract(contract, tf)
        now = datetime.now(timezone.utc)
        self._maybe_alert(contract, sig)
        chart = [{"t": int(r.ts.timestamp()), "o": r.o, "h": r.h, "l": r.l, "c": r.c, "v": r.v} for r in F.tail(400).itertuples()] if len(F) else []
        return {"contract": contract.to_dict(), "parsed": parsed.to_dict(), "spec": contract.spec.to_dict(), "session": clk.state(now),
                "data": label, "data_notes": notes, "levels": fsig.levels_snapshot(F, contract.spec), "signal": sig,
                "evidence": self.evidence.get(contract.root, {}).get("overall"), "evidence_run": self.evidence.get(contract.root, {}).get("run"),
                "chart": chart}

    LIVE_DAYS = {60: 2, 300: 10, 900: 20, 1800: 30, 3600: 60, 14400: 120, 86400: 365}

    async def live_chart(self, root: str, tf: Timeframe) -> dict:
        """Everything the Live Market chart draws. Each overlay is a calculated price with the time it refers to; nothing decorative.
        Levels come from the 5-minute frame (they're price levels, independent of the chart timeframe); structure, swings, FVGs and
        sweeps come from the chart timeframe's own bars (completed bars only)."""
        from .setups import key_levels
        now = datetime.now(timezone.utc)
        contract = fc.front_contract(root, now.astimezone(fc.CT).date())
        spec, clk = contract.spec, self.clock(root)
        bars, label, notes = await self.data.bars(contract, tf, clk, self.LIVE_DAYS[tf.seconds])
        done = bars[:-1] if bars and bars[-1].get("closed") is False else bars
        ts_ = lambda t: int(pd.Timestamp(t).timestamp())  # noqa: E731
        candles = [{"time": ts_(b["ts"]), "open": b["open"], "high": b["high"], "low": b["low"], "close": b["close"],
                    "volume": b.get("volume") or 0, "closed": b.get("closed", True)} for b in bars]
        closes = pd.Series([b["close"] for b in bars], dtype=float)
        emas = {}
        for n in (9, 20, 50, 200):
            e = closes.ewm(span=n, adjust=False, min_periods=n).mean()
            emas[str(n)] = [{"time": c["time"], "value": round(float(v), 4)} for c, v in zip(candles, e, strict=True) if pd.notna(v)]
        out: dict = {"root": root, "contract": contract.to_dict(), "spec": spec.to_dict(), "timeframe": tf.value, "data": label,
                     "notes": notes, "candles": candles, "ema": emas, "vwap": [], "levels": {}, "overlays": {}, "generated_at": now.isoformat(),
                     "stream": self.stream.summary() if self.stream else {"state": "off", "reason": self.stream_off_reason()},
                     "indicators_note": "EMAs use every bar shown, including the forming one; structure overlays use completed bars only.",
                     "last_minute": None}
        feed = self.stream.feed_for(contract.code) if (self.stream and self.data.streaming(contract)) else None
        if feed and feed.builder.bars:
            lm = next(reversed(feed.builder.bars.values())).to_dict()
            out["last_minute"] = {"time": ts_(lm["ts"]), "open": lm["open"], "high": lm["high"], "low": lm["low"], "close": lm["close"],
                                  "volume": lm["volume"], "closed": lm["closed"]}
        # levels from the 5-minute frame
        try:
            F5, _l5, _, _ = await self.frame(contract, Timeframe.M5, days=6, completed_only=True)
            L = fsig.levels_snapshot(F5, spec) if len(F5) else {}
        except Exception as e:  # noqa: BLE001
            F5, L = pd.DataFrame(), {}
            notes.append(f"Levels unavailable: {type(e).__name__}")
        if len(F5):
            r = F5.iloc[-1]
            td = r["td"]
            today = F5[F5["td"] == td]
            rth_today = today[today["rth"]]
            sess_open = float(today["o"].iloc[0]) if len(today) else None
            rth_open = float(rth_today["o"].iloc[0]) if len(rth_today) else None
            lv = {"prev_day_high": L.get("prev_day_high"), "prev_day_low": L.get("prev_day_low"),
                  "overnight_high": L.get("overnight_high"), "overnight_low": L.get("overnight_low"),
                  "session_open": sess_open, "rth_open": rth_open,
                  "opening_range_high": L.get("opening_range_high"), "opening_range_low": L.get("opening_range_low"),
                  "ib_high": L.get("ib_high"), "ib_low": L.get("ib_low"), "vwap": L.get("vwap")}
            out["levels"] = {k: {"price": v, "as_of": L.get("as_of"), "trade_date": str(td)} for k, v in lv.items() if v is not None}
            sr = {k.lower().replace(" ", "_"): float(v) for k, v in key_levels(r).items() if v is not None and not pd.isna(v)}
            out["overlays"]["support_resistance"] = [{"name": k, "price": v, "side": "support" if v < r["c"] else "resistance",
                                                      "as_of": r["ts"].isoformat()} for k, v in sorted(sr.items(), key=lambda kv: kv[1])]
            out["overlays"]["volume_profile"] = {"previous_rth": L.get("profile_prev_rth"), "today": L.get("profile_today")}
            out["overlays"]["structure_state"] = {"trend": L.get("trend"), "as_of": L.get("as_of"), "timeframe": "5Min"}
        # chart-timeframe structure (intraday timeframes, where the feature frame's session logic applies)
        if done and tf.seconds <= 3600:
            F = ff.build(ff.bars_to_frame(done, clk), spec, clk, bar_minutes=tf.seconds // 60)
            if len(F):
                out["vwap"] = [{"time": ts_(t), "value": round(float(v), 4), "trade_date": str(d)}
                               for t, v, d in zip(F["ts"], F["vwap"], F["td"], strict=True) if pd.notna(v)]
                n = ff.LevelParams().swing_n
                marks, swings = [], []
                for i in range(len(F)):
                    x = F.iloc[i]
                    if x["bos_up"] or x["bos_dn"]:
                        broke = F["swing_h"].iloc[i] if x["bos_up"] else F["swing_l"].iloc[i]
                        marks.append({"time": ts_(x["ts"]), "kind": "CHoCH" if x["choch"] else "BOS", "direction": "up" if x["bos_up"] else "down",
                                      "level": float(broke), "close": float(x["c"])})
                    for col, kind in (("swing_h", "high"), ("swing_l", "low")):
                        v, prev = F[col].iloc[i], (F[col].iloc[i - 1] if i else np.nan)
                        if pd.notna(v) and (pd.isna(prev) or v != prev) and i - n >= 0:
                            swings.append({"time": ts_(F["ts"].iloc[i - n]), "kind": kind, "price": float(v), "confirmed": ts_(x["ts"])})
                out["overlays"]["structure"] = marks[-40:]
                out["overlays"]["swings"] = swings[-60:]
                out["overlays"]["fvgs"] = [{**g, "formed": ts_(g["formed"])} for g in ff.recent_fvgs(F, lookback=min(len(F), 300))]
                lvmap = {k: v["price"] for k, v in out["levels"].items() if k != "vwap"}
                cur = F[F["td"] == F["td"].iloc[-1]]               # today's levels only apply to today's bars
                out["overlays"]["sweeps"] = [{**s_, "time": ts_(s_["ts"])} for s_ in ff.sweep_events(cur, lvmap, spec, lookback=len(cur))]
        elif tf.seconds > 3600:
            notes.append("VWAP resets every session, so it isn't drawn on 4h/daily charts; structure overlays are shown on intraday timeframes.")
        return out

    def _maybe_alert(self, contract: fc.Contract, sig: dict) -> None:
        prev = self.last_actions.get(contract.code)
        act = sig["action"]
        self.last_actions[contract.code] = act
        if not self.alerts or act == prev or act not in ("LONG", "SHORT", "EXIT"):
            return
        s = sig.get("signal") or {}
        body = "; ".join(sig.get("reasons", [])[:3])
        if s:
            body = f"Entry {fmt_num(s['entry'])}, stop {fmt_num(s['stop'])}, target {fmt_num(s['target'])}. " + body
        self.alerts.emit("entry" if act != "EXIT" else "position", "high", f"{act} {contract.code} (futures, paper)", body,
                         key=f"fut:{contract.code}", fingerprint=f"{act}:{s.get('entry')}", symbol=contract.code)

    async def dashboard(self, sym: str | None = None) -> dict:
        sym = sym or self.store.get("futures.default_root", "MES")
        a = await self.analysis(sym)
        now = datetime.now(timezone.utc)
        clk = self.clock(a["contract"]["root"])
        upcoming = []
        if self.news:
            try:
                upcoming = [e for e in self.news.upcoming(3) if e.get("importance") == "high"][:6]
            except Exception:  # noqa: BLE001
                upcoming = []
        return {**a, "account": self.engine.summary(now, clk), "upcoming_events": upcoming, "sim_only_note": SIM_ONLY,
                "data_source": self.data.source}

    # ---------------- paper ----------------

    async def _ref(self, contract: fc.Contract) -> tuple[float | None, str, FuturesClock, dict]:
        clk = self.clock(contract.root)
        bars, label, _ = await self.data.bars(contract, Timeframe.M1, clk, days=2)
        self._feed(contract, bars, label, clk)
        return (bars[-1]["close"] if bars else None), label.get("status", "unavailable"), clk, label

    def _feed(self, contract: fc.Contract, bars: list[dict], label: dict, clk: FuturesClock) -> None:
        """Feed completed bars the simulator hasn't seen (marks, fills, flat time). The newest bar may still be forming,
        so it only updates the mark. After a restart or sleep, the bars missed in between are processed as
        "reconcile" bars, so stops and targets hit while the app was off are honoured instead of skipped."""
        if not bars:
            return
        for e in (self.engine, self.sandbox):
            if e is not None:
                self._feed_one(e, contract, bars, label, clk)

    def _feed_one(self, e: FuturesPaperEngine, contract: fc.Contract, bars: list[dict], label: dict, clk: FuturesClock) -> None:
        status = label.get("status", "unavailable")
        last = e.last_bar_ts.get(contract.code)
        done = bars[:-1]
        if last is None:
            new = done[-1:]                      # never seen this contract: start from now, don't replay history
            gap_bars: list = []
        else:
            new = [b for b in done if b["ts"].isoformat() > last]
            step = (bars[-1]["ts"] - bars[-2]["ts"]) if len(bars) >= 2 else timedelta(minutes=1)
            first_new = new[0]["ts"] if new else None
            gap = first_new is not None and (first_new - datetime.fromisoformat(last)) > 3 * step
            busy = any(p.qty for c, p in e.positions.items() if c == contract.code) or any(
                o.active for o in e.orders.values() if o.contract == contract.code)
            gap_bars = new[:-1] if gap or (busy and len(new) > 3) else []
        for b in new:
            st = "reconcile" if b in gap_bars else status
            e.on_bar(contract.code, b["ts"], b["open"], b["high"], b["low"], b["close"], b["volume"], st, clk)
        if gap_bars:
            e._event("info", f"{contract.code}: processed {len(gap_bars)} bars from {gap_bars[0]['ts']:%Y-%m-%d %H:%M} to "
                     f"{gap_bars[-1]['ts']:%H:%M} UTC that arrived while Study Terminal was offline or asleep, so stops and targets hit "
                     "in that time are applied.", datetime.now(timezone.utc))
        lb = bars[-1]
        pos = e.positions.get(contract.code)
        if pos:
            pos.mark, pos.mark_ts, pos.mark_status = lb["close"], lb["ts"].isoformat(), status

    async def preview(self, body: dict) -> dict:
        contract, _ = self.resolve(body["contract"])
        ref, status, clk, lab = await self._ref(contract)
        return self.engine.preview(contract.code, body["side"], int(body["qty"]), body.get("type", "market"), body.get("limit_price"),
                                   body.get("stop_price"), body.get("bracket"), ref, datetime.now(timezone.utc), clk, status, lab.get("age_seconds")) | {
                                       "ref_price": ref, "data_status": status}

    async def submit(self, body: dict) -> dict:
        if not body.get("confirm"):
            raise PermissionError("Confirm the paper order first (you must review it before it's placed in the simulator).")
        contract, _ = self.resolve(body["contract"])
        ref, status, clk, lab = await self._ref(contract)
        o, pv = self.engine.submit(contract.code, body["side"], int(body["qty"]), body.get("type", "market"), body.get("limit_price"),
                                   body.get("stop_price"), body.get("bracket"), ref, datetime.now(timezone.utc), clk, status,
                                   signal_id=body.get("signal_id"), data_age_seconds=lab.get("age_seconds"))
        self.save()
        self._push()
        return {"order": asdict(o) if o else None, "preview": pv}

    def cancel(self, oid: str) -> dict:
        o = self.engine.cancel(oid)
        self.save()
        self._push()
        return asdict(o)

    async def flatten(self, contract: str | None) -> dict:
        now = datetime.now(timezone.utc)
        fills = []
        targets = [contract] if contract else [c for c, p in self.engine.positions.items() if p.qty]
        for c in targets:
            con, _ = self.resolve(c)
            ref, status, clk, lab = await self._ref(con)
            if status not in ("realtime", "near_realtime", "polling") and not (status == "delayed" and self.engine.cfg.allow_delayed_practice):
                raise ValueError(f"Can't flatten {c} in the simulator on {status} data. (In replay, use the replay controls.)")
            fills += self.engine.flatten(con.code, now, "Flattened by you", price=ref, ts_basis=f"{status} last price")
        self.save()
        self._push()
        return {"fills": [asdict(f) for f in fills]}

    def reset(self, starting_balance: float | None = None) -> dict:
        if starting_balance is not None:
            self.set_prop({"starting_balance": float(starting_balance)})
            self.apply()
        self.engine.reset()
        self.automation.state.managed = {k: v for k, v in self.automation.state.managed.items() if v.get("account") != "practice"}
        self.save()
        self.automation.save()
        self._push()
        return {"ok": True, "balance": self.engine.balance}

    def reset_sandbox(self) -> dict:
        self.sandbox.reset()
        self.automation.state.managed = {k: v for k, v in self.automation.state.managed.items() if v.get("account") != "sandbox"}
        self.save()
        self.automation.save()
        return {"ok": True, "balance": self.sandbox.balance}

    def review(self, note: str) -> dict:
        out = self.engine.manual_review(note, datetime.now(timezone.utc))
        self.save()
        return out

    def account(self) -> dict:
        now = datetime.now(timezone.utc)
        root = next((p.root for p in self.engine.positions.values() if p.qty), self.store.get("futures.default_root", "MES"))
        return self.engine.summary(now, self.clock(fc.parse_symbol(root, allow_bare_root=True).root))

    def journal(self, account: str = "practice") -> dict:
        """Round trips from futures simulator fills, net of fees, with R when the entry had a bracket stop."""
        from .journal import journal_report
        eng = self.engine if account == "practice" else self.sandbox
        return {**journal_report(self.all_fills(account), eng.orders, self.decisions(limit=500)), "account": account,
                "review_log": eng.review_log[::-1]}

    # ---------------- background ----------------

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())
        await self.autoresearch.start()
        try:
            await self.sync_stream()
        except Exception:  # noqa: BLE001
            log.exception("live stream start failed")
        a = self.automation
        if a.state.status == "running" or (a.state.status == "stopped" and self.store.get("automation.autostart", True)):
            was = a.state.status

            async def resume():
                # Not awaited by start-up: resuming can wait on market data, and the app's window shouldn't wait for that.
                try:
                    await a.start()
                    a._log("info", "Monitoring resumed after a restart; missed bars are reconciled first." if was == "running"
                           else "Monitoring started with Study Terminal (Settings > automation.autostart).")
                except Exception:  # noqa: BLE001
                    log.exception("automation could not resume after start-up")
            self._resume_task = asyncio.create_task(resume())
        elif a.state.status == "emergency_stopped":
            a._log("high", "Study Terminal started with the emergency stop still active; automation stays off until you clear it.")

    # ---------------- live stream (TopstepX market hub) ----------------

    def stream_wanted(self) -> bool:
        return bool(self.projectx and self.store.get("futures.data_source", "yahoo") == "projectx"
                    and self.store.get("futures.stream_enabled", True))

    async def sync_stream(self) -> dict:
        """Start or stop the live stream to match the settings. Never starts without TopstepX credentials."""
        from .stream import LiveStream
        if self.stream_wanted() and self.stream is None:
            roots = [r for r in (self.automation.state.roots or []) if r] or ["NQ", "MNQ", "ES", "MES"]
            for r in ("NQ", "MNQ", "ES", "MES"):
                if r not in roots:
                    roots.append(r)
            self.stream = LiveStream(self.projectx, roots, rtc_url=self.settings.projectx_rtc_url,
                                     stale_seconds=float(self.store.get("futures.stream_stale_seconds", 30.0)),
                                     broadcaster=self.broadcaster, on_bar_close=self._on_live_bar_close)
            self.data.stream = self.stream
            await self.stream.start()
        elif not self.stream_wanted() and self.stream is not None:
            await self.stream.stop()
            self.stream, self.data.stream = None, None
        return self.stream.summary() if self.stream else {"state": "off", "reason": self.stream_off_reason()}

    def stream_off_reason(self) -> str:
        if not self.projectx:
            return ("No TopstepX API credentials. Live futures data needs a ProjectX API Access subscription and "
                    "STUDY_PROJECTX_USERNAME / STUDY_PROJECTX_API_KEY in the .env file. Charts use Yahoo, labelled DELAYED.")
        if self.store.get("futures.data_source", "yahoo") != "projectx":
            return "Data source is Yahoo (Futures > Data & simulator). Choose TopstepX API to stream live data."
        return "Live streaming is turned off (setting futures.stream_enabled)."

    def _on_live_bar_close(self, root: str, bar: dict):
        """A streamed minute closed. On each 5-minute boundary, let automation re-evaluate now instead of waiting for its timer.
        Same pipeline, same risk engine, same evidence gate: nothing is bypassed."""
        end = bar["ts"] + timedelta(minutes=1)
        w = self.clock(root).window_at(bar["ts"])
        if w is None or int((end - w.open).total_seconds()) % 300:
            return None
        a = self.automation
        if a.state.status == "running" and root in a.state.roots and not a._lock.locked():
            return a.cycle()
        return None

    async def stop(self) -> None:
        await self.autoresearch.stop()
        if self.stream is not None:
            await self.stream.stop()
        if self.automation._task:
            self.automation._task.cancel()
            self.automation._task = None
        self.save()
        if self._task:
            self._task.cancel()
            self._task = None
        if self.projectx:
            await self.projectx.aclose()

    def refresh_events(self) -> None:
        """High-impact releases in the next 2 days, as (name, datetime), for the risk layer's event window."""
        if not self.news:
            return
        try:
            from ..news.sources import event_datetime
            self.engine.upcoming_events = [(e["event"], event_datetime(e)) for e in self.news.upcoming(2) if e.get("importance") == "high"]
        except Exception:  # noqa: BLE001
            log.exception("could not read the economic calendar for futures risk")

    def event_warnings(self, now: datetime) -> list[dict]:
        """One alert per high-impact release, `events.warn_minutes` before it (setting; 0 turns it off). Times come from the
        official calendars; nothing is estimated."""
        lead = int(self.store.get("events.warn_minutes", 30) or 0)
        out = []
        if lead <= 0:
            return out
        warned = self.__dict__.setdefault("_warned_events", set())
        for name, dt in self.engine.upcoming_events:
            if dt is None:
                continue
            mins = (dt - now).total_seconds() / 60
            key = f"{name}|{dt.isoformat()}"
            if 0 <= mins <= lead and key not in warned:
                warned.add(key)
                out.append({"event": name, "at": dt.isoformat(), "minutes": round(mins)})
                block = self.engine.personal.event_block_minutes if self.engine.personal.enabled else None
                body = f"{name} at {dt.astimezone(ET).strftime('%H:%M')} ET, in {round(mins)} min." + (
                    f" New simulated entries are blocked from {block} min before." if block else "")
                self.engine._event("medium", "Upcoming release: " + body, now)
                if self.alerts:
                    self.alerts.emit("market", "medium", f"{name} in {round(mins)} min", body, key=f"fut:event:{key}", fingerprint=key)
        return out

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(20)
            gap = self.downtime.tick()
            if gap:
                self.engine._event("high", f"Study Terminal wasn't running for {gap['seconds'] // 60} min ({gap['from'][:16]} to {gap['to'][:16]} UTC: "
                                   "sleep, shutdown or a stall). Missed bars are reconciled before anything else happens.", datetime.now(timezone.utc))
                if self.alerts:
                    self.alerts.emit("system", "medium", "Monitoring gap", f"No monitoring for {gap['seconds'] // 60} minutes; reconciling.",
                                     key="fut:gap", fingerprint=gap["from"])
            self.refresh_events()
            self.event_warnings(datetime.now(timezone.utc))
            try:
                await self.sync_stream()
            except Exception:  # noqa: BLE001
                log.exception("live stream sync failed")
            try:
                live = set()
                for eng in (self.engine, self.sandbox):
                    if eng is not None:
                        live |= {o.contract for o in eng.orders.values() if o.active} | {c for c, p in eng.positions.items() if p.qty}
                for code in live:
                    con, _ = self.resolve(code)
                    await self._ref(con)
                now = datetime.now(timezone.utc)
                root = next(iter(live), None)
                clk = self.clock(fc.parse_symbol(root, allow_bare_root=True).root) if root else self.clock(self.store.get("futures.default_root", "MES"))
                w = clk.window_at(now)
                self.engine.on_clock(now, w.trade_date.isoformat() if w else None)
                if live:
                    self.save()
                    self._push()
                    st = self.engine.risk_status(now, clk)
                    for w_ in st["warnings"]:
                        if w_["level"] == "high" and self.alerts:
                            self.alerts.emit("position", "high", "Futures risk warning (simulator)", w_["text"], key=f"futrisk:{w_['code']}",
                                             fingerprint=w_["text"][:60])
            except Exception:  # noqa: BLE001
                log.exception("futures loop failed")

    def _push(self) -> None:
        if self.broadcaster:
            try:
                self.broadcaster.publish({"type": "futures", "data": {"balance": self.engine.balance, "unrealized": self.engine.unrealized()}})
            except Exception:  # noqa: BLE001
                pass

    # ---------------- backtest ----------------

    async def backtest(self, root: str, days: int = 59) -> dict:
        spec = fc.get(root)
        if spec.root in self._bt_running:
            raise RuntimeError(f"A {spec.root} backtest is already running.")
        self._bt_running.add(spec.root)
        try:
            clk = self.clock(spec.root)
            raw, _notes = await self.data.yahoo.get_bars(f"{spec.root}=F", Timeframe.M5, datetime.now(timezone.utc) - timedelta(days=days))
            bars = [{"ts": b.ts, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in raw]
            F = await asyncio.to_thread(lambda: ff.build(ff.bars_to_frame(bars, clk), spec, clk))
            fee = self.engine.round_turn(spec.root)
            res = await asyncio.to_thread(fbt.run, F, spec, fee, self.engine.cfg.slippage_ticks_market, 3, self.flat_minutes(clk))
            res["run"] = {"at": datetime.now(timezone.utc).isoformat(), "source": f"Yahoo {spec.root}=F continuous 5-minute bars",
                          "note": ("Continuous front-month series: the roll can create a price jump between two trade dates. "
                                   "Signals at the jump can be distorted."),
                          "fee_note": self.engine.fee_per_side(spec.root)[1]}
            self.evidence[spec.root] = {k: v for k, v in res.items() if k != "trades"} | {"trades_sample": res["trades"][-50:]}
            self._save(EVIDENCE_ID, self.evidence)
            return self.evidence[spec.root]
        finally:
            self._bt_running.discard(spec.root)

    async def research(self, root: str, days: int = 59) -> dict:
        """Walk-forward + holdout research on Yahoo's continuous 5-minute bars; updates the strategy registry."""
        from . import research as fr
        spec = fc.get(root)
        if spec.root in self._bt_running:
            raise RuntimeError(f"A {spec.root} test is already running.")
        self._bt_running.add(spec.root)
        try:
            clk = self.clock(spec.root)
            raw, _ = await self.data.yahoo.get_bars(f"{spec.root}=F", Timeframe.M5, datetime.now(timezone.utc) - timedelta(days=days))
            bars = [{"ts": b.ts, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume} for b in raw]
            F = await asyncio.to_thread(lambda: ff.build(ff.bars_to_frame(bars, clk), spec, clk))
            res = await asyncio.to_thread(fr.walk_forward, F, spec, self.engine.round_turn(spec.root), self.engine.cfg.slippage_ticks_market,
                                          self.flat_minutes(clk))
            res["run"] = {"at": res["run_at"], "source": f"Yahoo {spec.root}=F continuous 5-minute bars", "method": res["method"],
                          "note": "Continuous series: a roll inside the window can distort signals near it.",
                          "fee_note": self.engine.fee_per_side(spec.root)[1]}
            self.evidence[spec.root] = res
            self._save(EVIDENCE_ID, self.evidence)
            return res
        finally:
            self._bt_running.discard(spec.root)

    # ---------------- replay (see replay.py) ----------------

    async def replay_start(self, sym: str, trade_date: str, source_tf: str = "auto", auto: bool = False, auto_experimental: bool = False) -> dict:
        return await self.replayer.start(sym, trade_date, source_tf, auto, auto_experimental)

    async def replay_step(self, n: int = 1) -> dict:
        return self.replayer.step(n)

    def replay_order(self, body: dict) -> dict:
        return self.replayer.order(body)

    def replay_flatten(self) -> dict:
        return self.replayer.flatten()

    # ---------------- screen (TopstepX or futures on TradingView) ----------------

    async def screen_fuse(self, obs: dict, last_change_at: float | None = None) -> dict:
        """Cross-check what's on a futures chart against independently retrieved futures data."""
        import time as _t

        out: dict = {"platform": obs.get("platform"), "asset_class": "futures", "ticker": obs.get("ticker"),
                     "timeframe": obs.get("timeframe"), "checks": []}
        f = obs.get("futures")
        if not f:
            out["status"] = ("I can't read a futures contract on this screen reliably, so I won't guess. Make the symbol visible in the chart "
                             "legend (for example MESZ6 or /MES), or pick the platform in Screen settings.")
            return out
        try:
            contract, _ = self.resolve(f["contract"] or f["root"])
        except KeyError as e:
            out["status"] = str(e.args[0])
            return out
        if f.get("continuous"):
            out["checks"].append({"check": "contract", "ok": True,
                                  "detail": f"The chart shows {f['raw']} (no month); assuming the front contract {contract.code}."})
        if f.get("year_ambiguous"):
            out["checks"].append({"check": "contract", "ok": False, "detail": "The contract year on screen is ambiguous."})
        tf_s = obs.get("timeframe")
        tf = Timeframe(tf_s) if tf_s in ("1Min", "5Min", "15Min") else Timeframe.M5
        if tf_s not in ("1Min", "5Min", "15Min"):
            out["checks"].append({"check": "timeframe", "ok": False,
                                  "detail": f"Chart timeframe {'unknown' if not tf_s else tf_s}; analysis uses 5-minute bars."})
        a = await self.analysis(contract.code, tf)
        label, levels, sig = a["data"], a["levels"], a["signal"]
        spec = contract.spec
        out.update({"ticker": contract.code, "contract": contract.code, "market_label": label, "market_price": levels.get("last"),
                    "analysis_timeframe": tf.value, "session": a["session"]["label"]})
        vp, last = obs.get("visible_price"), levels.get("last")
        if vp is not None and last:
            on_grid = fc.round_to_tick(vp, spec) == round(vp, spec.decimals + 2)
            out["checks"].append({"check": "price on the tick grid", "ok": on_grid,
                                  "detail": f"{fmt_num(vp)} {'is' if on_grid else 'is NOT'} a valid {spec.root} price (tick {spec.tick_size})."
                                  + ("" if on_grid else " The price was probably misread.")})
            diff = 100 * (vp / last - 1)
            ticks = fc.ticks_between(last, vp, spec) if on_grid else None
            out.update({"visible_price": vp, "price_diff_pct": round(diff, 3), "price_diff_ticks": ticks})
            delayed = label.get("status") in ("delayed", "historical", "stale")
            tol = 1.0 if delayed else 0.3
            ok = abs(diff) <= tol
            out["ticker_confirmed"] = ok and on_grid
            out["ticker_confirmation"] = ("price on screen is close to market data" if ok else "unconfirmed")
            detail = f"{diff:+.2f}%" + (f" ({ticks:+d} ticks)" if ticks is not None else "")
            if delayed:
                detail += (f". Market data here is {label.get('status')} ({label.get('reason', '')}); your platform is live, so a gap is "
                           "expected and this check can only catch big mismatches (wrong contract, misread price).")
            out["checks"].append({"check": "visible price vs market data", "ok": ok, "detail": detail})
            if not ok:
                out["discrepancy"] = (f"Screen shows {fmt_num(vp)} but {label.get('provider')} shows {fmt_num(last)} for {contract.code} ({diff:+.2f}%). The chart may "
                                      "be a different contract month, the price may be misread, or a feed is delayed. Recommendations use market data only.")
        else:
            out["ticker_confirmed"] = False
            out["checks"].append({"check": "visible price", "ok": False, "detail": "Couldn't read a price on screen to cross-check."})
        if last_change_at and _t.monotonic() - last_change_at > 90 and label.get("status") in ("polling", "realtime", "near_realtime"):
            out["stale_screen"] = "The screen hasn't changed for 90+ seconds while the market is live. The chart may be frozen."
        out["action"], out["reasons"] = sig["action"], sig["reasons"]
        out["best_signal"] = sig.get("signal") or (sig.get("watch") or sig.get("study_only") or [None])[0]
        out["developing"] = sig.get("developing", [])
        named = {k: v for k, v in levels.items() if isinstance(v, (int, float)) and k not in ("last", "atr")}
        atr = levels.get("atr") or 0
        out["your_drawn_levels"] = []
        for d in obs.get("drawn_levels", []):
            near = min(named.items(), key=lambda kv: abs(kv[1] - d["price_estimate"])) if named else None
            out["your_drawn_levels"].append({**d, "nearest_known_level": near[0].replace("_", " ") if near and atr and abs(near[1] - d["price_estimate"]) <= atr else None})
        if obs.get("position_on_screen"):
            out["position_on_screen"] = {**obs["position_on_screen"], "note": "Read from your screen by OCR; not verified and not used for any calculation."}
        out["origins"] = {"contract_on_screen": f"screen OCR ({obs.get('ticker_source') or 'chart text'})",
                          "visible_price": f"screen OCR ({obs.get('visible_price_source') or 'not read'})",
                          "market_price": f"{label.get('provider')} market data, {label.get('status')}, bar time {label.get('data_time')}",
                          "levels_and_signal": f"computed by Study Terminal from {label.get('provider')} bars, not from the screen"}
        out["sim_only_note"] = "Study Terminal reads your TopstepX screen. It can't place, change or cancel anything on your Topstep account."
        return out

    # ---------------- info ----------------

    def info(self) -> dict:
        from .research import in_sample_only as fr_in_sample_only
        return {"products": fc.all_specs_dict(), "presets": load_presets(), "sources": SOURCES, "data_source": self.data.source,
                "projectx_configured": self.projectx is not None, "user_products_error": self.user_products_error,
                "holiday_coverage": [d.isoformat() for d in (fc.holiday_coverage() or ())],
                "prop": self.engine.rules.to_dict(), "personal": self.engine.personal.to_dict(), "paper": self.engine.cfg.to_dict(),
                "fees_default": self.fees_default, "sim_only_note": SIM_ONLY,
                "evidence": {k: {f: (fr_in_sample_only(v.get(f)) if f == "cost_sensitivity" else v.get(f))
                                 for f in ("overall", "run", "by_setup", "validated", "registry", "oos_metrics", "holdout_metrics",
                                           "holdout_by_setup", "diagnostics", "cost_sensitivity", "data", "folds", "final_params", "method")}
                             for k, v in self.evidence.items()}}
