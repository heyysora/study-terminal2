"""Does Study Terminal work on THIS PC, with THIS Edge window and THIS TopstepX chart?

Run:  .\\scripts\\acceptance-test.ps1          (or: StudyTerminal.exe --acceptance)

Everything else -- unit tests, CI, the packaged checks -- answers a different question. They prove the code is
right and the build is complete. None of them can tell you whether the chart on your screen is being read, because
none of them has ever seen it. This has.

It walks the whole pipeline in order and stops being optimistic at the first stage that fails:

   1  which Study Terminal is installed, and where
   2  the runtime and library versions it is actually using
   3  the screen-text reader, started and made to read known text
   4  every other part of the build, each doing a small piece of real work
   5  the local engine answering
   6  a chart profile saved and read back
   7  your Microsoft Edge TopstepX window, found among the open windows
   8  a capture of that window
   9  the text on that capture, read
  10  the market, the timeframe and the price, extracted and checked against each other
  11  capture timestamps and how old the data is
  12  how long each stage took, over repeated cycles (p50/p95/p99)

It reads and it measures. It never clicks anything, types anything, or touches a TopstepX control.

The report is written next to your logs as acceptance-<timestamp>.json and .md, with the captured chart saved
alongside it as a .png so you can see exactly what the app saw.
"""
from __future__ import annotations

import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if (ROOT / "backend").is_dir():
    sys.path.insert(0, str(ROOT / "backend"))

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIPPED"
steps: list[dict] = []
_t0 = time.monotonic()


def rec(n: int, name: str, status: str, detail: str = "", data: dict | None = None) -> str:
    steps.append({"step": n, "name": name, "status": status, "detail": detail, "data": data or {},
                  "at": datetime.now(timezone.utc).isoformat()})
    mark = {"PASS": "ok  ", "FAIL": "FAIL", "WARN": "warn", "SKIPPED": "--  "}[status]
    print(f"  [{mark}] {n:>2}. {name}{': ' + detail if detail else ''}", flush=True)
    return status


def failed() -> bool:
    return any(s["status"] == FAIL for s in steps)


def data_dir() -> Path:
    import os
    d = os.environ.get("STUDY_TERMINAL_DATA_DIR")
    if d:
        return Path(d)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "StudyTerminal"


def api_base() -> str:
    import os
    return f"http://127.0.0.1:{os.environ.get('PORT', '8765')}/api"


def quantiles(xs: list[float]) -> dict:
    if not xs:
        return {}
    s = sorted(xs)
    def q(p):
        return round(s[min(len(s) - 1, int(round(p * (len(s) - 1))))], 1)
    return {"n": len(s), "p50": q(0.50), "p95": q(0.95), "p99": q(0.99),
            "min": round(s[0], 1), "max": round(s[-1], 1), "mean": round(statistics.fmean(s), 1)}


# ---------------------------------------------------------------- the steps

def step_1_version() -> None:
    try:
        from app.config import BUILD, VERSION
        exe = sys.executable if not getattr(sys, "frozen", False) else sys.executable
        rec(1, "Installed version", PASS, f"Study Terminal {VERSION} (build {BUILD})",
            {"version": VERSION, "build": BUILD, "executable": exe, "frozen": bool(getattr(sys, "frozen", False))})
    except Exception as e:  # noqa: BLE001
        rec(1, "Installed version", FAIL, f"{type(e).__name__}: {e}")


def step_2_runtime() -> None:
    info = {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
            "frozen": bool(getattr(sys, "frozen", False)), "cpu_count": __import__("os").cpu_count()}
    try:
        from app.screen import ocr_health
        info.update(ocr_health.check(deep=False).get("versions", {}))
    except Exception as e:  # noqa: BLE001
        rec(2, "Runtime and library versions", FAIL, f"{type(e).__name__}: {e}", info)
        return
    rec(2, "Runtime and library versions", PASS,
        f"Python {info['python']}, OCR {info.get('rapidocr_onnxruntime', '?')}, {info['cpu_count']} CPU cores", info)


def step_3_ocr() -> None:
    try:
        from app.screen import ocr_health
        r = ocr_health.check(deep=True)
        rec(3, "Screen-text reader", PASS if r["ok"] else FAIL,
            r["headline"] + (" " + r["advice"] if r.get("advice") else ""), r)
    except Exception as e:  # noqa: BLE001
        rec(3, "Screen-text reader", FAIL, f"{type(e).__name__}: {e}")


def step_4_subsystems() -> None:
    try:
        from app import diagnostics
        r = diagnostics.subsystems()
        bad = ", ".join(c["name"] for c in r["checks"] if c["status"] == "fail")
        rec(4, "Every part of this build", PASS if r["ok"] else FAIL,
            r["headline"] + (f" Failing: {bad}" if bad else ""), r)
    except Exception as e:  # noqa: BLE001
        rec(4, "Every part of this build", FAIL, f"{type(e).__name__}: {e}")


def step_5_backend() -> dict | None:
    try:
        import httpx
        r = httpx.get(f"{api_base()}/health", timeout=10, headers={"X-Study-Terminal": "1"})
        if r.status_code != 200:
            rec(5, "Local engine answering", FAIL, f"HTTP {r.status_code} from /api/health")
            return None
        h = r.json()
        rec(5, "Local engine answering", PASS,
            f"version {h.get('version')}, database {'ok' if h.get('database_ok') else 'NOT ok'}, "
            f"execution: {h.get('execution')}", h)
        return h
    except Exception as e:  # noqa: BLE001
        rec(5, "Local engine answering", FAIL,
            f"{type(e).__name__}: {e}. Start Study Terminal and leave it running, then run this again.")
        return None


def step_6_profile(alive: bool) -> None:
    if not alive:
        rec(6, "Chart profile saves and reloads", SKIP, "the engine isn't answering")
        return
    try:
        import httpx
        hdr = {"X-Study-Terminal": "1"}
        before = httpx.get(f"{api_base()}/visual/profiles", timeout=10, headers=hdr).json()
        name = f"acceptance check {int(time.time())}"
        body = {"name": name, "window_title_contains": "TopstepX", "root": "auto", "timeframe": "5Min",
                "region": [0, 0, 0, 0], "capture_seconds": 2.0}
        made = httpx.post(f"{api_base()}/visual/profiles", json=body, timeout=20, headers=hdr)
        if made.status_code >= 400:
            rec(6, "Chart profile saves and reloads", FAIL, f"saving answered HTTP {made.status_code}: {made.text[:160]}")
            return
        pid = made.json().get("id")
        back = [p for p in httpx.get(f"{api_base()}/visual/profiles", timeout=10, headers=hdr).json() if p.get("id") == pid]
        ok = bool(back) and back[0].get("timeframe") == "5Min"
        httpx.delete(f"{api_base()}/visual/profiles/{pid}", timeout=10, headers=hdr)
        after = httpx.get(f"{api_base()}/visual/profiles", timeout=10, headers=hdr).json()
        kept = len(after) == len(before)
        rec(6, "Chart profile saves and reloads", PASS if (ok and kept) else FAIL,
            "saved, read back with the same settings, removed again; your own charts untouched" if ok and kept
            else f"saved={bool(back)} same_settings={ok} your_profiles_preserved={kept}")
    except Exception as e:  # noqa: BLE001
        rec(6, "Chart profile saves and reloads", FAIL, f"{type(e).__name__}: {e}")


def step_7_window() -> dict | None:
    try:
        from app.screen.capture import list_targets
        from app.screen.platforms import topstepx_title
        from app.screen.vision import is_browser
        wins = [t for t in list_targets() if t.get("kind") == "window"]
        hits = []
        for t in wins:
            title, proc = t.get("title") or "", (t.get("process") or "")
            parsed = topstepx_title(title)
            if ("topstep" in title.lower() or parsed) and is_browser(proc):
                hits.append({"id": t["id"], "title": title, "process": proc, "parsed": parsed})
        if not hits:
            rec(7, "Your Edge TopstepX window", FAIL,
                f"not found among {len(wins)} open windows. Open your chart in Microsoft Edge, keep that tab in "
                "front, and don't minimise the window.",
                {"window_titles": [w.get("title") for w in wins][:25]})
            return None
        best = hits[0]
        p = best["parsed"]
        rec(7, "Your Edge TopstepX window", PASS,
            f"{best['process']}: {best['title'][:80]}" + (f"  (contract {p['contract']}, price {p['price']})" if p else ""),
            {"matches": hits})
        return best
    except Exception as e:  # noqa: BLE001
        rec(7, "Your Edge TopstepX window", FAIL, f"{type(e).__name__}: {e}")
        return None


def step_8_capture(win: dict | None, out_dir: Path) -> tuple[object, dict]:
    if not win:
        rec(8, "Capture of that window", SKIP, "no window to capture")
        return None, {}
    try:
        from app.screen import capture as cap
        from app.screen.capture_sources import CaptureManager
        mgr = CaptureManager()
        a = time.perf_counter()
        res = mgr.capture(int(win["id"]), "auto", lambda h: False)
        ms = (time.perf_counter() - a) * 1000
        if res.frame is None:
            why = "; ".join(f"{t['method']}: {t['error']}" for t in (res.tried or []) if t.get("error"))
            rec(8, "Capture of that window", FAIL, f"nothing captured ({why or res.method})", {"tried": res.tried})
            return None, {}
        h, w = res.frame.shape[:2]
        png = out_dir / "acceptance-capture.png"
        try:
            import cv2
            cv2.imwrite(str(png), res.frame)
        except Exception:  # noqa: BLE001
            png = None
        rec(8, "Capture of that window", PASS, f"{w}x{h} via {res.method} in {ms:.0f} ms"
            + (f"; saved as {png.name}" if png else ""),
            {"width": w, "height": h, "method": res.method, "ms": round(ms, 1),
             "frame_age_seconds": res.frame_age, "image": str(png) if png else None})
        _ = cap
        return res.frame, {"method": res.method, "ms": ms}
    except Exception as e:  # noqa: BLE001
        rec(8, "Capture of that window", FAIL, f"{type(e).__name__}: {e}")
        return None, {}


def step_9_10_11_read(frame, win: dict | None) -> dict:
    """Read the capture, then judge what came out of it. These three steps share one read."""
    if frame is None:
        rec(9, "Text read from your chart", SKIP, "nothing was captured")
        rec(10, "Market, timeframe and price", SKIP, "nothing was captured")
        rec(11, "Timestamps and freshness", SKIP, "nothing was captured")
        return {}
    try:
        from app.screen.chart_profile import ChartProfile
        from app.screen.chart_reader import read_chart
        h, w = frame.shape[:2]
        prof = ChartProfile(id="acceptance", name="acceptance", root="auto", timeframe="auto",
                            window_title_contains="TopstepX", region=[0, 0, w, h])
        captured_at = datetime.now(timezone.utc)
        a = time.perf_counter()
        r = read_chart(frame, prof, captured_at, title=(win or {}).get("title", ""))
        ms = (time.perf_counter() - a) * 1000
    except Exception as e:  # noqa: BLE001
        rec(9, "Text read from your chart", FAIL, f"{type(e).__name__}: {e}")
        rec(10, "Market, timeframe and price", SKIP, "the read failed")
        rec(11, "Timestamps and freshness", SKIP, "the read failed")
        return {}

    words = len(getattr(r, "tokens", []) or [])
    rec(9, "Text read from your chart", PASS if r.ok or r.price.value is not None else FAIL,
        f"read in {ms:.0f} ms; {len(r.candles)} candles found" + (f"; {words} words" if words else ""),
        {"ms": round(ms, 1), "ok": r.ok, "problems": r.problems[:6]})

    # 10 -- what was actually extracted, and does it agree with the window title?
    tab = (win or {}).get("parsed") or {}
    bits, bad = [], []
    bits.append(f"market {r.instrument.value or '?'} ({r.instrument.source})")
    bits.append(f"timeframe {r.timeframe.value or '?'} ({r.timeframe.source})")
    bits.append(f"price {r.price.value if r.price.value is not None else '?'} ({r.price.source})")
    if r.instrument.value is None:
        bad.append("the market could not be read")
    if r.timeframe.value is None:
        bad.append("the timeframe could not be read (set it in Set up a chart, or include the chart's label in the region)")
    if r.price.value is None:
        bad.append("the price could not be read")
    if tab and r.instrument.value and tab.get("root") and r.instrument.value != tab["root"]:
        bad.append(f"the chart says {r.instrument.value} but the Edge tab says {tab['root']}")
    if tab and r.price.value is not None and tab.get("price"):
        gap = abs(float(r.price.value) - float(tab["price"]))
        rel = gap / max(1.0, float(tab["price"]))
        bits.append(f"tab price {tab['price']} (difference {gap:.2f})")
        if rel > 0.01:
            bad.append(f"the price read from the chart is {gap:.2f} away from the price in the Edge tab title")
    rec(10, "Market, timeframe and price", FAIL if bad else PASS, "; ".join(bits) + ("  --  " + "; ".join(bad) if bad else ""),
        {"instrument": r.instrument.value, "timeframe": r.timeframe.value, "price": r.price.value,
         "confidence": round(r.confidence, 2), "tab": tab, "problems": bad})

    # 11 -- is what we just read current?
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(r.captured_at)).total_seconds()
    ok = age < 10
    rec(11, "Timestamps and freshness", PASS if ok else WARN,
        f"captured {age:.1f} s ago; the reading carries its own capture time"
        + ("" if ok else " -- this machine took a long time to get through the read"),
        {"captured_at": r.captured_at, "age_seconds": round(age, 2)})
    return {"reading": r, "profile": prof, "frame": frame, "title": (win or {}).get("title", "")}


def step_12_latency(ctx: dict, cycles: int = 12) -> None:
    """Where the time goes, over repeated cycles on your real chart."""
    if not ctx:
        rec(12, "Stage timings", SKIP, "there was nothing to time")
        return
    try:
        import cv2

        from app.screen.chart_reader import read_chart
        from app.screen.token_cache import TokenCache
        from app.screen.vision import ocr
        frame, prof, title = ctx["frame"], ctx["profile"], ctx["title"]
        grey_ms, cached_ms, ocr_passes = [], [], 0
        tc = TokenCache(ocr)
        a = time.perf_counter()
        tc.tokens(frame, ctx["reading"].signature)
        first_ms = (time.perf_counter() - a) * 1000
        for _ in range(cycles):
            a = time.perf_counter()
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            grey_ms.append((time.perf_counter() - a) * 1000)
            a = time.perf_counter()
            toks, meta = tc.tokens(frame, ctx["reading"].signature)
            read_chart(frame, prof, datetime.now(timezone.utc), tokens=toks, title=title)
            cached_ms.append((time.perf_counter() - a) * 1000)
            ocr_passes += meta["ocr_passes"]
        a = time.perf_counter()
        read_chart(frame, prof, datetime.now(timezone.utc), title=title)
        full_ms = (time.perf_counter() - a) * 1000
        q = quantiles(cached_ms)
        rec(12, "Stage timings", PASS,
            f"full read with no cache {full_ms:.0f} ms; first read {first_ms:.0f} ms; "
            f"repeat reads p50 {q['p50']} ms / p95 {q['p95']} ms / max {q['max']} ms"
            + (f"; {full_ms / max(q['p50'], 0.1):.0f}x faster once warm" if q.get("p50") else ""),
            {"full_read_no_cache_ms": round(full_ms, 1), "first_read_ms": round(first_ms, 1),
             "repeat_read_ms": q, "change_detect_ms": quantiles(grey_ms),
             "ocr_passes_over_cycles": ocr_passes, "cycles": cycles,
             "note": "same frame each cycle: this is the quiet-market floor, not a moving market"})
    except Exception as e:  # noqa: BLE001
        rec(12, "Stage timings", FAIL, f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------- report

def write_report(out_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {k: sum(1 for s in steps if s["status"] == k) for k in (PASS, FAIL, WARN, SKIP)}
    verdict = ("THE PIPELINE WORKS ON THIS PC" if counts[FAIL] == 0 and counts[SKIP] == 0 else
               "SOMETHING IS BROKEN" if counts[FAIL] else "INCOMPLETE -- some stages could not be tested")
    doc = {"what": "Study Terminal real-PC acceptance test", "when": datetime.now(timezone.utc).isoformat(),
           "machine": platform.platform(), "verdict": verdict, "counts": counts,
           "took_seconds": round(time.monotonic() - _t0, 1), "steps": steps}
    (out_dir / f"acceptance-{stamp}.json").write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    md = [f"# Study Terminal acceptance test on this PC ({stamp})", "",
          f"**{verdict}** -- {counts[PASS]} passed, {counts[FAIL]} failed, {counts[WARN]} warnings, "
          f"{counts[SKIP]} skipped, in {doc['took_seconds']} s.", "",
          f"`{platform.platform()}`", "", "| # | Stage | Result | Detail |", "|---|---|---|---|"]
    for s in steps:
        md.append(f"| {s['step']} | {s['name']} | **{s['status']}** | {s['detail'].replace('|', '/')[:300]} |")
    md += ["", "## What this does and does not prove", "",
           "It proves what happened on this machine, with this chart, at this moment. It does not prove the next",
           "hour will go the same way, and it says nothing at all about whether any strategy makes money.", ""]
    path = out_dir / f"acceptance-{stamp}.md"
    path.write_text("\n".join(md), encoding="utf-8")
    return path


def main() -> int:
    print("Study Terminal -- acceptance test on this PC")
    print("Reads your chart and measures. Never clicks or types anything in TopstepX.\n", flush=True)
    out = data_dir() / "logs"
    out.mkdir(parents=True, exist_ok=True)
    step_1_version()
    step_2_runtime()
    step_3_ocr()
    step_4_subsystems()
    alive = step_5_backend()
    step_6_profile(bool(alive))
    win = step_7_window()
    frame, _ = step_8_capture(win, out)
    ctx = step_9_10_11_read(frame, win)
    step_12_latency(ctx)
    path = write_report(out)
    bad = sum(1 for s in steps if s["status"] == FAIL)
    print(f"\n{'Something is broken.' if bad else 'Every stage that could run, passed.'}")
    print(f"Report: {path}")
    print(f"        {path.with_suffix('.json')}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
