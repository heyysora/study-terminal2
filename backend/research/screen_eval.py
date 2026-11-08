"""Screen-copilot accuracy on labeled screenshots. Usage (from backend/):

    python -m research.screen_eval <folder> [<folder> ...] [--out research/out/screen_eval.json]

Each folder needs a manifest.json: a list of objects with
    file          image file name in the folder
    platform      tradingview | webull | thinkorswim | ibkr | other
    symbol        the ticker actually on screen
    interval      timeframe on screen, e.g. "5", "15", "60", "D", "5m", "1h"   (optional)
    price         the true current price at capture time                       (optional)
    page_title    the window/tab title at capture time (optional; used for the "with window title" run)
    process       e.g. chrome.exe, Webull Desktop.exe                          (optional)

Every image is analyzed twice with the app's own pipeline (app/screen/vision.py): once from pixels only,
and once with the window title the app would see on Windows. A field is scored:
    correct     matches the label
    unknown     the app said it couldn't read it (honest failure)
    WRONG       the app gave an answer and it was wrong (the failure that matters most)
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2

from app.screen.vision import analyze_image

TF_MAP = {"1": "1Min", "2": "2Min", "5": "5Min", "15": "15Min", "30": "30Min", "60": "1Hour", "240": "4Hour", "D": "1Day",
          "1m": "1Min", "5m": "5Min", "15m": "15Min", "30m": "30Min", "1h": "1Hour", "4h": "4Hour", "1d": "1Day", "1D": "1Day"}
PRICE_TOL = 0.003   # 0.3%


def truth_price(item: dict) -> float | None:
    if item.get("price") is not None:
        return float(item["price"])
    m = re.search(r"\b(\d{1,6}(?:\.\d+)?)\b", (item.get("page_title") or "").replace(",", ""))
    return float(m.group(1)) if m else None


def score(res: dict, item: dict) -> dict:
    out = {}
    if res.get("blocked"):
        return {"blocked": True}
    t = res.get("ticker")
    out["ticker"] = "unknown" if not t else "correct" if t.upper() == item["symbol"].upper() else "WRONG"
    want_tf = TF_MAP.get(str(item.get("interval"))) if item.get("interval") is not None else None
    if want_tf:
        tf = res.get("timeframe")
        out["timeframe"] = "unknown" if not tf else "correct" if tf == want_tf else "WRONG"
    tp = truth_price(item)
    if tp:
        vp = res.get("visible_price")
        out["price"] = "unknown" if vp is None else "correct" if abs(vp / tp - 1) <= PRICE_TOL else "WRONG"
        out["price_detail"] = {"read": vp, "truth": tp, "source": res.get("visible_price_source")}
    ax = res.get("price_axis")
    out["axis"] = "unknown" if not ax else "correct" if ax["max_error_pct"] <= 0.5 else "WRONG"
    out["axis_detail"] = ax
    return out


NAME_RE = re.compile(r"^(?P<platform>[a-z]+)_(?P<symbol>[A-Za-z.\-]{1,10})_(?P<interval>[0-9]+[mhMH]?|[DdWw1]D?|[0-9]+)(?:_(?P<price>[0-9]+(?:\.[0-9]+)?))?", re.I)


def manifest_for(folder: Path) -> list[dict]:
    """manifest.json if present; otherwise labels from file names like  webull_AAPL_5m_342.37.png
    (platform_SYMBOL_interval[_truePrice].png). Files that don't follow the pattern are skipped and listed."""
    m = folder / "manifest.json"
    if m.exists():
        return json.loads(m.read_text())
    out = []
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() not in (".png", ".jpg", ".jpeg"):
            continue
        g = NAME_RE.match(f.stem)
        if not g:
            print(f"skipped (name not in platform_SYMBOL_interval[_price] form): {f.name}")
            continue
        iv = g["interval"].lower()
        out.append({"file": f.name, "platform": g["platform"].lower(), "symbol": g["symbol"].upper(),
                    "interval": "D" if iv in ("d", "1d") else iv, "price": float(g["price"]) if g["price"] else None})
    return out


def run(folders: list[Path]) -> dict:
    rows = []
    for folder in folders:
        manifest = manifest_for(folder)
        for item in manifest:
            img = cv2.imread(str(folder / item["file"]))
            if img is None:
                rows.append({"file": item["file"], "error": "unreadable image"})
                continue
            for mode in ("pixels_only", "with_title"):
                title = (item.get("page_title", "") + " - Google Chrome") if mode == "with_title" and item.get("page_title") else ""
                if mode == "with_title" and not title:
                    continue
                t0 = time.time()
                res = analyze_image(img, title=title, process=item.get("process", "chrome.exe") if title else None)
                rows.append({"file": item["file"], "folder": folder.name, "platform": item.get("platform", "other"),
                             "theme": item.get("theme"), "size": f"{img.shape[1]}x{img.shape[0]}", "mode": mode,
                             "seconds": round(time.time() - t0, 2), "score": score(res, item),
                             "read": {k: res.get(k) for k in ("ticker", "ticker_confidence", "ticker_source", "timeframe", "visible_price",
                                                              "visible_price_source", "could_not_recognize", "indicators_visible")},
                             "label": {k: item.get(k) for k in ("symbol", "interval", "price", "page_title")}})
    summary: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for r in rows:
        if "score" not in r or r["score"].get("blocked"):
            continue
        key = f"{r['platform']} / {r['mode']}"
        for field in ("ticker", "timeframe", "price", "axis"):
            if field in r["score"]:
                summary[key][field][r["score"][field]] += 1
    return {"rows": rows, "summary": json.loads(json.dumps(summary)),
            "seconds_per_frame": round(sum(r.get("seconds", 0) for r in rows) / max(1, len(rows)), 2)}


def markdown(rep: dict) -> str:
    lines = ["| Platform / mode | Field | Correct | Unknown (honest) | WRONG |", "|---|---|---|---|---|"]
    for key, fields in rep["summary"].items():
        for f, c in fields.items():
            n = sum(c.values())
            lines.append(f"| {key} | {f} | {c.get('correct', 0)}/{n} | {c.get('unknown', 0)} | {c.get('WRONG', 0)} |")
    return "\n".join(lines)


if __name__ == "__main__":
    args = sys.argv[1:]
    out = Path("research/out/screen_eval.json")
    if "--out" in args:
        i = args.index("--out")
        out = Path(args[i + 1])
        args = args[:i] + args[i + 2:]
    rep = run([Path(a) for a in args])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1, default=str))
    print(markdown(rep))
    print("seconds/frame:", rep["seconds_per_frame"])
    for r in rep["rows"]:
        s = r.get("score", {})
        bad = [k for k, v in s.items() if v == "WRONG"]
        if bad:
            print("WRONG", r["file"], r["mode"], bad, r["read"], r["label"])
