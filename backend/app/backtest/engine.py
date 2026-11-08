"""Bar-replay backtester.

Honesty rules, each enforced in code:
  - Features are causal (tested) and setups are detected on *closed* bars only.
  - Entries are stop orders placed after the signal bar closes, so they can only fill on later bars.
  - Fills use the paper simulator's own rules: slippage on stops, gap-aware fills,
    trade-through limits, stop-first when one bar touches both stop and target.
  - If the entry bar also trades through the stop, the stop is assumed hit on that bar.
  - Commissions and slippage are always charged. Intraday trades are flattened at the session close.
  - Untriggered entries expire after `expiry_bars`.
Known limits: no partial fills; no borrow costs beyond the simulated fee; the symbol list you
choose today may carry survivorship bias (stocks that died aren't in it).
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta, timezone

import numpy as np
import pandas as pd

from ..analysis.features import FeatureFrame
from ..core.market_clock import ET, MarketClock
from ..market_data.types import DataStatus
from ..paper.engine import OrderRequest, OrderType, PaperConfig, PaperEngine, PriceRef, RiskConfig, Side, TIF
from ..signals.engine import MarketContext, add_regime_inputs, build_plan, quality, regime
from ..signals.setups import SetupParams, detect

ML_FEATURES = ["rsi", "macd_hist", "stoch_k", "roc", "atr_pct", "bb_width", "bb_pctb", "vol_ratio", "rvol", "pressure",
               "ext_from_ema9_atr", "dist_vwap_atr", "ema_stack", "structure_code", "minute", "clv", "consolidating"]


@dataclass
class BacktestConfig:
    setups: list[str] | None = None       # None = all setups
    params: SetupParams = field(default_factory=SetupParams)
    starting_cash: float = 25_000.0
    risk_pct: float = 0.5
    slippage_bps: float = 1.0
    slippage_min: float = 0.01
    commission_per_share: float = 0.0
    commission_per_order: float = 0.0
    allow_short: bool = True
    flatten_eod: bool = True              # intraday: be flat at the close
    max_trades_per_day: int = 3
    daily_loss_pct: float = 2.0
    max_consecutive_losses: int = 3
    max_exposure_pct: float = 100.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["params"] = self.params.to_dict()
        return d


def _ml_row(row: pd.Series) -> dict:
    vw = row.get("vwap")
    d = {k: (float(row[k]) if k in row and row[k] == row[k] else np.nan) for k in ML_FEATURES if k in row}
    d["dist_vwap_atr"] = float((row["close"] - vw) / row["atr"]) if vw == vw and vw is not None and row.get("atr") else np.nan
    d["ema_stack"] = 1.0 if row["ema9"] > row["ema21"] > row["ema50"] else -1.0 if row["ema9"] < row["ema21"] < row["ema50"] else 0.0
    d["structure_code"] = {"uptrend": 1.0, "downtrend": -1.0}.get(row.get("structure"), 0.0)
    d["consolidating"] = float(bool(row.get("consolidating")))
    d["minute"] = float(row.get("minute", 570))
    return d


def _bar_times(ts: pd.Timestamp, bar_seconds: int, intraday: bool) -> tuple[datetime, datetime]:
    t = ts.to_pydatetime()
    if intraday:
        return t, t + timedelta(seconds=bar_seconds - 1)
    d = t.astimezone(ET).date()
    return (datetime.combine(d, time(9, 30), tzinfo=ET).astimezone(timezone.utc),
            datetime.combine(d, time(15, 59, 59), tzinfo=ET).astimezone(timezone.utc))


def run(symbol: str, ff: FeatureFrame, cfg: BacktestConfig, clock: MarketClock, start: datetime | None = None,
        end: datetime | None = None) -> dict:
    df = ff.df
    if df.empty:
        return {"symbol": symbol, "trades": [], "equity": [], "notes": ["no data"]}
    if "atr_pct_med" not in df:
        add_regime_inputs(df)
    cands = detect(df, cfg.params, ff.intraday)
    if cfg.setups:
        cands = cands[cands["setup"].isin(cfg.setups)]
    if not cfg.allow_short:
        cands = cands[cands["direction"] == "long"]
    idx = df.index
    lo_i = 0 if start is None else int(idx.searchsorted(pd.Timestamp(start)))
    hi_i = len(df) if end is None else int(idx.searchsorted(pd.Timestamp(end)))
    if hi_i - lo_i < 2:
        return {"symbol": symbol, "trades": [], "equity": [], "notes": ["window too short"]}

    eng = PaperEngine(PaperConfig(starting_cash=cfg.starting_cash, slippage_bps=cfg.slippage_bps, slippage_min=cfg.slippage_min,
                                  allow_short=cfg.allow_short,
                                  commission_per_share=cfg.commission_per_share, commission_per_order=cfg.commission_per_order),
                      RiskConfig(max_per_trade_pct=cfg.risk_pct, max_daily_loss_pct=cfg.daily_loss_pct, max_open_positions=1,
                                 min_reward_risk=0, require_stop=True, max_consecutive_losses=cfg.max_consecutive_losses,
                                 max_exposure_pct=cfg.max_exposure_pct),
                      clock, now=_bar_times(idx[lo_i], ff.timeframe.seconds, ff.intraday)[0])
    status = DataStatus.NEAR_REALTIME
    bar_s = ff.timeframe.seconds
    sessions = df["session"].to_numpy()
    pending: dict | None = None
    open_trade: dict | None = None
    trades: list[dict] = []
    equity: list[tuple[str, float]] = []
    trades_today: dict = {}
    rejected = 0
    n_fill_seen = 0

    def harvest(i_bar: int):
        nonlocal open_trade, pending, n_fill_seen
        for f in eng.fills[n_fill_seen:]:
            if pending and f.order_id == pending["order_id"]:
                open_trade = {**pending["meta"], "entry_ts": f.ts.isoformat(), "entry_price": f.price, "qty": f.qty,
                              "commission": f.commission, "slippage": f.slippage_cost, "entry_bar": i_bar}
                pending = None
            elif open_trade:
                open_trade["commission"] += f.commission
                open_trade["slippage"] += f.slippage_cost
                open_trade.setdefault("realized", 0.0)
                open_trade["realized"] += f.realized_pnl
                if symbol not in eng.positions:
                    pnl = open_trade["realized"] - open_trade["commission"]
                    risk_d = open_trade["risk_per_share"] * open_trade["qty"]
                    trades.append({**open_trade, "exit_ts": f.ts.isoformat(), "exit_price": f.price,
                                   "exit_reason": "eod" if f.role.value == "exit" else f.role.value,
                                   **_excursions(df, sessions, open_trade, i_bar, f.role.value),
                                   "pnl": round(pnl, 2), "r_multiple": round(pnl / risk_d, 3) if risk_d else 0.0,
                                   "cost_r": round((open_trade["slippage"] + open_trade["commission"]) / risk_d, 3) if risk_d else 0.0,
                                   "bars_held": i_bar - open_trade["entry_bar"],
                                   "hold_minutes": round((f.ts - datetime.fromisoformat(open_trade["entry_ts"])).total_seconds() / 60, 1)})
                    open_trade = None
        n_fill_seen = len(eng.fills)

    for i in range(lo_i, hi_i):
        ts = idx[i]
        row = df.iloc[i]
        b0, b1 = _bar_times(ts, bar_s, ff.intraday)
        eng.roll(b0)
        eng.on_price(symbol, float(row["close"]), b1, status, high=float(row["high"]), low=float(row["low"]),
                     open_=float(row["open"]), bar_start=b0)
        entered_now = pending is not None and eng.orders[pending["order_id"]].status.value == "filled"
        harvest(i)
        if entered_now and symbol in eng.positions:
            # conservative: if this same bar also traded through the stop, assume it was hit
            eng.on_price(symbol, float(row["close"]), b1, status, high=float(row["high"]), low=float(row["low"]))
            harvest(i)
        if pending and i >= pending["expire_i"]:
            o = eng.orders[pending["order_id"]]
            if o.status.value == "open":
                eng.cancel(o.id, b1, "Setup expired untriggered")
            pending = None
        last_of_session = ff.intraday and (i + 1 >= len(df) or sessions[i + 1] != sessions[i])
        if last_of_session:
            if pending:
                o = eng.orders[pending["order_id"]]
                if o.status.value == "open":
                    eng.cancel(o.id, b1, "Session ended")
                pending = None
            if cfg.flatten_eod and symbol in eng.positions:
                eng.close_position(symbol, PriceRef(float(row["close"]), b1, status), b1)
                harvest(i)
        elif pending is None and open_trade is None and symbol not in eng.positions and ts in cands.index:
            day = sessions[i]
            if trades_today.get(day, 0) < cfg.max_trades_per_day:
                c = cands.loc[[ts]].iloc[0]
                plan = build_plan(df, i, c, cfg.params)
                long = c["direction"] == "long"
                eq = eng.equity()
                comm = 2 * (cfg.commission_per_order + cfg.commission_per_share * 100)
                slip = max(plan["entry"] * cfg.slippage_bps / 1e4, cfg.slippage_min)  # entry fills this much worse
                qty = int(max(0, (eq * cfg.risk_pct / 100 - comm) // (plan["risk_per_share"] + slip + 1e-9)))
                cap = min(eng.buying_power() * 0.95, eq * cfg.max_exposure_pct / 100 * 0.99)
                qty = min(qty, int(cap // (max(plan["entry"], 0.01) * (1 + cfg.slippage_bps / 1e4) + cfg.slippage_min)))
                if qty >= 1:
                    req = OrderRequest(symbol=symbol, side=Side.BUY if long else Side.SELL, qty=qty, type=OrderType.STOP,
                                       stop_price=round(plan["entry"], 2), stop_loss=round(plan["stop"], 2),
                                       take_profit=round(plan["t2"], 2), tif=TIF.GTC)
                    o, pv = eng.submit(req, PriceRef(float(row["close"]), b1, status), b1)
                    if o.status.value == "open":
                        trades_today[day] = trades_today.get(day, 0) + 1
                        pending = {"order_id": o.id, "expire_i": i + cfg.params.expiry_bars, "meta": {
                            "symbol": symbol, "setup": c["setup"], "direction": c["direction"], "signal_ts": ts.isoformat(),
                            "planned_entry": plan["entry"], "stop": plan["stop"], "target": plan["t2"],
                            "risk_per_share": plan["risk_per_share"], "features": _ml_row(row),
                            "regime": regime(row), "timeframe": ff.timeframe.value, "signal_i": i,
                            "signal_close": float(row["close"]), "atr": float(plan["atr"] or 0),
                            "quality": quality(row, c["direction"], plan, MarketContext(), None, ff.intraday)[0]}}
                    else:
                        rejected += 1
        equity.append((b1.isoformat(), round(eng.equity(), 2)))
    return {"symbol": symbol, "trades": trades, "equity": equity, "rejected_orders": rejected,
            "final_equity": round(eng.equity(), 2), "notes": ff.notes}


def _excursions(df: pd.DataFrame, sessions, t: dict, i_exit: int, exit_role: str) -> dict:
    """How far a trade went for and against it (MFE/MAE, in R), how fast it was stopped, and what
    price did for the rest of that session after a stop. Bar data can't show the order of prices
    inside a bar, so: the exit bar counts toward MFE only for target exits (a stop bar's high may have
    come after the stop), and the entry bar counts in full (may slightly overstate both)."""
    long = t["direction"] == "long"
    e, rps, i0 = t["entry_price"], t["risk_per_share"] or 1e-9, t["entry_bar"]
    seg = df.iloc[i0:i_exit + 1]
    fav_seg = seg if exit_role == "take_profit" or i_exit == i0 else df.iloc[i0:i_exit]
    hi, lo = float(fav_seg["high"].max()), float(fav_seg["low"].min())
    mfe = (hi - e) / rps if long else (e - lo) / rps
    mae = (e - float(seg["low"].min())) / rps if long else (float(seg["high"].max()) - e) / rps
    out = {"mfe_r": round(max(mfe, 0.0), 3), "mae_r": round(max(mae, 0.0), 3), "bars_to_exit": i_exit - i0,
           "entry_bars_after_signal": i0 - t["signal_i"]}
    if t.get("atr"):
        d = (e - t["signal_close"]) / t["atr"]
        out["entry_vs_signal_close_atr"] = round(d if long else -d, 3)
    if exit_role == "stop_loss":
        j = i_exit + 1
        while j < len(df) and sessions[j] == sessions[i_exit]:
            j += 1
        rest = df.iloc[i_exit + 1:j]
        hit = (rest["high"] >= t["target"]) if long else (rest["low"] <= t["target"])
        reached = bool(hit.any())
        out["target_after_stop"] = reached
        if reached:
            before = pd.concat([seg, rest.iloc[:int(hit.to_numpy().argmax()) + 1]])
            worst = (e - float(before["low"].min())) / rps if long else (float(before["high"].max()) - e) / rps
            out["adverse_before_target_r"] = round(worst, 3)
    return out


def metrics(trades: list[dict], equity: list[tuple[str, float]], starting_cash: float) -> dict:
    n = len(trades)
    out: dict = {"trades": n}
    if equity:
        eq = pd.Series([e for _, e in equity], index=pd.to_datetime([t for t, _ in equity], utc=True))
        peak = eq.cummax()
        dd = (eq / peak - 1)
        out["max_drawdown_pct"] = round(float(dd.min() * 100), 2)
        out["total_return_pct"] = round(float((eq.iloc[-1] / starting_cash - 1) * 100), 2)
        daily = eq.groupby(eq.index.tz_convert(ET).date).last()
        rets = daily.pct_change().dropna()
        out["sharpe"] = round(float(rets.mean() / rets.std() * math.sqrt(252)), 2) if len(rets) > 2 and rets.std() > 0 else None
        out["days"] = int(len(daily))
    if n == 0:
        out.update({"win_rate": None, "note": "No trades - nothing to measure."})
        return out
    pnl = np.array([t["pnl"] for t in trades])
    r = np.array([t["r_multiple"] for t in trades])
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    out.update({
        "win_rate": round(float(len(wins) / n * 100), 1),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else None,
        "expectancy": round(float(pnl.mean()), 2),
        "expectancy_r": round(float(r.mean()), 3),
        "net_pnl": round(float(pnl.sum()), 2),
        "avg_hold_minutes": round(float(np.mean([t["hold_minutes"] for t in trades])), 1),
        "avg_cost_r": round(float(np.mean([t.get("cost_r", 0) for t in trades])), 3),
        "expectancy_r_before_costs": round(float(np.mean([t["r_multiple"] + t.get("cost_r", 0) for t in trades])), 3),
        "exit_reasons": pd.Series([t["exit_reason"] for t in trades]).value_counts().to_dict(),
    })
    if n < 30:
        out["sample_warning"] = f"Only {n} trades: results are dominated by luck at this sample size."
    return out


def breakdown(trades: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        groups.setdefault(t[key], []).append(t)
    return {k: {"trades": len(v), "win_rate": round(100 * sum(t["pnl"] > 0 for t in v) / len(v), 1),
                "expectancy_r": round(float(np.mean([t["r_multiple"] for t in v])), 3),
                "net_pnl": round(sum(t["pnl"] for t in v), 2)} for k, v in sorted(groups.items())}
