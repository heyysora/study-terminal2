"""Trust & Validation: does the evidence justify more serious use of Study Terminal?

Every status here is computed from RECORDED evidence of real use. Unit tests never count: they prove the code does what it was
written to do, not that it works on your charts, in your markets or with your money. Specifically:
  * Visual recognition (categories 1-4) counts only calibration samples scored with the Visual Monitor reader on REAL screenshots
    (samples marked synthetic are excluded) and real screen captures made while monitoring (injected/test sources are never recorded).
  * Strategies (6-7) count only research results computed on market data, out of sample (walk-forward and final holdout).
  * Paper trading (8-9) counts only COMPLETED simulated trades entered on live market data (not delayed practice, replay or sandbox).

Statuses: UNTESTED (no evidence), IN PROGRESS (some evidence, not enough), PASSED (meets every threshold), FAILED (enough evidence and
it doesn't meet the bar, or a hard rule was broken).

Readiness levels (each needs everything below it):
  EXPERIMENTAL -> VISUAL VALIDATION (1-4) -> STRATEGY VALIDATION (5-7) -> PAPER TRADING VALIDATION (8-9)
  -> LIVE ELIGIBILITY REVIEW (all PASSED plus a longer paper record).
LIVE ELIGIBILITY REVIEW means "ready for YOU to review", nothing more: live brokerage execution stays disabled at every level, and
this module has no way to enable it.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

UNTESTED, IN_PROGRESS, PASSED, FAILED = "UNTESTED", "IN PROGRESS", "PASSED", "FAILED"
LEVELS = ["EXPERIMENTAL", "VISUAL VALIDATION", "STRATEGY VALIDATION", "PAPER TRADING VALIDATION", "LIVE ELIGIBILITY REVIEW"]
LEVEL_NEEDS = {"VISUAL VALIDATION": ["visual_capture", "ocr_price", "instrument_timeframe", "candles_indicators"],
               "STRATEGY VALIDATION": ["signal_generation", "historical_performance", "walk_forward"],
               "PAPER TRADING VALIDATION": ["paper_trading", "risk_management"],
               "LIVE ELIGIBILITY REVIEW": []}
LIVE_DATA_STATUSES = {"realtime", "near_realtime", "polling", "screen_capture"}
LIVE_FILL_BASES = {"realtime market data", "near_realtime market data", "polling market data"}

# Thresholds (shown on the dashboard so the bar is visible, and tested)
CRIT = {
    "min_real_samples": 20,                 # labelled real screenshots per field
    "accuracy_lower_bound": 0.90,           # 95% Wilson lower bound for text fields and the axis (counted by session, see _rate_status)
    "min_real_sessions": 3,                 # samples must come from at least this many different days to pass
    "candle_lower_bound": 0.80,             # 95% Wilson lower bound for candle and indicator estimates
    "min_capture_attempts": 1000,           # real monitoring captures
    "min_capture_days": 3,
    "capture_live_share": 0.90,             # share of captures (window present) that were readable LIVE VISUAL OBSERVATION
    "min_live_decisions": 200,              # decisions computed on live data (market feed or screen capture)
    "min_decision_days": 10,
    "min_paper_trades": 50,                 # completed simulated trades on live data
    "min_paper_days": 20,
    "min_risk_audited_trades": 50,
    "min_risk_days": 10,
    "review_paper_trades": 100,             # extra for LIVE ELIGIBILITY REVIEW
    "review_paper_days": 40,
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def _cat(key: str, name: str, status: str, n: int, metrics: dict, last: str | None, limitations: list[str], evidence: list[str],
         remaining: list[str]) -> dict:
    return {"key": key, "name": name, "status": status, "observations": n, "metrics": metrics, "last_validated": last,
            "limitations": limitations, "evidence": evidence, "remaining": remaining}


def effective_samples(per_session: dict[str, tuple[int, int]]) -> tuple[float, float]:
    """Screenshots taken minutes apart on the same chart aren't independent: when one is misread, the next often is too. This
    shrinks the sample count by how much results cluster within sessions (days): returns (effective n, design effect).
    Cluster-robust variance of the overall accuracy versus the simple binomial variance; never below 1."""
    k = sum(a for a, _ in per_session.values())
    n = sum(b for _, b in per_session.values())
    c = len(per_session)
    if n == 0:
        return 0.0, 1.0
    p = k / n
    if c < 2 or p in (0.0, 1.0):
        return float(n), 1.0          # clustering can't be measured; the minimum number of sessions still applies
    v_cluster = c / (c - 1) * sum((a - p * b) ** 2 for a, b in per_session.values()) / n ** 2
    v_simple = p * (1 - p) / n
    deff = max(1.0, v_cluster / v_simple)
    return n / deff, deff


def _rate_status(k: int, n: int, lower_bar: float, per_session: dict[str, tuple[int, int]] | None = None) -> tuple[str, dict]:
    if n == 0:
        return UNTESTED, {}
    per_session = per_session or {"all": (k, n)}
    n_eff, deff = effective_samples(per_session)
    lo, hi = wilson_float(k / n * n_eff, n_eff)
    m = {"correct": k, "samples": n, "accuracy": round(k / n, 3), "ci95": [round(lo, 3), round(hi, 3)],
         "sessions": len(per_session), "effective_samples": round(n_eff, 1), "design_effect": round(deff, 2),
         "interval_note": "counted by session: screenshots from the same session aren't independent"}
    if n < CRIT["min_real_samples"] or len(per_session) < CRIT["min_real_sessions"]:
        return IN_PROGRESS, m
    if lo >= lower_bar:
        return PASSED, m
    # enough samples but the lower bound misses: FAILED only if even the upper bound can't reach the bar (clearly below)
    return (FAILED if hi < lower_bar else IN_PROGRESS), m


def wilson_float(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(max(0.0, p * (1 - p) / n + z * z / (4 * n * n))) / d
    return max(0.0, c - h), min(1.0, c + h)


# ---------------- visual (1-4) ----------------

def _visual_rows(cal_rows: list[dict]) -> list[dict]:
    """Real (non-synthetic) samples scored with the Visual Monitor reader."""
    return [r for r in cal_rows if not r.get("synthetic") and str(r.get("platform", "")).startswith("topstepx-visual")
            and not (r.get("result") or {}).get("blocked")]


def _field(rows: list[dict], f: str) -> tuple[int, int, str | None, list[dict], dict]:
    k = n = 0
    last = None
    fails = []
    sessions: dict[str, list[int]] = {}
    for r in rows:
        res = (r.get("result") or {}).get(f)
        if not res:
            continue
        n += 1
        ok = bool(res.get("ok"))
        k += ok
        day = str(r.get("at", ""))[:10] or "unknown"
        sessions.setdefault(day, [0, 0])
        sessions[day][0] += ok
        sessions[day][1] += 1
        last = max(last or "", r.get("at", ""))
        if not ok and len(fails) < 5:
            fails.append({"sample": r.get("id"), "read": res.get("read"), "truth": res.get("truth"), "at": r.get("at")})
    return k, n, last or None, fails, {d: (a, b) for d, (a, b) in sessions.items()}


def visual_capture(cal_rows: list[dict], capture_days: dict) -> dict:
    rows = _visual_rows(cal_rows)
    k, n, last, fails, ss = _field(rows, "price_axis")
    s_axis, m_axis = _rate_status(k, n, CRIT["accuracy_lower_bound"], ss)
    found = sum(d.get("window_found", 0) for d in capture_days.values())
    live = sum(d.get("live", 0) for d in capture_days.values())
    attempts = sum(d.get("attempts", 0) for d in capture_days.values())
    days = sorted(d for d, v in capture_days.items() if v.get("attempts"))
    share = live / found if found else None
    methods: dict = defaultdict(int)
    for d in capture_days.values():
        for mth, c in (d.get("methods") or {}).items():
            methods[mth] += c
    if attempts == 0:
        s_cap = UNTESTED
    elif attempts < CRIT["min_capture_attempts"] or len(days) < CRIT["min_capture_days"]:
        s_cap = IN_PROGRESS
    else:
        s_cap = PASSED if share is not None and share >= CRIT["capture_live_share"] else FAILED
    status = _combine([s_axis, s_cap])
    rem = []
    if s_axis != PASSED:
        rem.append(f"Price-axis calibration on real screenshots: {n}/{CRIT['min_real_samples']} samples"
                   + (f", 95% lower bound {m_axis['ci95'][0]:.0%} (needs {CRIT['accuracy_lower_bound']:.0%})" if n else ""))
    if s_cap != PASSED:
        rem.append(f"Real monitoring captures: {attempts}/{CRIT['min_capture_attempts']} over {len(days)}/{CRIT['min_capture_days']} days"
                   + (f"; readable share {share:.0%} (needs {CRIT['capture_live_share']:.0%})" if share is not None else ""))
    return _cat("visual_capture", "Visual capture accuracy", status, n + attempts,
                {"axis": m_axis, "captures": {"attempts": attempts, "window_found": found, "live": live,
                                               "live_share": None if share is None else round(share, 3), "days": len(days),
                                               "methods": dict(methods)}},
                max(filter(None, [last, days[-1] if days else None]), default=None),
                ["Accuracy holds only for the chart layouts, zoom and colors you sampled.",
                 "Capture reliability depends on Windows, Edge and GPU settings on this PC."],
                [f"{n} real calibration samples with an axis check; {attempts} real captures on {len(days)} day(s)."] +
                [f"Axis miss: sample {f['sample']} at {f['at']}" for f in fails], rem)


def ocr_price(cal_rows: list[dict]) -> dict:
    k, n, last, fails, ss = _field(_visual_rows(cal_rows), "price")
    st, m = _rate_status(k, n, CRIT["accuracy_lower_bound"], ss)
    rem = [] if st == PASSED else [f"Current price vs what you typed, on real screenshots: {n}/{CRIT['min_real_samples']} samples"
                                   + (f", 95% lower bound {m['ci95'][0]:.0%} (needs {CRIT['accuracy_lower_bound']:.0%})" if n else "")]
    return _cat("ocr_price", "OCR and price recognition", st, n, m, last,
                ["Only the price tag is read as text; misreads are checked against the axis and tick grid but can still happen."],
                [f"{k} of {n} real screenshots read the price within tolerance."] +
                [f"Miss: read {f['read']} vs {f['truth']} ({f['at']})" for f in fails], rem)


def instrument_timeframe(cal_rows: list[dict]) -> dict:
    rows = _visual_rows(cal_rows)
    ki, ni, li, fi, ssi = _field(rows, "ticker")
    kt, nt, lt, ft, sst = _field(rows, "timeframe")
    si, mi = _rate_status(ki, ni, CRIT["accuracy_lower_bound"], ssi)
    stf, mt = _rate_status(kt, nt, CRIT["accuracy_lower_bound"], sst)
    rem = []
    for label, s, n, m in (("Instrument", si, ni, mi), ("Timeframe", stf, nt, mt)):
        if s != PASSED:
            rem.append(f"{label} on real screenshots: {n}/{CRIT['min_real_samples']} samples"
                       + (f", 95% lower bound {m['ci95'][0]:.0%}" if n else ""))
    return _cat("instrument_timeframe", "Instrument and timeframe recognition", _combine([si, stf]), ni + nt,
                {"instrument": mi, "timeframe": mt}, max(filter(None, [li, lt]), default=None),
                ["A profile with a fixed instrument/timeframe still checks the chart text, but can't detect what isn't shown."],
                [f"Instrument {ki}/{ni}, timeframe {kt}/{nt} correct on real screenshots."] +
                [f"Miss: read {f['read']} vs {f['truth']}" for f in fi + ft], rem)


def candles_indicators(cal_rows: list[dict]) -> dict:
    rows = _visual_rows(cal_rows)
    kc, nc, lc, fc_, ssc = _field(rows, "last_candle")
    ki, ni, li, fi, ssn = _field(rows, "indicators")
    sc, mc = _rate_status(kc, nc, CRIT["candle_lower_bound"], ssc)
    si, mi = _rate_status(ki, ni, CRIT["candle_lower_bound"], ssn)
    rem = []
    if sc != PASSED:
        rem.append(f"Last completed candle O/H/L/C on real screenshots: {nc}/{CRIT['min_real_samples']} samples"
                   + (f", 95% lower bound {mc['ci95'][0]:.0%} (needs {CRIT['candle_lower_bound']:.0%})" if nc else ""))
    if si != PASSED:
        rem.append(f"VWAP/EMA values on real screenshots: {ni}/{CRIT['min_real_samples']} samples"
                   + (f", 95% lower bound {mi['ci95'][0]:.0%}" if ni else ""))
    return _cat("candles_indicators", "Candle and indicator recognition", _combine([sc, si]), nc + ni,
                {"last_candle": mc, "indicators": mi}, max(filter(None, [lc, li]), default=None),
                ["Candle and line values are pixel estimates (about 1-3 ticks).",
                 "Indicators are only checked for the lines whose colors you assigned and whose values you typed."],
                [f"Candles {kc}/{nc}, indicators {ki}/{ni} within tolerance on real screenshots."] +
                [f"Miss: read {f['read']} vs {f['truth']}" for f in fc_ + fi], rem)


# ---------------- signals and strategies (5-7) ----------------

def _decision_violations(d: dict) -> list[str]:
    out = []
    status = (d.get("data") or {}).get("status")
    steps = d.get("steps") or []
    if d.get("outcome") == "APPROVED":
        if status not in LIVE_DATA_STATUSES | {"replay"}:
            out.append(f"approved on {status} data")
        if any(s.get("passed") is False for s in steps):
            out.append("approved although a step failed")
    if len(steps) != 13:
        out.append(f"{len(steps)} of 13 steps recorded")
    return out


def signal_generation(decisions: list[dict]) -> dict:
    live = [d for d in decisions if (d.get("data") or {}).get("status") in LIVE_DATA_STATUSES]
    days = sorted({str(d.get("evaluated_at", ""))[:10] for d in live if d.get("evaluated_at")})
    viol = [(d.get("id"), v) for d in decisions for v in _decision_violations(d)]
    outcomes: dict = defaultdict(int)
    for d in live:
        outcomes[d.get("outcome")] += 1
    if viol:
        st = FAILED
    elif not live:
        st = UNTESTED
    elif len(live) < CRIT["min_live_decisions"] or len(days) < CRIT["min_decision_days"]:
        st = IN_PROGRESS
    else:
        st = PASSED
    rem = [] if st == PASSED else ([f"{len(viol)} decision-integrity violation(s) must be explained and fixed."] if viol else []) + (
        [f"Decisions on live data (TopstepX stream or live visual observation): {len(live)}/{CRIT['min_live_decisions']} over "
         f"{len(days)}/{CRIT['min_decision_days']} trading days."] if len(live) < CRIT["min_live_decisions"] or len(days) < CRIT["min_decision_days"] else [])
    return _cat("signal_generation", "Signal generation", st, len(live),
                {"live_decisions": len(live), "all_decisions": len(decisions), "days": len(days), "outcomes": dict(outcomes),
                 "integrity_violations": len(viol)}, days[-1] if days else None,
                ["This checks that signals are produced correctly and consistently from live data, not that they make money "
                 "(that's categories 6-8)."],
                [f"{len(live)} decisions on live data with every step recorded."] + [f"Violation {i}: {v}" for i, v in viol[:5]], rem)


def historical_performance(evidence: dict) -> dict:
    prods = {r: e for r, e in (evidence or {}).items() if isinstance(e, dict) and e.get("overall")}
    if not prods:
        return _cat("historical_performance", "Historical strategy performance", UNTESTED, 0, {}, None,
                    ["Needs a research run on market data."], [], ["Run Futures > Evidence > Run research for NQ, MNQ, ES, MES."])
    rows, trades, last = {}, 0, None
    for r, e in prods.items():
        ov = e["overall"]
        rows[r] = {k: ov.get(k) for k in ("trades", "days", "avg_r", "avg_r_ci95", "win_rate", "tier")}
        trades += int(ov.get("trades") or 0)
        at = (e.get("run") or {}).get("at") or e.get("run_at")
        last = max(last or "", str(at or ""))
    reliable = [r for r, v in rows.items() if v["tier"] == "reliable" and (v["avg_r"] or 0) > 0]
    losing = [r for r, v in rows.items() if v["tier"] == "losing" or (v["avg_r"] is not None and v["avg_r"] <= 0)]
    st = PASSED if reliable else FAILED if len(losing) == len(rows) else IN_PROGRESS
    rem = [] if st == PASSED else ["An out-of-sample result whose 95% interval for average R is above zero ('reliable' tier) for at least "
                                   "one product. Current: " + ", ".join(f"{r} {v['tier']} ({v['avg_r']}R)" for r, v in rows.items()) + "."]
    return _cat("historical_performance", "Historical strategy performance", st, trades, {"products": rows}, last or None,
                ["Free data covers about 60 days of 5-minute bars: one market period.", "Costs and slippage are modelled, not measured."],
                [f"Out-of-sample walk-forward trades: {trades} across {len(rows)} product(s)."], rem)


def walk_forward(evidence: dict) -> dict:
    prods = {r: e for r, e in (evidence or {}).items() if isinstance(e, dict) and e.get("registry") is not None}
    if not prods:
        return _cat("walk_forward", "Walk-forward validation", UNTESTED, 0, {}, None, [], [],
                    ["Run walk-forward research (Futures > Evidence > Run research)."])
    validated = {r: e.get("validated") or [] for r, e in prods.items()}
    hold = {r: {k: (e.get("holdout_metrics") or {}).get(k) for k in ("trades", "avg_r", "profit_factor")} for r, e in prods.items()}
    n = sum(int(h["trades"] or 0) for h in hold.values())
    any_valid = any(validated.values())
    positive_small = [r for r, h in hold.items() if (h["avg_r"] or 0) > 0]
    st = PASSED if any_valid else IN_PROGRESS if positive_small else FAILED
    last = max((str((e.get("run") or {}).get("at") or e.get("run_at") or "") for e in prods.values()), default=None)
    rem = [] if st == PASSED else ["At least one strategy validated: reliable out-of-sample tier AND a final holdout of 30+ trades with "
                                   "average R > 0 and profit factor > 1.1. Holdouts now: "
                                   + ", ".join(f"{r} {h['trades']} trades {h['avg_r']}R" for r, h in hold.items()) + "."]
    return _cat("walk_forward", "Walk-forward validation", st, n, {"validated": validated, "holdout": hold}, last or None,
                ["Parameters are chosen on earlier folds only; the holdout is used once. More data can still change the verdict."],
                [f"Holdout trades: {n}. Validated strategies: " + (", ".join(f"{r}: {v}" for r, v in validated.items() if v) or "none") + "."],
                rem)


# ---------------- paper trading and risk (8-9) ----------------

def live_trips(trips: list[dict]) -> list[dict]:
    """Completed practice-account trades entered on live market data (not delayed practice, replay, sandbox or reconcile)."""
    return [t for t in trips if t.get("entry_basis") in LIVE_FILL_BASES and t.get("origin") not in ("sandbox", "replay", "replay-auto")]


def paper_trading(trips: list[dict]) -> dict:
    lt = live_trips(trips)
    days = sorted({t.get("trade_date") for t in lt if t.get("trade_date")})
    rs = [t["r"] for t in lt if t.get("r") is not None]
    nets = [t["net"] for t in lt]
    m: dict = {"completed_trades": len(lt), "excluded_trades": len(trips) - len(lt), "days": len(days)}
    if lt:
        m.update({"net_usd": round(sum(nets), 2), "win_rate": round(sum(1 for x in nets if x > 0) / len(nets), 3)})
    if rs:
        mean = sum(rs) / len(rs)
        sd = (sum((x - mean) ** 2 for x in rs) / (len(rs) - 1)) ** 0.5 if len(rs) > 1 else 0.0
        half = 1.96 * sd / math.sqrt(len(rs)) if len(rs) > 1 else None
        m.update({"avg_r": round(mean, 3), "avg_r_ci95": None if half is None else [round(mean - half, 3), round(mean + half, 3)],
                  "trades_with_r": len(rs)})
    if not lt:
        st = UNTESTED
    elif len(lt) < CRIT["min_paper_trades"] or len(days) < CRIT["min_paper_days"]:
        st = IN_PROGRESS
    elif m.get("avg_r_ci95") and m["avg_r_ci95"][0] > 0:
        st = PASSED
    elif m.get("avg_r") is not None and m["avg_r"] <= 0:
        st = FAILED
    else:
        st = IN_PROGRESS
    rem = [] if st == PASSED else [f"Completed simulated trades on live data: {len(lt)}/{CRIT['min_paper_trades']} over "
                                   f"{len(days)}/{CRIT['min_paper_days']} trading days, with the 95% interval of average R above zero"
                                   + (f" (now {m.get('avg_r_ci95')})" if m.get("avg_r_ci95") else "") + "."]
    return _cat("paper_trading", "Paper trading performance", st, len(lt), m, days[-1] if days else None,
                ["Simulated fills (modelled slippage and fees) differ from real fills.",
                 "Trades on delayed practice data, replay and the research sandbox don't count."],
                [f"{len(lt)} completed simulated trades on live data ({m['excluded_trades']} other trades excluded)."], rem)


def risk_audit(trips: list[dict], rules: dict, personal: dict) -> list[dict]:
    """Checks every completed live paper trade against the current limits. Returns violations."""
    out = []
    by_day: dict = defaultdict(float)
    max_c = rules.get("max_contracts_mini")
    for t in sorted(trips, key=lambda x: x.get("closed") or ""):
        tid = f"{t.get('contract')} {t.get('opened')}"
        if personal.get("require_stop", True) and not t.get("stop"):
            out.append({"trade": tid, "rule": "require_stop", "text": "No protective stop."})
        mini = t.get("contracts", 0) / (10 if str(t.get("contract", "")).startswith(("MNQ", "MES", "MYM", "M2K")) else 1)
        if max_c and mini > max_c + 1e-9:
            out.append({"trade": tid, "rule": "max_contracts", "text": f"{t.get('contracts')} contracts exceeds {max_c} mini-equivalent."})
        risk_cap = personal.get("max_risk_per_trade_usd")
        if risk_cap and t.get("r") is not None and t["r"] < -1.25 and t["net"] < -1.25 * risk_cap:
            out.append({"trade": tid, "rule": "max_risk_per_trade", "text": f"Lost {t['net']} (> 1.25x the ${risk_cap} per-trade limit)."})
        day = t.get("trade_date")
        if day:
            before = by_day[day]
            by_day[day] += t["net"]
            dl = personal.get("max_daily_loss_usd")
            if dl and before <= -dl:
                out.append({"trade": tid, "rule": "daily_loss", "text": f"Entered after the daily loss limit (${dl}) was already reached."})
    return out


def risk_management(trips: list[dict], rules: dict, personal: dict, confirmed: bool) -> dict:
    lt = live_trips(trips)
    days = sorted({t.get("trade_date") for t in lt if t.get("trade_date")})
    viol = risk_audit(lt, rules, personal)
    if viol:
        st = FAILED
    elif not lt:
        st = UNTESTED
    elif len(lt) < CRIT["min_risk_audited_trades"] or len(days) < CRIT["min_risk_days"] or not confirmed:
        st = IN_PROGRESS
    else:
        st = PASSED
    rem = []
    if viol:
        rem.append(f"{len(viol)} risk-rule violation(s) in completed trades must be explained and fixed.")
    if len(lt) < CRIT["min_risk_audited_trades"] or len(days) < CRIT["min_risk_days"]:
        rem.append(f"Audited live paper trades: {len(lt)}/{CRIT['min_risk_audited_trades']} over {len(days)}/{CRIT['min_risk_days']} days.")
    if not confirmed:
        rem.append("Confirm your prop-firm rules against your Topstep dashboard (Futures > Rules).")
    return _cat("risk_management", "Risk-management reliability", st, len(lt),
                {"audited_trades": len(lt), "days": len(days), "violations": len(viol), "rules_confirmed": confirmed},
                days[-1] if days else None,
                ["Trades are audited against your CURRENT limits; limits that changed since a trade aren't reconstructed.",
                 "This is the simulator's risk layer. It doesn't control your real Topstep account."],
                [f"{len(lt)} completed live paper trades checked: stops, size, per-trade loss, trading after the daily limit."] +
                [f"Violation: {v['trade']}: {v['text']}" for v in viol[:5]], rem)


# ---------------- overall ----------------

def _combine(statuses: list[str]) -> str:
    if any(s == FAILED for s in statuses):
        return FAILED
    if all(s == PASSED for s in statuses):
        return PASSED
    if all(s == UNTESTED for s in statuses):
        return UNTESTED
    return IN_PROGRESS


def readiness(cats: dict, trips: list[dict]) -> dict:
    level = LEVELS[0]
    for lvl in LEVELS[1:4]:
        if all(cats[k]["status"] == PASSED for k in LEVEL_NEEDS[lvl]):
            level = lvl
        else:
            break
    lt = live_trips(trips)
    days = {t.get("trade_date") for t in lt if t.get("trade_date")}
    review_ok = level == "PAPER TRADING VALIDATION" and len(lt) >= CRIT["review_paper_trades"] and len(days) >= CRIT["review_paper_days"]
    if review_ok:
        level = "LIVE ELIGIBILITY REVIEW"
    idx = LEVELS.index(level)
    nxt = LEVELS[idx + 1] if idx + 1 < len(LEVELS) else None
    missing = []
    if nxt == "LIVE ELIGIBILITY REVIEW":
        missing.append(f"A longer paper record: {len(lt)}/{CRIT['review_paper_trades']} completed live paper trades over "
                       f"{len(days)}/{CRIT['review_paper_days']} trading days.")
    elif nxt:
        for k in LEVEL_NEEDS[nxt]:
            c = cats[k]
            if c["status"] != PASSED:
                missing += [f"{c['name']} ({c['status']}): {r}" for r in (c["remaining"] or ["needs more evidence"])]
    return {"level": level, "level_index": idx, "levels": LEVELS, "next_level": nxt, "remaining_for_next_level": missing,
            "live_execution": "DISABLED. No readiness level enables live brokerage execution; the review level only means the "
                              "record is complete enough for you to review it."}


def build(*, cal_rows: list[dict], capture_days: dict, decisions: list[dict], evidence: dict, trips: list[dict], rules: dict,
          personal: dict, rules_confirmed: bool, now: datetime | None = None) -> dict:
    cats = {c["key"]: c for c in [
        visual_capture(cal_rows, capture_days), ocr_price(cal_rows), instrument_timeframe(cal_rows), candles_indicators(cal_rows),
        signal_generation(decisions), historical_performance(evidence), walk_forward(evidence),
        paper_trading(trips), risk_management(trips, rules, personal, rules_confirmed)]}
    synth = sum(1 for r in cal_rows if r.get("synthetic"))
    return {"generated_at": (now or datetime.now(timezone.utc)).isoformat(), "categories": list(cats.values()),
            "readiness": readiness(cats, trips), "criteria": CRIT,
            "excluded": {"synthetic_screenshots": synth,
                         "note": "Unit tests, synthetic screenshots, replay, delayed practice and sandbox trades are never counted."}}
