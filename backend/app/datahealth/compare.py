"""Comparing the same instrument across independent sources.

Sources are never averaged. Each pair is compared; if any pair differs by more than the tolerance the result is "questionable" and
every source's own number is kept and shown. The tolerance allows for what honestly differs between venues: the bid/ask spread,
slightly different times, different pools.
"""
from __future__ import annotations

import math
from itertools import combinations


def _ok(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v) and v > 0


def tolerance(base: float, spreads: list[float | None] | None = None, age_seconds: float = 0.0, per_minute: float = 0.0) -> float:
    """base: what venues normally differ by. Widened by 3x the widest quoted spread and by how far apart in time the quotes are."""
    widest = max((s for s in (spreads or []) if s and s > 0), default=0.0)
    return base + 3 * widest + per_minute * (age_seconds / 60.0)


def compare_prices(quotes: dict[str, float | None], tol: float, what: str = "price") -> dict:
    """quotes: source name -> price (None = that source didn't answer). Returns verdict agree / questionable / single / none."""
    have = {k: float(v) for k, v in quotes.items() if _ok(v)}
    silent = sorted(k for k in quotes if k not in have)
    if not have:
        return {"verdict": "none", "ok": None, "independent": False, "values": {}, "silent": silent,
                "detail": f"No source gave a usable {what}."}
    if len(have) == 1:
        (name, v), = have.items()
        return {"verdict": "single", "ok": None, "independent": False, "values": have, "silent": silent,
                "detail": f"Only {name} gave a {what} ({v:g}), so there's nothing independent to check it against."}
    worst, pair = 0.0, None
    for (a, x), (b, y) in combinations(have.items(), 2):
        d = abs(x - y) / min(x, y)
        if d >= worst:
            worst, pair = d, (a, b)
    agree = worst <= tol
    return {"verdict": "agree" if agree else "questionable", "ok": agree, "independent": True, "values": have, "silent": silent,
            "max_diff_pct": round(worst * 100, 4), "tolerance_pct": round(tol * 100, 4), "widest_pair": list(pair) if pair else None,
            "detail": (f"{len(have)} independent sources agree on the {what} within {worst:.2%} (allowed {tol:.2%})." if agree else
                       f"{pair[0]} and {pair[1]} disagree on the {what} by {worst:.2%} (allowed {tol:.2%}). "
                       f"Neither is assumed right; the {what} is treated as questionable.")}


def within_range(value: float | None, low: float | None, high: float | None, tol: float) -> dict:
    """Was `value` inside [low, high] (a reference candle's range), allowing `tol` either side?"""
    if not (_ok(value) and _ok(low) and _ok(high)):
        return {"ok": None, "detail": "No reference range to compare with.", "diff_pct": None}
    if low * (1 - tol) <= value <= high * (1 + tol):
        return {"ok": True, "diff_pct": 0.0, "detail": f"{value:g} is inside the reference range {low:g}-{high:g} (allowing {tol:.2%})."}
    d = (low - value) / low if value < low else (value - high) / high
    return {"ok": False, "diff_pct": round(d * 100, 4),
            "detail": f"{value:g} is {d:.2%} outside the reference range {low:g}-{high:g} (allowed {tol:.2%})."}
