"""Why do the setups win or lose? Slices out-of-sample trades along every dimension that could
explain it, with uncertainty on each slice, and turns the clear patterns into plain findings.

Nothing here changes a strategy. It is a microscope, not a tuner: using these slices to pick
filters and then re-testing on the same trades would be optimizing on the test period. Any idea
found here has to be confirmed on new data (a later walk-forward run) before it counts.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .stats import MIN_TRADES, summarize


def _f(t: dict, k: str):
    v = (t.get("features") or {}).get(k)
    return None if v is None or v != v else v


def time_bucket(t: dict) -> str:
    m = _f(t, "minute")
    if m is None:
        return "unknown"
    return ("09:30-10:00 open" if m < 600 else "10:00-11:30 morning" if m < 690 else
            "11:30-14:00 midday" if m < 840 else "14:00-16:00 afternoon")


def trend_alignment(t: dict) -> str:
    stack, st = _f(t, "ema_stack"), _f(t, "structure_code")
    sgn = 1 if t["direction"] == "long" else -1
    votes = [x * sgn for x in (stack, st) if x]
    if not votes:
        return "no clear trend"
    return "with trend" if sum(votes) > 0 else "against trend" if sum(votes) < 0 else "mixed"


def volume_confirmation(t: dict) -> str:
    rv, vr = _f(t, "rvol"), _f(t, "vol_ratio")
    if rv is None or vr is None:
        return "unknown"
    return "volume confirmed" if rv >= 1.2 and vr >= 1.3 else "weak volume"


def extension(t: dict) -> str:
    x = _f(t, "ext_from_ema9_atr")
    if x is None:
        return "unknown"
    x = abs(x)
    return "extended (>1.5 ATR from 9 EMA)" if x > 1.5 else "near 9 EMA (<=1.5 ATR)"


def choppiness(t: dict) -> str:
    c = _f(t, "consolidating")
    bbw = _f(t, "bb_width")
    if c is None:
        return "unknown"
    return "choppy / consolidating" if c else "trending / expanding" if bbw is not None else "not consolidating"


def quality_bucket(t: dict) -> str:
    q = t.get("quality")
    if q is None:
        return "unknown"
    return "checklist < 50" if q < 50 else "checklist 50-69" if q < 70 else "checklist >= 70"


def lateness(t: dict) -> str:
    d = t.get("entry_vs_signal_close_atr")
    if d is None:
        return "unknown"
    return "entry > 0.5 ATR past signal close" if d > 0.5 else "entry within 0.5 ATR"


DIMENSIONS = {
    "setup": lambda t: t["setup"],
    "symbol": lambda t: t["symbol"],
    "timeframe": lambda t: t.get("timeframe", "?"),
    "direction": lambda t: t["direction"],
    "setup_direction": lambda t: f"{t['setup']} ({t['direction']})",
    "regime": lambda t: t.get("regime", "?"),
    "trend": lambda t: (t.get("regime") or "?/?").split("/")[0] + "trend (21/50 EMA)",
    "volatility": lambda t: (t.get("regime") or "?/?").split("/")[-1],
    "time_of_day": time_bucket,
    "trend_alignment": trend_alignment,
    "volume_confirmation": volume_confirmation,
    "extension": extension,
    "choppiness": choppiness,
    "entry_lateness": lateness,
    "setup_quality": quality_bucket,
    "prior_result": lambda t: t.get("_prior", "first trade"),
    "exit_reason": lambda t: t.get("exit_reason", "?"),
}

LABELS = {
    "setup": "Strategy", "symbol": "Ticker", "timeframe": "Timeframe", "direction": "Long vs short",
    "setup_direction": "Strategy and direction", "regime": "Market regime (trend / volatility)", "trend": "Trend",
    "volatility": "Volatility", "time_of_day": "Time of day", "trend_alignment": "Trade vs trend",
    "volume_confirmation": "Volume confirmation", "extension": "Distance from 9 EMA at signal",
    "choppiness": "Choppy vs trending", "entry_lateness": "Entry timing", "setup_quality": "Setup checklist score",
    "prior_result": "After a win or a loss (streaks)", "exit_reason": "How trades ended",
}


def _mark_streaks(trades: list[dict]) -> list[dict]:
    """Tag each trade with the result of the trades just before it (time order, all symbols)."""
    out = sorted(trades, key=lambda t: t["entry_ts"])
    run_sign, run_len = 0, 0
    for t in out:
        if run_len:
            t["_prior"] = f"after {'win' if run_sign > 0 else 'loss'} streak of {'1' if run_len == 1 else '2' if run_len == 2 else '3+'}"
        s = 1 if t["pnl"] > 0 else -1
        run_len = run_len + 1 if s == run_sign else 1
        run_sign = s
    return out


def slices(trades: list[dict]) -> dict:
    trades = _mark_streaks(trades)
    res = {}
    for dim, fn in DIMENSIONS.items():
        groups: dict[str, list[dict]] = defaultdict(list)
        for t in trades:
            groups[fn(t)].append(t)
        rows = []
        for k, g in groups.items():
            s = summarize(g)
            s["bucket"] = k
            s["share_pct"] = round(100 * len(g) / len(trades), 1)
            rows.append(s)
        rows.sort(key=lambda r: -r["trades"])
        res[dim] = {"label": LABELS[dim], "rows": rows}
    return res


def _pct(a: int, b: int) -> float | None:
    return round(100 * a / b, 1) if b else None


def mechanics(trades: list[dict]) -> dict:
    """Entry, exit, stop and target behaviour across all trades."""
    n = len(trades)
    if not n:
        return {}
    r = np.array([t["r_multiple"] for t in trades])
    cost = np.array([t.get("cost_r", 0.0) for t in trades])
    mfe = np.array([t.get("mfe_r", np.nan) for t in trades], dtype=float)
    mae = np.array([t.get("mae_r", np.nan) for t in trades], dtype=float)
    stops = [t for t in trades if t.get("exit_reason") == "stop_loss"]
    targets = [t for t in trades if t.get("exit_reason") == "take_profit"]
    eods = [t for t in trades if t.get("exit_reason") == "eod"]
    losers = [t for t in trades if t["pnl"] <= 0]
    quick = [t for t in stops if t.get("bars_to_exit", 99) <= 2]
    recovered = [t for t in stops if t.get("target_after_stop")]
    recovered_tight = [t for t in recovered if t.get("adverse_before_target_r", 99) <= 1.5]
    target_r = float(np.median([abs(t["target"] - t["planned_entry"]) / t["risk_per_share"] for t in trades if t.get("risk_per_share")]))
    reach = {f"{x}R": _pct(int(np.nansum(mfe >= x)), int(np.isfinite(mfe).sum())) for x in (0.5, 1.0, 1.5, 2.0, 3.0)}
    win_rate = (r > 0).mean()
    avg_w = r[r > 0].mean() if (r > 0).any() else 0.0
    avg_l = r[r <= 0].mean() if (r <= 0).any() else 0.0
    breakeven_wr = (-avg_l / (avg_w - avg_l)) if (avg_w - avg_l) else None
    return {
        "trades": n,
        "avg_r_after_costs": round(float(r.mean()), 3),
        "avg_r_before_costs": round(float((r + cost).mean()), 3),
        "avg_cost_r": round(float(cost.mean()), 3),
        "median_target_r": round(target_r, 2),
        "exit_mix_pct": {"stop": _pct(len(stops), n), "target": _pct(len(targets), n), "end of day": _pct(len(eods), n)},
        "win_rate_pct": round(100 * float(win_rate), 1),
        "avg_winner_r": round(float(avg_w), 3), "avg_loser_r": round(float(avg_l), 3),
        "breakeven_win_rate_pct": round(100 * breakeven_wr, 1) if breakeven_wr is not None else None,
        "mfe_reach_pct": reach,
        "median_mfe_r": round(float(np.nanmedian(mfe)), 2), "median_mae_r": round(float(np.nanmedian(mae)), 2),
        "stopped_within_2_bars_pct": _pct(len(quick), len(stops)),
        "losers_that_were_up_1r_pct": _pct(sum(1 for t in losers if t.get("mfe_r", 0) >= 1.0), len(losers)),
        "stopped_then_hit_target_same_day_pct": _pct(len(recovered), len(stops)),
        "of_those_within_1_5r_adverse_pct": _pct(len(recovered_tight), len(recovered)),
        "median_entry_bars_after_signal": float(np.median([t.get("entry_bars_after_signal", 0) for t in trades])),
    }


def _bucket_r(sl: dict, dim: str) -> dict[str, dict]:
    return {r["bucket"]: r for r in sl[dim]["rows"]}


def findings(trades: list[dict], sl: dict, mech: dict) -> list[dict]:
    """Plain-language conclusions. Each says how strong the evidence is. 'Clear' means the 95%
    interval excludes zero; with ~80 slices, expect a few 'clear' results by chance alone."""
    out: list[dict] = []
    if not trades:
        return [{"title": "No trades", "text": "Nothing to analyze.", "strength": "n/a"}]

    def add(title, text, strength, area):
        out.append({"title": title, "text": text, "strength": strength, "area": area})

    m = mech
    gross, net, cst = m["avg_r_before_costs"], m["avg_r_after_costs"], m["avg_cost_r"]
    add("Costs", f"Slippage and commissions cost {cst:.3f}R per trade on average ({gross:+.3f}R before costs, {net:+.3f}R after). "
        + ("Costs turn a small loss into a bigger one; they are not the main reason for losing." if gross < 0 else
           "Before costs the setups were roughly break-even (within noise); costs push them negative." if net < 0 and gross < 0.05 else
           "Before costs the setups made money; costs erase it." if net < 0 < gross else "Costs are affordable here."),
        "measured", "costs")
    be = m.get("breakeven_win_rate_pct")
    add("Win rate vs what's needed", f"Win rate {m['win_rate_pct']}% against about {be}% needed to break even with the actual average "
        f"winner ({m['avg_winner_r']:+.2f}R) and loser ({m['avg_loser_r']:+.2f}R). Median target was {m['median_target_r']}R; "
        f"only {m['mfe_reach_pct'].get('2.0R')}% of trades ever reached +2R before exiting.", "measured", "targets")
    if (q := m.get("stopped_within_2_bars_pct")) is not None:
        add("False breakouts", f"{q}% of stopped trades were stopped within 2 bars of entry: the move reversed almost immediately. "
            + ("That is a lot of instant failures, typical of breakouts in choppy markets." if q >= 40 else "Not unusually high."),
            "measured", "false breakouts")
    if (g := m.get("losers_that_were_up_1r_pct")) is not None:
        add("Giving back winners", f"{g}% of losing trades were up at least +1R at some point before turning into a loss. "
            + ("A rule to protect gains (like moving the stop to breakeven at +1R) is worth testing on NEW data." if g >= 20 else
               "Few losers were ever meaningfully profitable, so exit management isn't the main problem."), "measured", "exits")
    if (s := m.get("stopped_then_hit_target_same_day_pct")) is not None:
        t = m.get("of_those_within_1_5r_adverse_pct")
        add("Stop placement", f"{s}% of stopped trades went on to reach the original target later the same day"
            + (f"; {t}% of those never went more than 1.5R against the entry first, so a somewhat wider stop might have held. "
               if t is not None else ". ")
            + "Wider stops mean smaller positions, so this is a trade-off to test, not a fix.", "measured", "stops")
    for dim, title, area in (("direction", "Long vs short", "direction"), ("trend_alignment", "Trading with or against the trend", "trend"),
                             ("time_of_day", "Time of day", "session"), ("choppiness", "Choppy markets", "chop"),
                             ("extension", "Late / extended entries", "entry"), ("volume_confirmation", "Volume confirmation", "volume"),
                             ("volatility", "Volatility", "volatility"), ("setup_quality", "Checklist score", "quality")):
        rows = [r for r in sl[dim]["rows"] if r["trades"] >= MIN_TRADES and r["bucket"] != "unknown"]
        if len(rows) < 2:
            continue
        best, worst = max(rows, key=lambda r: r["avg_r"]), min(rows, key=lambda r: r["avg_r"])
        clear = (best.get("avg_r_ci95") and best["avg_r_ci95"][0] > 0) or (worst.get("avg_r_ci95") and worst["avg_r_ci95"][1] < 0)
        add(title, f"Best: {best['bucket']} {best['avg_r']:+.3f}R over {best['trades']} trades "
            f"(95% interval {best.get('avg_r_ci95')}). Worst: {worst['bucket']} {worst['avg_r']:+.3f}R over {worst['trades']} trades "
            f"(interval {worst.get('avg_r_ci95')}).", "clear" if clear else "suggestive only (intervals overlap zero)", area)
    good = [(dim, r) for dim in ("setup_direction", "symbol") for r in sl[dim]["rows"]
            if r["tier"] in ("promising", "reliable")]
    bad = [(dim, r) for dim in ("setup_direction",) for r in sl[dim]["rows"] if r["tier"] == "negative"]
    if bad:
        add("Setups that clearly lose", "; ".join(f"{r['bucket']} ({r['avg_r']:+.3f}R, {r['trades']} trades)" for _, r in bad)
            + ". These are switched to NO TRADE in live signals.", "clear", "strategy")
    add("Setups with positive evidence",
        ("; ".join(f"{r['bucket']} ({r['avg_r']:+.3f}R, {r['trades']} trades, {r['tier']})" for _, r in good)
         if good else "None. No setup or ticker slice has an out-of-sample 95% interval entirely above zero."),
        "clear" if good else "measured", "strategy")
    return out


def report(trades: list[dict], folds: list[dict] | None = None) -> dict:
    sl = slices(trades)
    mech = mechanics(trades)
    return {"overall": summarize(trades, folds), "mechanics": mech, "slices": sl, "findings": findings(trades, sl, mech),
            "caveat": ("These slices describe past out-of-sample trades. Choosing filters from them and re-testing on the same "
                       "trades would be curve-fitting; any idea here must be confirmed on later data.")}
