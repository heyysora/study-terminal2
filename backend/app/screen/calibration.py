"""Screen-reading calibration: measure how well the screen copilot reads YOUR charts.

You upload a screenshot of your own platform (TopstepX, TradingView, ...) and type what is actually on it: contract/ticker,
timeframe and the last price. The copilot reads the image with the same code the live monitor uses and each field is scored.

Privacy:
- Nothing is stored unless you tick "keep this screenshot". Without it, the image is analyzed in memory and dropped; only the
  labels you typed and the per-field scores are kept so the accuracy report can add up (you can switch that off too).
- Kept screenshots live only in <data dir>/calibration on this computer and can be deleted one by one or all at once.
- Login/authentication screens are refused by the same detector the live monitor uses; nothing from them is kept.

Honesty rules:
- Accuracy is reported per platform and per field with the sample size and a 95% Wilson interval, plus the failure cases.
- Samples marked "synthetic" (generated test charts) are scored but never counted in the accuracy figures, because a reader that
  works on clean generated charts can still fail on a real platform.
- Under 20 real samples for a platform/field, the report says the number is not yet meaningful.
"""
from __future__ import annotations

import json
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

FIELDS = ("ticker", "timeframe", "price", "price_axis", "last_candle", "indicators")
INDICATOR_LABELS = {"vwap": "VWAP", "ema9": "EMA 9", "ema20": "EMA 20", "ema50": "EMA 50", "ema200": "EMA 200"}
MIN_SAMPLES = 20
_TF_ALIASES = {"1": "1Min", "1m": "1Min", "1min": "1Min", "5": "5Min", "5m": "5Min", "5min": "5Min", "15": "15Min", "15m": "15Min",
               "15min": "15Min", "30m": "30Min", "30min": "30Min", "1h": "1Hour", "60": "1Hour", "1hour": "1Hour", "60m": "1Hour",
               "4h": "4Hour", "1d": "1Day", "d": "1Day", "1day": "1Day", "day": "1Day", "2m": "2Min", "2min": "2Min", "3m": "3Min",
               "3min": "3Min", "10m": "10Min", "10min": "10Min"}


def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * max(0.0, c - h), 1), round(100 * min(1.0, c + h), 1)]


def norm_tf(s: str | None) -> str | None:
    if not s:
        return None
    k = re.sub(r"\s+", "", str(s)).lower()
    return _TF_ALIASES.get(k, str(s))


def norm_ticker(s: str | None) -> str | None:
    if not s:
        return None
    t = re.sub(r"[^A-Z0-9]", "", str(s).upper().split(":")[-1])
    return t or None


def _ticker_match(read: str | None, truth: str, futures_obs: dict | None) -> bool:
    """A futures root on screen (e.g. 'MNQ') matches a labelled contract ('MNQZ26') only if the label is that root's contract;
    a different root never matches."""
    r, t = norm_ticker(read), norm_ticker(truth)
    if not r or not t:
        return False
    if r == t:
        return True
    root = (futures_obs or {}).get("root")
    roots = {x for x in (r, norm_ticker(root)) if x}
    return any(t.startswith(x) and re.fullmatch(r"[FGHJKMNQUVXZ]\d{1,2}", t[len(x):] or "-") for x in roots)


def score(obs: dict, labels: dict, tick_size: float | None = None) -> dict:
    """Compare one observation to the labels you typed. Fields you leave blank aren't scored."""
    out: dict = {}
    if obs.get("blocked"):
        return {"blocked": True, "reason": obs.get("reason")}
    if labels.get("ticker"):
        ok = _ticker_match(obs.get("ticker"), labels["ticker"], obs.get("futures"))
        out["ticker"] = {"ok": ok, "read": obs.get("ticker"), "truth": labels["ticker"], "confidence": obs.get("ticker_confidence"),
                         "source": obs.get("ticker_source")}
    if labels.get("timeframe"):
        r, t = norm_tf(obs.get("timeframe")), norm_tf(labels["timeframe"])
        out["timeframe"] = {"ok": bool(r) and r == t, "read": obs.get("timeframe"), "truth": labels["timeframe"]}
    if labels.get("price") not in (None, ""):
        truth = float(labels["price"])
        read = obs.get("visible_price")
        tol_ticks = float(labels.get("tolerance_ticks") or 2)
        tol = tol_ticks * tick_size if tick_size else max(abs(truth) * 0.0005, 0.01)
        out["price"] = {"ok": read is not None and abs(float(read) - truth) <= tol + 1e-9, "read": read, "truth": truth,
                        "error": round(float(read) - truth, 6) if read is not None else None, "tolerance": round(tol, 6),
                        "source": obs.get("visible_price_source")}
    ax = obs.get("price_axis")
    if labels.get("axis_visible", True):
        out["price_axis"] = {"ok": bool(ax) and (ax.get("max_error_pct") or 0) <= 0.2, "read": ax}
    return out


def visual_observation(reading: dict) -> dict:
    """A Visual Market Monitor reading in the shape score() expects, so both readers are measured the same way."""
    ax = reading.get("axis") or {}
    return {"blocked": False, "ticker": reading["instrument"]["value"], "ticker_confidence": reading["instrument"]["confidence"],
            "ticker_source": reading["instrument"]["source"], "futures": {"root": reading["instrument"]["value"]},
            "timeframe": reading["timeframe"]["value"], "visible_price": reading["price"]["value"],
            "visible_price_source": reading["price"]["source"],
            "price_axis": {"points": ax.get("labels"), "max_error_pct": ax.get("max_residual_pct", 0)} if ax else None,
            "platform": "topstepx-visual", "candles": reading.get("candles", [])[-1:]}


def score_last_candle(obs: dict, labels: dict, tick_size: float | None) -> dict | None:
    """Compare the newest COMPLETED candle you typed (open/high/low/close, any subset) with what the reader estimated."""
    want = {k: labels.get(f"last_{k}") for k in ("open", "high", "low", "close")}
    want = {k: float(v) for k, v in want.items() if v not in (None, "")}
    cands = obs.get("all_candles") or []
    if not want or len(cands) < 2:
        return None
    c = cands[-2]                                          # the right-most candle is still forming
    tol = float(labels.get("tolerance_ticks") or 2) * (tick_size or 0.25)
    errs = {k: (None if c.get(k) is None else round(float(c[k]) - v, 6)) for k, v in want.items()}
    ok = all(e is not None and abs(e) <= tol + 1e-9 for e in errs.values())
    return {"ok": ok, "read": {k: c.get(k) for k in want}, "truth": want, "error": errs, "tolerance": tol}


def score_indicators(reading: dict, labels: dict, tick_size: float | None) -> dict | None:
    """Indicator values you typed (as TopstepX shows them for the newest candle) vs the line read from the chart."""
    want = {name: float(labels[k]) for k, name in INDICATOR_LABELS.items() if labels.get(k) not in (None, "")}
    if not want:
        return None
    tol = 2 * float(labels.get("tolerance_ticks") or 2) * (tick_size or 0.25)
    inds = reading.get("indicators") or {}
    read = {n: (inds.get(n) or {}).get("last") for n in want}
    errs = {n: (None if read[n] is None else round(float(read[n]) - v, 6)) for n, v in want.items()}
    ok = all(e is not None and abs(e) <= tol + 1e-9 for e in errs.values())
    return {"ok": ok, "read": read, "truth": want, "error": errs, "tolerance": tol}


class CalibrationStore:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / "calibration"
        self.log = self.dir / "results.jsonl"

    def _rows(self) -> list[dict]:
        if not self.log.exists():
            return []
        rows = []
        for line in self.log.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _write(self, rows: list[dict]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows), encoding="utf-8")

    def add(self, platform: str, labels: dict, obs: dict, result: dict, png: bytes | None, keep_image: bool, keep_result: bool) -> dict:
        sid = uuid.uuid4().hex[:12]
        row = {"id": sid, "at": datetime.now(timezone.utc).isoformat(), "platform": platform,
               "synthetic": bool(labels.get("synthetic")), "labels": {k: v for k, v in labels.items() if k != "synthetic"},
               "result": result, "image_kept": bool(keep_image and png and not result.get("blocked")),
               "observation": {k: obs.get(k) for k in ("ticker", "ticker_confidence", "timeframe", "visible_price", "price_axis", "platform")}}
        if row["image_kept"]:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / f"{sid}.png").write_bytes(png)
        if keep_result and not result.get("blocked"):
            self._write(self._rows() + [row])
        return row

    def samples(self) -> list[dict]:
        return self._rows()[::-1]

    def image(self, sid: str) -> bytes | None:
        if not re.fullmatch(r"[0-9a-f]{12}", sid):
            return None
        p = self.dir / f"{sid}.png"
        return p.read_bytes() if p.exists() else None

    def delete(self, sid: str | None = None) -> int:
        """Delete one sample (image + result) or, with sid=None, everything."""
        rows = self._rows()
        keep = [] if sid is None else [r for r in rows if r["id"] != sid]
        gone = [r for r in rows if r not in keep]
        for r in gone:
            (self.dir / f"{r['id']}.png").unlink(missing_ok=True)
        if sid is None and self.dir.exists():
            for p in self.dir.glob("*.png"):
                p.unlink(missing_ok=True)
        self._write(keep)
        return len(gone)

    def replace_result(self, sid: str, result: dict, obs: dict) -> None:
        rows = self._rows()
        for r in rows:
            if r["id"] == sid:
                r["result"], r["rescored_at"] = result, datetime.now(timezone.utc).isoformat()
                r["observation"] = {k: obs.get(k) for k in ("ticker", "ticker_confidence", "timeframe", "visible_price", "price_axis", "platform")}
        self._write(rows)

    def report(self) -> dict:
        rows = self._rows()
        real = [r for r in rows if not r.get("synthetic")]
        synth = [r for r in rows if r.get("synthetic")]
        plats: dict = {}
        for r in real:
            p = plats.setdefault(r["platform"], {f: {"n": 0, "correct": 0, "conf_ok": [], "conf_bad": [], "failures": []} for f in FIELDS})
            for f in FIELDS:
                res = (r.get("result") or {}).get(f)
                if not res:
                    continue
                cell = p[f]
                cell["n"] += 1
                cell["correct"] += bool(res["ok"])
                if f == "ticker" and res.get("confidence") is not None:
                    (cell["conf_ok"] if res["ok"] else cell["conf_bad"]).append(res["confidence"])
                if not res["ok"] and len(cell["failures"]) < 10:
                    cell["failures"].append({"sample": r["id"], "read": res.get("read"), "truth": res.get("truth"), "at": r["at"]})
        out = {}
        for plat, fields in plats.items():
            out[plat] = {}
            for f, c in fields.items():
                n = c["n"]
                acc = round(100 * c["correct"] / n, 1) if n else None
                out[plat][f] = {"samples": n, "correct": c["correct"], "accuracy_pct": acc, "ci95": wilson(c["correct"], n),
                                "meaningful": n >= MIN_SAMPLES,
                                "note": None if n >= MIN_SAMPLES else f"Only {n} real sample(s); at least {MIN_SAMPLES} are needed before this number means much.",
                                "failures": c["failures"]}
                if f == "ticker":
                    avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None  # noqa: E731
                    out[plat][f]["avg_confidence_when_right"] = avg(c["conf_ok"])
                    out[plat][f]["avg_confidence_when_wrong"] = avg(c["conf_bad"])
        return {"platforms": out, "real_samples": len(real), "synthetic_samples": len(synth),
                "synthetic_note": "Synthetic (generated) charts are scored for development but never counted in these accuracy figures.",
                "images_kept": sum(1 for r in rows if r.get("image_kept")),
                "generated_at": datetime.now(timezone.utc).isoformat()}
