"""Signal engine: setups -> trade plans -> lifecycle state -> action, with full explanations.

Actions for new trades:  STRONG BUY, BUY, POTENTIAL BUY, WAIT FOR CONFIRMATION,
                         STRONG SHORT (shown as SHORT with high quality), SHORT, POTENTIAL SHORT, NO TRADE
Actions for positions:   HOLD, TAKE PARTIAL PROFITS, SELL, EXIT POSITION, COVER SHORT

States: developing (pattern formed, trigger not near) -> approaching (within 0.25 ATR of trigger)
        -> confirmed (trigger traded, price still inside the entry window)
        -> extended (ran past the entry window: don't chase) / invalidated / expired

Nothing here places orders. Signals are recommendations for you to review.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..analysis.engine import factors, key_levels, to_jsonable
from ..analysis.features import FeatureFrame
from ..paper.engine import position_size
from .explain import GLOSSARY_INLINE, SETUP_EDU, money_example
from .setups import SETUPS, SetupParams, detect

QUALITY_STRONG = 75


@dataclass
class MarketContext:
    """Broad-market read from SPY (and QQQ) on the same timeframe."""
    bias: str = "unknown"          # bullish / bearish / mixed / unknown
    spy_above_vwap: bool | None = None
    spy_change_pct: float | None = None
    high_risk: bool = False
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {"bias": self.bias, "spy_above_vwap": self.spy_above_vwap, "spy_change_pct": self.spy_change_pct,
                "high_risk": self.high_risk, "reasons": list(self.reasons)}


def market_context(spy: FeatureFrame | None) -> MarketContext:
    if spy is None or spy.df.empty:
        return MarketContext(reasons=("SPY data unavailable - market conditions unknown",))
    row = spy.df.iloc[-1]
    fs = factors(row, spy.df.iloc[-2] if len(spy.df) > 1 else None)
    b = sum(f["weight"] for f in fs if f["direction"] == "bullish") - sum(f["weight"] for f in fs if f["direction"] == "bearish")
    bias = "bullish" if b >= 3 else "bearish" if b <= -3 else "mixed"
    chg = float(100 * (row["close"] / row["pdc"] - 1)) if row.get("pdc") == row.get("pdc") and row.get("pdc") else None
    above = bool(row["close"] > row["vwap"]) if row.get("vwap") == row.get("vwap") else None
    reasons, high = [], False
    if chg is not None and chg <= -1.5:
        high = True
        reasons.append(f"SPY is down {chg:.1f}% today - broad selling; longs fight the tide.")
    day_rng_atr = (row["day_high"] - row["day_low"]) / row["atr"] if row.get("atr") else 0
    if spy.intraday and day_rng_atr and day_rng_atr > 12:
        high = True
        reasons.append("SPY's intraday range is unusually wide - volatile, whippy conditions.")
    return MarketContext(bias=bias, spy_above_vwap=above, spy_change_pct=round(chg, 2) if chg is not None else None,
                         high_risk=high, reasons=tuple(reasons))


def _r(x: float | None, nd: int = 2) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(float(x), nd)


def build_plan(df: pd.DataFrame, i: int, cand: pd.Series, p: SetupParams) -> dict:
    """Entry range, stop, targets, invalidation for a candidate detected on row i."""
    long = cand["direction"] == "long"
    sgn = 1 if long else -1
    atr = float(df["atr"].iloc[i])
    entry = float(cand["trigger"])
    stop = float(cand["stop"])
    risk = abs(entry - stop)
    entry_hi = entry + sgn * p.entry_window_atr * atr
    t1, t2, t3 = entry + sgn * risk, entry + sgn * p.target_r * risk, entry + sgn * max(3.0, p.target_r + 1) * risk
    levels = key_levels(df, i)
    blockers = [lv for lv in levels if (lv["price"] > entry if long else lv["price"] < entry) and lv["kind"] != "vwap"]
    blockers.sort(key=lambda lv: abs(lv["price"] - entry))
    room_r = abs(blockers[0]["price"] - entry) / risk if blockers and risk else None
    beyond = [lv["price"] for lv in blockers if abs(lv["price"] - entry) > abs(t2 - entry)]
    if beyond and abs(beyond[0] - entry) <= 4.5 * risk:
        t3 = beyond[0]
    return {"entry": entry, "entry_low": min(entry, entry_hi), "entry_high": max(entry, entry_hi), "stop": stop,
            "invalidation": float(cand["invalidation"]), "t1": t1, "t2": t2, "t3": t3, "risk_per_share": risk,
            "reward_risk": p.target_r, "room_to_first_level_r": room_r,
            "first_level": blockers[0] if blockers else None, "atr": atr}


def quality(row: pd.Series, direction: str, plan: dict, market: MarketContext, mtf: dict | None, intraday: bool) -> tuple[int, list[dict]]:
    long = direction == "long"
    checks = []

    def chk(name, passed, weight, detail):
        checks.append({"check": name, "passed": bool(passed), "weight": weight, "detail": detail})

    st = row.get("structure")
    stack_up = row["ema9"] > row["ema21"] > row["ema50"]
    stack_dn = row["ema9"] < row["ema21"] < row["ema50"]
    chk("Trend agrees", (stack_up or st == "uptrend") if long else (stack_dn or st == "downtrend"), 20,
        f"EMA stack {'up' if stack_up else 'down' if stack_dn else 'mixed'}, structure {st}")
    if intraday and row.get("vwap") == row.get("vwap"):
        chk("VWAP side agrees", row["close"] > row["vwap"] if long else row["close"] < row["vwap"], 15,
            f"close {row['close']:.2f} vs VWAP {row['vwap']:.2f}")
    rv = row.get("rvol")
    chk("Relative volume >= 1.2x", rv == rv and rv is not None and rv >= 1.2, 15, f"RVOL {rv:.2f}" if rv == rv and rv is not None else "RVOL unknown")
    vr = row.get("vol_ratio")
    chk("Signal bar volume >= 1.3x", vr == vr and vr is not None and vr >= 1.3, 10, f"{vr:.2f}x the 20-bar average" if vr == vr and vr is not None else "unknown")
    room = plan["room_to_first_level_r"]
    chk("Room to move (no level within 1R)", room is None or room >= 1.0, 15,
        "no nearby level in the way" if room is None else f"first level {room:.1f}R away ({plan['first_level']['label']})")
    ext = row.get("ext_from_ema9_atr")
    chk("Not extended from 9 EMA", ext != ext or ext is None or abs(ext) < 2, 10, f"{ext:.1f} ATR from the 9 EMA" if ext == ext and ext is not None else "")
    if market.bias != "unknown":
        agree = market.bias in ("mixed", "bullish") if long else market.bias in ("mixed", "bearish")
        chk("Market (SPY) not against it", agree and not market.high_risk, 15, f"SPY bias {market.bias}{', high-risk conditions' if market.high_risk else ''}")
    if mtf and mtf.get("timeframes"):
        htf = mtf["timeframes"][-1]
        chk(f"Higher timeframe ({htf['timeframe']}) agrees", htf["bias"] in (("bullish", "mixed") if long else ("bearish", "mixed")), 10,
            f"{htf['timeframe']} bias {htf['bias']}")
    total = sum(c["weight"] for c in checks)
    got = sum(c["weight"] for c in checks if c["passed"])
    return (round(100 * got / total) if total else 0), checks


def lifecycle(df: pd.DataFrame, i_signal: int, plan: dict, direction: str, live_price: float, p: SetupParams) -> tuple[str, str]:
    """State of a setup detected on row i_signal, given bars after it and the live price."""
    long = direction == "long"
    after = df.iloc[i_signal + 1:]
    bars_since = len(after)
    trig, hi_lim, inval, stop = plan["entry"], plan["entry_high"] if long else plan["entry_low"], plan["invalidation"], plan["stop"]
    if len(after):
        if (after["close"] < inval).any() if long else (after["close"] > inval).any():
            return "invalidated", "Price closed through the invalidation level after the signal."
        hit = (after["high"] >= trig) if long else (after["low"] <= trig)
        triggered = bool(hit.any())
        if triggered:
            since = after.iloc[int(hit.to_numpy().argmax()):]  # from the trigger bar on (stop on that bar counts: conservative)
            if (since["low"] <= stop).any() if long else (since["high"] >= stop).any():
                return "invalidated", "Triggered, then hit the stop level - this idea already failed."
    else:
        triggered = False
    beyond = live_price > hi_lim if long else live_price < hi_lim
    at_or_past = live_price >= trig if long else live_price <= trig
    if (long and live_price <= inval) or (not long and live_price >= inval):
        return "invalidated", "Live price is through the invalidation level."
    if beyond:
        return "extended", "Price already ran past the entry window. Chasing here means a worse price and a bigger stop: skip it."
    if at_or_past or triggered:
        return "confirmed", "Price traded through the trigger and is still inside the entry window."
    if bars_since >= p.expiry_bars:
        return "expired", f"Not triggered within {p.expiry_bars} bars - the moment passed."
    dist_atr = abs(trig - live_price) / plan["atr"] if plan["atr"] else 99
    if dist_atr <= 0.25:
        return "approaching", f"Price is {dist_atr:.2f} ATR from the trigger."
    return "developing", f"Setup formed; price is {dist_atr:.2f} ATR away from the trigger."


def regime(row: pd.Series) -> str:
    """Trend (21 vs 50 EMA) and volatility (ATR% vs its 200-bar median) at one bar.
    The backtester uses the same function, so live and historical regimes are comparable."""
    trend = "up" if row["ema21"] > row["ema50"] else "down"
    v = row.get("atr_pct")
    med = row.get("atr_pct_med")
    vol = "high-vol" if (v == v and med == med and med and v > 1.3 * med) else "normal-vol"
    return f"{trend}/{vol}"


def add_regime_inputs(df: pd.DataFrame) -> None:
    df["atr_pct_med"] = df["atr_pct"].rolling(200, min_periods=20).median()


def evidence_for(calibration: dict | None, setup: str, direction: str, tf: str) -> dict:
    """Out-of-sample evidence for one setup/direction/timeframe, with a tier. Old (pre-tier)
    calibration records are read conservatively: they can never count as reliable."""
    cal = (calibration or {}).get(f"{setup}|{direction}|{tf}")
    if cal and "tier" in cal:
        return cal
    old = (calibration or {}).get(f"{setup}|{tf}")
    if not old:
        return {"available": False, "tier": "none", "tradeable": False,
                "note": "No out-of-sample backtest for this setup yet. Run a walk-forward test on the Backtest page."}
    n, avg = old.get("trades", 0), old.get("expectancy_r", 0)
    t = "insufficient" if n < 30 else "losing" if avg < 0 else "inconclusive"
    return {**old, "tier": t, "tradeable": False,
            "note": f"{old.get('note', '')} (Older test without direction split or confidence interval: re-run walk-forward.)".strip()}


TIER_SHORT = {"none": "untested", "insufficient": "too few test trades", "negative": "clearly lost money in testing",
              "losing": "lost money in testing", "inconclusive": "no proven edge", "promising": "positive but not yet reliable",
              "reliable": "reliable out-of-sample edge"}


ACTION = {
    ("long", "developing"): "POTENTIAL BUY", ("long", "approaching"): "WAIT FOR CONFIRMATION",
    ("short", "developing"): "POTENTIAL SHORT", ("short", "approaching"): "WAIT FOR CONFIRMATION",
}


def evaluate(
    symbol: str,
    ff: FeatureFrame,
    *,
    live_price: float | None = None,
    params: SetupParams | None = None,
    market: MarketContext | None = None,
    mtf: dict | None = None,
    equity: float = 25_000.0,
    risk_pct: float = 0.5,
    min_rr: float = 2.0,
    data_gate: tuple[bool, str, str | None] = (True, "", "1Min"),
    calibration: dict | None = None,
    model_probability: Any = None,
    lookback_bars: int = 8,
    suspect: set[str] | None = None,
) -> dict:
    """All current setup ideas for one symbol/timeframe, plus the single best action."""
    p = params or SetupParams()
    market = market or MarketContext()
    df = ff.df
    tf = ff.timeframe.value
    out: dict[str, Any] = {"symbol": symbol, "timeframe": tf, "signals": [], "action": "NO TRADE", "reasons": []}
    if df.empty or len(df) < 30:
        out["reasons"].append("Not enough bars to evaluate setups.")
        return out
    price = float(live_price if live_price is not None else df["close"].iloc[-1])
    out["price"] = round(price, 4)
    allowed, why, fastest = data_gate
    order = ["1Min", "2Min", "5Min", "15Min", "30Min", "1Hour", "4Hour", "1Day"]
    if not allowed:
        out["reasons"].append(f"Signals disabled: {why}")
        return out
    if fastest and order.index(tf) < order.index(fastest):
        out["reasons"].append(f"Data is not fast enough for {tf} setups ({why}).")
        return out

    cands = detect(df, p, ff.intraday)
    start = max(0, len(df) - lookback_bars)
    recent = cands[cands.index >= df.index[start]]
    latest_by_setup = recent.groupby("setup").tail(1)
    for ts, cand in latest_by_setup.iterrows():
        i = df.index.get_loc(ts)
        row = df.iloc[i]
        plan = build_plan(df, i, cand, p)
        state, state_why = lifecycle(df, i, plan, cand["direction"], price, p)
        score, checks = quality(row, cand["direction"], plan, market, mtf, ff.intraday)
        long = cand["direction"] == "long"
        qty = position_size(equity, risk_pct, plan["entry"], plan["stop"])
        cal = evidence_for(calibration, cand["setup"], cand["direction"], tf)
        tier = cal.get("tier", "none")
        reliable = tier == "reliable"
        cur_regime = regime(row) if "atr_pct_med" in df else None
        reg_ev = (cal.get("by_regime") or {}).get(cur_regime) if cur_regime else None
        regime_ok = bool(reg_ev and reg_ev.get("trades", 0) >= 30 and reg_ev.get("avg_r", -1) >= 0)
        risks = []
        if state == "confirmed":
            if reliable:
                # STRONG needs all three: reliable out-of-sample evidence, a non-negative record in the
                # current market regime, and a high checklist score. A checklist alone never makes it STRONG.
                strong = score >= QUALITY_STRONG and regime_ok
                action = ("STRONG BUY" if strong else "BUY") if long else ("STRONG SHORT" if strong else "SHORT")
            else:
                action = "POTENTIAL BUY" if long else "POTENTIAL SHORT"
        elif state in ("developing", "approaching"):
            action = ACTION[(cand["direction"], state)] if reliable else ("POTENTIAL BUY" if long else "POTENTIAL SHORT")
        else:
            action = "NO TRADE"
        if tier == "negative":
            action = "NO TRADE"
            risks.append(f"Study only: this setup clearly lost money out-of-sample ({cal.get('note', '')}).")
        elif not reliable and state in ("confirmed", "developing", "approaching"):
            risks.append(f"Watch only: {TIER_SHORT.get(tier, tier)}. {cal.get('note', '')}".strip())
        if not checks[0]["passed"]:
            risks.append("Trading against the trend on this timeframe.")
        if market.high_risk:
            risks += list(market.reasons)
        if plan["room_to_first_level_r"] is not None and plan["room_to_first_level_r"] < 1:
            risks.append(f"{plan['first_level']['label']} at ${plan['first_level']['price']:,.2f} sits less than 1R away and may stop the move.")
        if not long:
            risks.append("Short selling: losses are theoretically unlimited; borrow availability and short-sale restrictions are not checked without a broker.")
        if fastest and fastest != "1Min":
            risks.append("Based on polled data that can lag 1-2 minutes.")
        if suspect and ts.isoformat() in suspect:
            action = "NO TRADE"
            risks.insert(0, "The signal bar looks like a bad print (a one-bar spike that immediately reversed). "
                            "Not trading off possibly bad data.")
        if p.target_r < min_rr:
            action = "NO TRADE"
            risks.append(f"Reward:risk {p.target_r}:1 is below your minimum {min_rr}:1.")
        rel = [f for f in factors(row, df.iloc[i - 1] if i else None) if f["direction"] == ("bullish" if long else "bearish")]
        edu = SETUP_EDU[cand["setup"]]
        sig = {
            "id": f"{symbol}|{cand['setup']}|{tf}",
            "symbol": symbol, "setup": cand["setup"], "setup_name": SETUPS[cand["setup"]][1],
            "direction": cand["direction"], "timeframe": tf, "action": action, "state": state, "state_reason": state_why,
            "detected_at": ts.isoformat(), "bars_since": len(df) - 1 - i, "price": round(price, 4),
            "entry_range": [_r(plan["entry_low"]), _r(plan["entry_high"])], "trigger": _r(plan["entry"]),
            "stop": _r(plan["stop"]), "invalidation": _r(plan["invalidation"]),
            "targets": {"t1": _r(plan["t1"]), "t2": _r(plan["t2"]), "t3": _r(plan["t3"])},
            "reward_risk": plan["reward_risk"],
            "position_size": {"shares": qty, "risk_dollars": _r(qty * plan["risk_per_share"]), "equity": _r(equity),
                              "risk_pct": risk_pct, "notional": _r(qty * plan["entry"])},
            "supporting_indicators": rel,
            "structure": {"state": row.get("structure"), "level": _r(cand.get("level")),
                          "first_level_in_the_way": plan["first_level"], "room_r": _r(plan["room_to_first_level_r"])},
            "volume": {"rvol": _r(row.get("rvol")), "signal_bar_vol_ratio": _r(row.get("vol_ratio")), "pressure": _r(row.get("pressure"))},
            "market": market.to_dict(),
            "tradeable": reliable and action not in ("NO TRADE",),
            "evidence_tier": tier,
            "regime": cur_regime,
            "confidence": {
                "historical": cal,
                "historical_in_current_regime": reg_ev,
                "model_probability": model_probability,
                "setup_quality": {"score": score, "checks": checks,
                                  "note": "Rule checklist score - how many quality boxes are ticked, NOT a probability of winning."},
                "certainty": "Not knowable. Any setup can fail; size every trade so a loss is affordable.",
            },
            "risks": risks,
            "confirmation": edu["confirm"],
            "education": {"what": edu["what"], "why": edu["why"], "how_it_fails": edu["fail"],
                          "money": money_example(cand["direction"], plan["entry"], plan["stop"], plan["t2"], max(qty, 1)),
                          "terms": GLOSSARY_INLINE},
        }
        out["signals"].append(to_jsonable(sig))

    rank = {"STRONG BUY": 0, "STRONG SHORT": 0, "BUY": 1, "SHORT": 1, "WAIT FOR CONFIRMATION": 2, "POTENTIAL BUY": 3,
            "POTENTIAL SHORT": 3, "NO TRADE": 9}
    live = sorted(out["signals"], key=lambda s: (rank[s["action"]], -s["confidence"]["setup_quality"]["score"]))
    if live and live[0]["action"] != "NO TRADE" and live[0]["tradeable"]:
        out["action"] = live[0]["action"]
        out["best"] = live[0]
    elif live and live[0]["action"] != "NO TRADE":
        # Ideas exist but none has reliable out-of-sample evidence: the honest answer is NO TRADE.
        out["watch"] = live[0]
        out["reasons"].append(f"NO TRADE: there is a {live[0]['setup_name']} idea ({live[0]['action']}), but this setup has "
                              f"{TIER_SHORT.get(live[0]['evidence_tier'], 'no proven edge')}. It's listed to watch and learn from, not to trade.")
    else:
        out["reasons"].append("No active setup right now. NO TRADE is a valid decision - waiting is a position.")
    if out["action"] == "NO TRADE" and market.high_risk:
        out["reasons"] += list(market.reasons)
    return out


def apply_events(ev: dict, events: dict | None) -> dict:
    """Attach scheduled-event and earnings notes to an evaluation. Inside a major-release window,
    tradeable signals become watch-only and the overall answer is NO TRADE (with the reason)."""
    if not events:
        return ev
    ev["events"] = events
    notes = [n["text"] for n in events.get("notes", [])]
    for s in ev.get("signals", []):
        s["risks"] = notes + s["risks"]
        if events.get("gate") and s.get("tradeable"):
            s["tradeable"] = False
            s["action"] = "POTENTIAL BUY" if s["direction"] == "long" else "POTENTIAL SHORT"
    if events.get("gate") and ev.get("best"):
        ev["watch"] = ev.pop("best")
        ev["action"] = "NO TRADE"
        ev["reasons"].insert(0, "NO TRADE for now: " + next(n["text"] for n in events["notes"] if n["type"] == "macro_window"))
    return ev


def manage_position(pos: dict, ff: FeatureFrame, live_price: float) -> dict:
    """Advice for an open paper position. Never changes orders - it only recommends."""
    df = ff.df
    long = pos["qty"] > 0
    entry, stop = pos["avg_price"], pos.get("stop_loss")
    row, prev = df.iloc[-1], df.iloc[-2] if len(df) > 1 else df.iloc[-1]
    res = {"symbol": pos["symbol"], "side": "long" if long else "short", "price": live_price, "action": "HOLD", "alerts": [], "reasons": []}
    if stop is None:
        res["alerts"].append({"type": "no_stop", "severity": "high", "text": "This position has no protective stop."})
        risk = row["atr"] if row.get("atr") else abs(entry) * 0.01
    else:
        risk = abs(entry - stop)
    r_now = ((live_price - entry) if long else (entry - live_price)) / risk if risk else 0.0
    res["r_multiple"] = round(r_now, 2)
    exit_action = "SELL" if long else "COVER SHORT"
    if stop is not None and abs(live_price - stop) <= 0.25 * risk:
        res["alerts"].append({"type": "stop_approaching", "severity": "high",
                              "text": f"Price ${live_price:,.2f} is within 0.25R of the stop ${stop:,.2f}."})
    tp = pos.get("take_profit")
    if tp and abs(tp - live_price) <= 0.25 * risk:
        res["alerts"].append({"type": "target_approaching", "severity": "medium", "text": f"Price is near the target ${tp:,.2f}."})
    vw = row.get("vwap")
    lost_vwap = vw == vw and vw is not None and ((row["close"] < vw) if long else (row["close"] > vw))
    mh, pmh = row.get("macd_hist"), prev.get("macd_hist")
    fading = mh == mh and pmh == pmh and mh is not None and pmh is not None and ((mh < pmh < 0) if long else (mh > pmh > 0))
    broke = (row["close"] < row["ema50"]) if long else (row["close"] > row["ema50"])
    flipped = row.get("structure") == ("downtrend" if long else "uptrend")
    if broke and flipped:
        res["action"] = "EXIT POSITION"
        res["reasons"].append("Thesis invalidated: price crossed the 50 EMA and structure flipped against the position.")
        res["alerts"].append({"type": "thesis_invalidated", "severity": "high", "text": res["reasons"][-1]})
    elif lost_vwap and fading:
        res["action"] = exit_action
        res["reasons"].append("Momentum weakening: price is on the wrong side of VWAP and MACD momentum is fading. Consider exiting.")
        res["alerts"].append({"type": "momentum_weakening", "severity": "medium", "text": res["reasons"][-1]})
    elif r_now >= 1.0:
        res["action"] = "TAKE PARTIAL PROFITS"
        res["reasons"].append(f"Up {r_now:.1f}R. Many traders take some profit at 1R and move the stop to breakeven (entry), so the rest of the trade can't turn into a loss. You decide; nothing changes automatically.")
        res["alerts"].append({"type": "consider_partial", "severity": "medium", "text": res["reasons"][-1]})
    else:
        res["reasons"].append("Original idea still intact: no invalidation signs.")
    return res
