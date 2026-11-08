"""Futures setups, evaluated on the last CLOSED bar only. Fixed rules, no parameters fitted to data.

Each setup returns a complete plan: entry, stop, target, invalidation, and the conditions that made it.
The live signal and the backtest call the same `detect`, so what you see is what was tested.

Anti-chase rules apply to every setup: no entry more than half an ATR past its trigger level, no entry after
a 1.5-ATR move in the last three bars, and no entries in the last 20 minutes before the flat-by time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

from .contracts import ProductSpec, round_to_tick

SETUPS = {
    "sweep_reversal": "Liquidity sweep and reclaim of a key level (previous day, overnight, initial balance)",
    "orb_retest": "Opening-range breakout that pulls back to the range edge and holds",
    "vwap_reclaim": "Reclaim (or loss) of session VWAP with a break of structure",
    "ib_breakout": "First close outside the initial balance on above-average volume",
    "trend_pullback": "Pullback into a fresh fair value gap after a break of structure, in trend direction",
}


@dataclass
class SetupParams:
    target_r: float = 2.0
    min_stop_atr: float = 0.4       # stops tighter than this are inside normal noise
    max_stop_atr: float = 2.5
    max_chase_atr: float = 0.5
    max_run_atr: float = 1.5        # 3-bar move that counts as extended
    obstacle_r: float = 0.75        # a key level closer than this (in R) blocks the path to target
    no_entry_last_minutes: int = 20
    flat_by_min_from_rth: float | None = None   # set by caller from the prop rules (minutes after RTH open)
    stop_buffer_ticks: int = 2


@dataclass
class Setup:
    name: str
    direction: int
    entry: float
    stop: float
    target: float
    trigger: float
    trigger_label: str
    conditions: list[str] = field(default_factory=list)
    invalidation: str = ""
    entry_range: tuple[float, float] | None = None
    next_level: tuple[str, float] | None = None
    status: str = "confirmed"

    @property
    def risk_points(self) -> float:
        return abs(self.entry - self.stop)

    def to_dict(self) -> dict:
        return {"setup": self.name, "description": SETUPS[self.name], "direction": "long" if self.direction > 0 else "short",
                "entry": self.entry, "entry_range": list(self.entry_range) if self.entry_range else None, "stop": self.stop,
                "target": self.target, "trigger": self.trigger, "trigger_label": self.trigger_label, "conditions": self.conditions,
                "invalidation": self.invalidation, "next_level": {"label": self.next_level[0], "price": self.next_level[1]} if self.next_level else None,
                "status": self.status}


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def key_levels(r: pd.Series) -> dict[str, float]:
    out = {}
    for k, label in (("pdh", "PDH"), ("pdl", "PDL"), ("onh", "ONH"), ("onl", "ONL"), ("ib_h", "IBH"), ("ib_l", "IBL"),
                     ("or_h", "ORH"), ("or_l", "ORL"), ("vwap", "VWAP"), ("pgh", "Prev Globex H"), ("pgl", "Prev Globex L")):
        v = r.get(k)
        if _ok(v):
            out[label] = float(v)
    return out


def _plan(spec: ProductSpec, name: str, d: int, r: pd.Series, stop_raw: float, trigger: float, label: str, conds: list[str],
          p: SetupParams, levels: dict[str, float]) -> tuple[Setup | None, str | None]:
    tick = float(spec.tick)
    entry = round_to_tick(r["c"], spec)
    stop = round_to_tick(stop_raw - d * p.stop_buffer_ticks * tick, spec, "down" if d > 0 else "up")
    risk = abs(entry - stop)
    atr = r["atr"]
    if risk < p.min_stop_atr * atr:
        return None, f"{name}: stop would be {risk:g} points, inside normal noise (ATR {atr:.2f})."
    if risk > p.max_stop_atr * atr:
        return None, f"{name}: stop would be {risk:g} points, too wide for this setup."
    target = round_to_tick(entry + d * p.target_r * risk, spec, "down" if d > 0 else "up")
    ahead = sorted(((lbl, v) for lbl, v in levels.items() if (v - entry) * d > tick), key=lambda kv: abs(kv[1] - entry))
    if ahead and abs(ahead[0][1] - entry) < p.obstacle_r * risk:
        return None, f"{name}: {ahead[0][0]} at {ahead[0][1]:g} sits {abs(ahead[0][1] - entry) / risk:.2f}R away, in the way of the target."
    nxt = next(((lbl, v) for lbl, v in ahead if abs(v - entry) >= abs(target - entry)), None)
    rng = (min(entry, entry - d * tick * 2), max(entry, entry - d * tick * 2))
    side = "below" if d > 0 else "above"
    return Setup(name, d, entry, stop, target, trigger, label, conds,
                 invalidation=f"A close {side} {stop:g} (stop), or {('back ' + side + ' ' + label) if label else 'structure failing'} before the entry fills.",
                 entry_range=rng, next_level=nxt), None


def detect(F: pd.DataFrame, i: int, spec: ProductSpec, p: SetupParams | None = None) -> tuple[list[Setup], list[str]]:
    """Setups confirmed at the close of bar i, plus the reasons other candidates were rejected."""
    p = p or SetupParams()
    r = F.iloc[i]
    rejected: list[str] = []
    if not r["rth"] or not _ok(r["atr"]) or r["atr"] <= 0:
        return [], rejected
    bm = F.attrs.get("bar_minutes", 5)
    mfr = r["min_from_rth"]
    if p.flat_by_min_from_rth is not None and mfr + bm > p.flat_by_min_from_rth - p.no_entry_last_minutes:
        return [], ["Too close to the flat-by time for a new entry."]
    tick = float(spec.tick)
    atr = float(r["atr"])
    prev = F.iloc[i - 1] if i > 0 else None
    if i >= 3 and abs(r["c"] - F["c"].iloc[i - 3]) > p.max_run_atr * atr:
        return [], [f"Extended: price moved {abs(r['c'] - F['c'].iloc[i - 3]):g} points in 3 bars (>{p.max_run_atr} ATR). Not chasing."]
    lv = key_levels(r)
    out: list[Setup] = []
    bull, bear = r["c"] > r["o"], r["c"] < r["o"]

    def add(res):
        s, why = res
        if s:
            out.append(s)
        elif why:
            rejected.append(why)

    # A. sweep and reclaim
    for lbl in ("PDL", "ONL", "IBL", "Prev Globex L"):
        L = lv.get(lbl)
        if L is not None and r["l"] <= L - tick and r["c"] > L and bull:
            if r["c"] - L > p.max_chase_atr * atr:
                rejected.append(f"sweep_reversal: close is {r['c'] - L:g} points above {lbl}; too far to chase.")
            else:
                add(_plan(spec, "sweep_reversal", +1, r, r["l"], L, lbl, [f"Traded below {lbl} ({L:g}) and closed back above it",
                                                                          "Bullish close on the sweep bar"], p, lv))
            break
    for lbl in ("PDH", "ONH", "IBH", "Prev Globex H"):
        H = lv.get(lbl)
        if H is not None and r["h"] >= H + tick and r["c"] < H and bear:
            if H - r["c"] > p.max_chase_atr * atr:
                rejected.append(f"sweep_reversal: close is {H - r['c']:g} points below {lbl}; too far to chase.")
            else:
                add(_plan(spec, "sweep_reversal", -1, r, r["h"], H, lbl, [f"Traded above {lbl} ({H:g}) and closed back below it",
                                                                          "Bearish close on the sweep bar"], p, lv))
            break
    # B. opening-range breakout retest (first 3 hours)
    orh, orl = r.get("or_h"), r.get("or_l")
    if _ok(orh) and _ok(orl) and mfr <= 180:
        broke_up, broke_dn = bool(r.get("or_broke_up")), bool(r.get("or_broke_dn"))
        if True:
            if broke_up and r["l"] <= orh + 0.15 * atr and r["c"] > orh and bull and r["c"] - orh <= p.max_chase_atr * atr:
                add(_plan(spec, "orb_retest", +1, r, min(r["l"], orh - 0.25 * atr), orh, "ORH",
                          ["Broke above the opening range earlier", f"Pulled back to ORH ({orh:g}) and held"], p, lv))
            if broke_dn and r["h"] >= orl - 0.15 * atr and r["c"] < orl and bear and orl - r["c"] <= p.max_chase_atr * atr:
                add(_plan(spec, "orb_retest", -1, r, max(r["h"], orl + 0.25 * atr), orl, "ORL",
                          ["Broke below the opening range earlier", f"Pulled back to ORL ({orl:g}) and failed"], p, lv))
    # C. VWAP reclaim / loss with structure
    if i >= 4 and _ok(r["vwap"]):
        prior = F.iloc[i - 3:i]
        recent_bos_up = F["bos_up"].iloc[i - 2:i + 1].any()
        recent_bos_dn = F["bos_dn"].iloc[i - 2:i + 1].any()
        if (prior["c"] < prior["vwap"]).all() and r["c"] > r["vwap"] and bull and recent_bos_up and r["c"] - r["vwap"] <= p.max_chase_atr * atr:
            add(_plan(spec, "vwap_reclaim", +1, r, F["l"].iloc[i - 5:i + 1].min(), float(r["vwap"]), "VWAP",
                      ["Three closes below VWAP, then a close above", "Break of structure to the upside"], p,
                      {k: v for k, v in lv.items() if k != "VWAP"}))
        if (prior["c"] > prior["vwap"]).all() and r["c"] < r["vwap"] and bear and recent_bos_dn and r["vwap"] - r["c"] <= p.max_chase_atr * atr:
            add(_plan(spec, "vwap_reclaim", -1, r, F["h"].iloc[i - 5:i + 1].max(), float(r["vwap"]), "VWAP",
                      ["Three closes above VWAP, then a close below", "Break of structure to the downside"], p,
                      {k: v for k, v in lv.items() if k != "VWAP"}))
    # D. initial balance breakout
    ibh, ibl = r.get("ib_h"), r.get("ib_l")
    vol_ok = _ok(r["vol_avg20"]) and r["vol_avg20"] > 0 and r["v"] > 1.2 * r["vol_avg20"]
    if _ok(ibh) and _ok(ibl) and prev is not None and prev["td"] == r["td"]:
        if r["c"] > ibh and prev["c"] <= ibh and vol_ok and r["c"] - ibh <= p.max_chase_atr * atr:
            add(_plan(spec, "ib_breakout", +1, r, min(r["l"], ibh - 0.3 * atr), ibh, "IBH",
                      [f"First close above the initial balance high ({ibh:g})", f"Volume {r['v'] / r['vol_avg20']:.1f}x the recent average"], p,
                      {k: v for k, v in lv.items() if k not in ("IBH", "ORH")}))
        if r["c"] < ibl and prev["c"] >= ibl and vol_ok and ibl - r["c"] <= p.max_chase_atr * atr:
            add(_plan(spec, "ib_breakout", -1, r, max(r["h"], ibl + 0.3 * atr), ibl, "IBL",
                      [f"First close below the initial balance low ({ibl:g})", f"Volume {r['v'] / r['vol_avg20']:.1f}x the recent average"], p,
                      {k: v for k, v in lv.items() if k not in ("IBL", "ORL")}))
    # E. trend pullback into a fresh FVG
    if i >= 12:
        win = F.iloc[i - 12:i]
        if r["trend"] == 1 and win["bos_up"].any() and _ok(r["vwap"]) and r["c"] > r["vwap"] and bull:
            g = win[win["fvg_bull"]]
            if len(g):
                lo, hi = float(g["fvg_bull_lo"].iloc[-1]), float(g["fvg_bull_hi"].iloc[-1])
                touched = r["l"] <= hi and r["l"] > lo - tick and r["c"] > hi
                if touched and r["c"] - hi <= p.max_chase_atr * atr:
                    add(_plan(spec, "trend_pullback", +1, r, lo - 0.2 * atr, hi, "FVG",
                              ["Uptrend: recent break of structure up", f"Pulled back into a fair value gap ({lo:g}-{hi:g}) and held",
                               "Above session VWAP"], p, lv))
        if r["trend"] == -1 and win["bos_dn"].any() and _ok(r["vwap"]) and r["c"] < r["vwap"] and bear:
            g = win[win["fvg_bear"]]
            if len(g):
                lo, hi = float(g["fvg_bear_lo"].iloc[-1]), float(g["fvg_bear_hi"].iloc[-1])
                touched = r["h"] >= lo and r["h"] < hi + tick and r["c"] < lo
                if touched and lo - r["c"] <= p.max_chase_atr * atr:
                    add(_plan(spec, "trend_pullback", -1, r, hi + 0.2 * atr, lo, "FVG",
                              ["Downtrend: recent break of structure down", f"Pulled back into a fair value gap ({lo:g}-{hi:g}) and failed",
                               "Below session VWAP"], p, lv))
    return out, rejected


def developing(F: pd.DataFrame, i: int, spec: ProductSpec) -> list[str]:
    """Plain notes about what is forming: price near a level, ranges not complete yet."""
    r = F.iloc[i]
    notes = []
    if not _ok(r.get("atr")):
        return notes
    atr = float(r["atr"])
    for lbl, v in key_levels(r).items():
        d = r["c"] - v
        if abs(d) <= 0.3 * atr:
            notes.append(f"Price is {abs(d):g} points {'above' if d >= 0 else 'below'} {lbl} ({v:g}). Watch how it reacts: a sweep and "
                         "reclaim, a clean break, or chop.")
    if r["rth"] and not _ok(r.get("or_h")):
        notes.append("The opening range is still forming; opening-range levels aren't set yet.")
    elif r["rth"] and not _ok(r.get("ib_h")):
        notes.append("The initial balance (first hour) is still forming.")
    if not r["rth"]:
        notes.append("Outside RTH: these setups are only evaluated during regular hours.")
    return notes[:5]
