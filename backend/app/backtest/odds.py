"""Odds check ("time machine") for one plan: entry, stop, target, flat by a time of day.

Two answers, both from the last ~60 days of free 5-minute bars:
  1. Same plan on past days: on each past session, the same distances (as % of price) from the same time of day. Which came
     first: target, stop, or neither by the flat time?
  2. Simulated sessions (10,000 by default): each 5-minute step is taken from the same time of day on a randomly chosen past
     session, switching session at random (20% per step) so calm and busy stretches stay realistic.

Conservative rules, the same as the research code: if the stop and target are both inside one bar, it counts as the stop; a
trade still open at the flat time is closed at that bar's close. Costs and slippage are not included.

This is a simulation of how prices moved recently, not a prediction. It can't see news, trend, or whether your setup has an
edge. It answers one question honestly: are the stop and target sensible for how this market moves at this time of day?
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np

ET = ZoneInfo("America/New_York")
MICRO_TO_DATA = {"MNQ": "NQ", "MES": "ES", "MYM": "YM", "M2K": "RTY", "MGC": "GC", "MCL": "CL"}


def data_symbol(symbol: str) -> str:
    """A TopstepX contract (MNQZ26) -> the free continuous symbol with the same price moves (NQ=F). Stocks unchanged."""
    import re
    m = re.match(r"^([A-Z0-9]{1,4}?)([FGHJKMNQUVXZ])(\d{1,2})$", symbol.upper())
    if m and not symbol.upper().endswith("=F"):
        root = MICRO_TO_DATA.get(m.group(1), m.group(1))
        return f"{root}=F"
    return symbol.upper()


def _tod(hhmm: str) -> time:
    h, m = (int(x) for x in hhmm.split(":"))
    return time(h, m)


def _sessions(bars: list, start: time, flat: time) -> list[tuple[str, float, np.ndarray]]:
    """Per ET date: (date, base price just before `start`, array of [high, low, close] for bars from start to flat)."""
    by: dict[str, list] = {}
    for b in bars:
        t = b.ts.astimezone(ET)
        by.setdefault(t.date().isoformat(), []).append((t.time(), float(b.open), float(b.high), float(b.low), float(b.close)))
    out = []
    for d, rows in sorted(by.items()):
        rows.sort()
        before = [r for r in rows if r[0] < start]
        window = [r for r in rows if start <= r[0] < flat]
        mins = lambda x: x.hour * 60 + x.minute  # noqa: E731
        if not window or mins(window[0][0]) - mins(start) >= 5:
            continue                                   # no bar right at the start time that day
        base = before[-1][4] if before else window[0][1]
        out.append((d, base, np.array([[r[2], r[3], r[4]] for r in window], dtype=float)))
    return out


def _first_hits(hi: np.ndarray, lo: np.ndarray, t_lvl: float, s_lvl: float, long: bool) -> tuple[np.ndarray, np.ndarray]:
    """Index of the first bar that reaches target / stop (len = no hit). Arrays shape (n, K) in log-price relative to entry."""
    k = hi.shape[1]
    hit_t = hi >= t_lvl if long else lo <= t_lvl
    hit_s = lo <= s_lvl if long else hi >= s_lvl
    ft = np.where(hit_t.any(axis=1), hit_t.argmax(axis=1), k)
    fs = np.where(hit_s.any(axis=1), hit_s.argmax(axis=1), k)
    return ft, fs


def odds_check(bars: list, direction: str, entry: float, stop: float, target: float, start_hhmm: str, flat_hhmm: str = "15:55",
               sims: int = 10000, seed: int | None = 7, switch_p: float = 0.2) -> dict:
    long = direction in ("long", "up", "buy")
    risk = (entry - stop) if long else (stop - entry)
    reward = (target - entry) if long else (entry - target)
    if risk <= 0 or reward <= 0:
        raise ValueError("The stop and target must be on opposite sides of the entry.")
    rr = reward / risk
    start, flat = _tod(start_hhmm), _tod(flat_hhmm)
    if start >= flat:
        raise ValueError(f"The plan starts at or after the flat time ({flat_hhmm}), so there's no time for it to work.")
    sess = _sessions(bars, start, flat)
    if len(sess) < 15:
        raise ValueError(f"Only {len(sess)} past sessions have bars at {start_hhmm}; at least 15 are needed.")
    k = int(np.median([len(a) for _, _, a in sess]))
    if k < 2:
        raise ValueError("Too close to the flat time to check.")
    full = [(d, b, a) for d, b, a in sess if len(a) >= k]
    s_lvl, t_lvl = np.log(stop / entry), np.log(target / entry)

    # 1. the same plan on each past day (same % distances, same time of day)
    past = {"target": 0, "stop": 0, "neither": 0, "neither_r": []}
    days = []
    for d, base, a in sess:
        hi, lo, cl = np.log(a[:, 0] / base)[None, :], np.log(a[:, 1] / base)[None, :], np.log(a[:, 2] / base)
        ft, fs = _first_hits(hi, lo, t_lvl, s_lvl, long)
        if fs[0] <= ft[0] and fs[0] < hi.shape[1]:
            res = "stop"
        elif ft[0] < hi.shape[1]:
            res = "target"
        else:
            res = "neither"
            r = (np.exp(cl[-1]) - 1) * entry / risk * (1 if long else -1)
            past["neither_r"].append(float(r))
        past[res] += 1
        days.append({"date": d, "result": res})
    n_past = len(sess)

    # 2. simulated sessions: per 5-minute slot, a bar from a random past session, switching session now and then
    rng = np.random.default_rng(seed)
    m = len(full)
    H = np.array([a[:k, 0] for _, _, a in full])
    L = np.array([a[:k, 1] for _, _, a in full])
    C = np.array([a[:k, 2] for _, _, a in full])
    prevc = np.concatenate([np.array([[b] for _, b, _ in full]), C[:, :-1]], axis=1)
    r_c, r_h, r_l = np.log(C / prevc), np.log(H / prevc), np.log(L / prevc)
    idx = np.empty((sims, k), dtype=int)
    idx[:, 0] = rng.integers(0, m, sims)
    for j in range(1, k):
        sw = rng.random(sims) < switch_p
        idx[:, j] = np.where(sw, rng.integers(0, m, sims), idx[:, j - 1])
    slot = np.broadcast_to(np.arange(k), (sims, k))
    rc, rh, rl = r_c[idx, slot], r_h[idx, slot], r_l[idx, slot]
    c = np.cumsum(rc, axis=1)
    prev = np.concatenate([np.zeros((sims, 1)), c[:, :-1]], axis=1)
    ft, fs = _first_hits(prev + rh, prev + rl, t_lvl, s_lvl, long)
    stop_first = (fs <= ft) & (fs < k)
    target_first = (ft < fs) & (ft < k)
    neither = ~(stop_first | target_first)
    end_r = (np.exp(c[:, -1]) - 1) * entry / risk * (1 if long else -1)
    p_t, p_s, p_n = target_first.mean(), stop_first.mean(), neither.mean()
    avg_n = float(end_r[neither].mean()) if neither.any() else 0.0
    exp_r = p_t * rr - p_s + p_n * avg_n
    breakeven = 1 / (1 + rr)

    p_t, p_s, p_n, avg_n, exp_r = float(p_t), float(p_s), float(p_n), float(avg_n), float(exp_r)
    if p_n >= 0.7:
        verdict, tone = f"Probably won't finish by {flat_hhmm}", "neutral"
        say = (f"In most simulations neither the stop nor the target was reached by {flat_hhmm}; the trade would end wherever the "
               "price is then. The target may be too far for the time left.")
    elif abs(exp_r) < 0.1:
        verdict, tone = "Close to a coin flip", "neutral"
        say = "In the simulation, this plan's wins and losses roughly cancel out before costs."
    elif exp_r > 0:
        verdict, tone = "Leans your way in the simulation", "good"
        say = "With how prices moved recently at this time of day, this stop and target came out ahead in the simulation."
    else:
        verdict, tone = "Leans against you in the simulation", "bad"
        say = "With how prices moved recently at this time of day, this stop and target came out behind in the simulation."
    first, last = sess[0][0], sess[-1][0]
    return {
        "verdict": verdict, "tone": tone, "say": say,
        "plan": {"direction": "long" if long else "short", "entry": entry, "stop": stop, "target": target, "reward_risk": round(rr, 2),
                 "start": start_hhmm, "flat_by": flat_hhmm},
        "simulation": {"sessions": sims, "target_first_pct": round(p_t * 100, 1), "stop_first_pct": round(p_s * 100, 1),
                       "neither_pct": round(p_n * 100, 1), "neither_avg_r": round(avg_n, 2), "expectancy_r": round(float(exp_r), 2),
                       "breakeven_win_pct": round(breakeven * 100, 1), "seed": seed, "bars_per_session": k},
        "past_days": {"days": n_past, "target": past["target"], "stop": past["stop"], "neither": past["neither"],
                      "neither_avg_r": round(float(np.mean(past["neither_r"])), 2) if past["neither_r"] else None,
                      "first": first, "last": last, "recent": days[-10:][::-1]},
        "notes": ["A simulation of how prices moved in the last ~60 days, not a prediction. It can't see news, trend or your setup.",
                  "If the stop and target are both reached inside one 5-minute bar, it counts as the stop.",
                  "Costs and slippage aren't included. A stop is a plan, not a guarantee: prices can jump past it."],
    }


def default_start(now: datetime, session_open: str, flat_hhmm: str) -> tuple[str, str | None]:
    """The plan's start time: now if the market is open with time left, otherwise 10:00 AM (and say so)."""
    t = now.astimezone(ET)
    hhmm = t.strftime("%H:%M")
    if session_open <= hhmm < flat_hhmm and t.weekday() < 5:
        # round down to the 5-minute bar
        return f"{t.hour:02d}:{t.minute - t.minute % 5:02d}", None
    return "10:00", "The market isn't open right now, so this checks the plan as if it started at 10:00 AM New York time."
