"""Does Study Terminal work on THIS computer, with THIS browser, on THIS chart?

Everything else that tests this app runs either on a build machine or against pictures of a chart. Neither can
answer the only question that matters to the person using it: does the thing in front of me read my chart right now?
So this is the acceptance test, and it runs on their PC, against their Edge window, against their TopstepX session.

It is built to be unable to flatter itself:

* A stage passes only on evidence. "Found the window" means a window handle and its title. "Read the chart" means a
  price, a market and a timeframe came out of the pixels, and they survived the same checks a trade idea must pass.
  There is no pass for "no error was raised".
* Nothing is inferred from anything else. The reader working does not imply the window was found; each stage is
  asked separately and reports separately.
* A stage that cannot run says BLOCKED and why -- never PASS, never FAIL. The market being shut is not a defect.
* It never touches TopstepX. It reads pixels. It never clicks, types, or sends anything to the platform.
* The report records what was actually observed -- the price read, the window title, the timings -- so a claim in it
  can be checked against the screen rather than believed.
"""
from __future__ import annotations

import json
import platform
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PASS, FAIL, BLOCKED, INFO = "PASS", "FAIL", "BLOCKED", "INFO"


@dataclass
class Stage:
    id: str
    name: str
    status: str
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    ms: int = 0

    def as_dict(self) -> dict:
        d = {"id": self.id, "name": self.name, "status": self.status, "detail": self.detail, "ms": self.ms}
        if self.evidence:
            d["evidence"] = self.evidence
        return d


class Acceptance:
    def __init__(self, out_dir: Path | None = None) -> None:
        self.stages: list[Stage] = []
        self.started = datetime.now(timezone.utc)
        self.out_dir = out_dir
        self.images: list[str] = []

    # ---------------------------------------------------------------- helpers

    def add(self, sid: str, name: str, status: str, detail: str = "", evidence: dict | None = None, ms: int = 0) -> Stage:
        st = Stage(sid, name, status, detail, evidence or {}, ms)
        self.stages.append(st)
        line = f"[{status:7}] {name}" + (f": {detail}" if detail else "")
        print(line, flush=True)
        return st

    def _run(self, sid: str, name: str, fn) -> Stage:
        """Run one stage. An exception is a FAIL carrying the real exception, never a crash of the whole test."""
        t0 = time.perf_counter()
        try:
            status, detail, evidence = fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            frames = [f for f in traceback.extract_tb(e.__traceback__) if "app" in Path(f.filename).parts]
            spot = f" ({Path(frames[-1].filename).name}:{frames[-1].lineno})" if frames else ""
            msg = str(e).strip().splitlines()[0][:200] if str(e).strip() else ""
            return self.add(sid, name, FAIL, f"{type(e).__name__}{': ' + msg if msg else ''}{spot}",
                            {"traceback": traceback.format_exc()[-1500:]}, int((time.perf_counter() - t0) * 1000))
        return self.add(sid, name, status, detail, evidence, int((time.perf_counter() - t0) * 1000))

    # ---------------------------------------------------------------- the stages

    def s1_build(self) -> None:
        def go():
            from .config import BUILD, VERSION
            exe = sys.executable
            frozen = bool(getattr(sys, "frozen", False))
            where = Path(sys.argv[0]).resolve() if frozen else Path(exe).resolve()
            return PASS, f"Study Terminal {VERSION} (build {BUILD}), {'packaged app' if frozen else 'running from source'}", {
                "version": VERSION, "build": BUILD, "frozen": frozen, "executable": str(where),
                "windows": platform.platform(), "machine": platform.machine()}
        self._run("build", "Which Study Terminal is this", go)

    def s2_runtime(self) -> None:
        def go():
            from .screen import ocr_health
            v = ocr_health.check(deep=False)["versions"]
            v["python"] = sys.version.split()[0]
            return PASS, ", ".join(f"{k} {x}" for k, x in v.items() if k != "frozen"), v
        self._run("runtime", "Python and library versions in use", go)

    def s3_ocr(self) -> None:
        def go():
            from .screen import ocr_health
            r = ocr_health.check(deep=True)
            if not r["ok"]:
                return FAIL, r["headline"] + " " + r["advice"], {"steps": r["steps"]}
            rec = next((s for s in r["steps"] if s["id"] == "recognize"), None)
            return PASS, (rec or {}).get("detail", "reads known text"), {"steps": r["steps"], "took_ms": r["took_ms"]}
        self._run("ocr", "Screen-text reader (reads known text from a picture)", go)

    def s4_subsystems(self) -> None:
        def go():
            from . import diagnostics
            r = diagnostics.subsystems()
            bad = [c for c in r["checks"] if c["status"] == "fail"]
            return (PASS if r["ok"] else FAIL), r["headline"], {"checks": r["checks"], "failed": [c["id"] for c in bad]}
        self._run("subsystems", "Every part of the app does real work", go)

    def s5_backend(self, base: str) -> None:
        def go():
            import httpx
            t0 = time.perf_counter()
            try:
                r = httpx.get(f"{base}/api/health", headers={"X-Study-Terminal": "1"}, timeout=10)
            except Exception as e:  # noqa: BLE001
                return BLOCKED, (f"Study Terminal's engine isn't answering on {base} ({type(e).__name__}). Start Study "
                                 "Terminal and leave it running, then run this again."), {}
            ms = int((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                return FAIL, f"the engine answered {r.status_code}", {"body": r.text[:300]}
            d = r.json()
            if d.get("recovery"):
                return FAIL, f"the engine is in Recovery mode: {d['recovery']}", d
            ver = d.get("version") or d.get("app_version") or ""
            return PASS, f"answered in {ms} ms{', version ' + ver if ver else ''}, database {'ok' if d.get('database_ok') else 'NOT ok'}", {
                "health": d, "reply_ms": ms}
        self._run("backend", "The local engine is up and healthy", go)

    def s6_profile(self, base: str) -> None:
        def go():
            import httpx
            h = {"X-Study-Terminal": "1"}
            try:
                got = httpx.get(f"{base}/api/visual/profiles", headers=h, timeout=10)
            except Exception as e:  # noqa: BLE001
                return BLOCKED, f"engine not reachable ({type(e).__name__})", {}
            if got.status_code != 200:
                return FAIL, f"listing your charts answered {got.status_code}", {"body": got.text[:300]}
            profiles = (got.json() or {}).get("profiles", [])
            if not profiles:
                return BLOCKED, ("no chart is set up yet, so there is nothing to save and reload. Set one up in "
                                 "My chart > Set up a chart, then run this again."), {}
            first = profiles[0]
            name = first.get("name")
            back = httpx.post(f"{base}/api/visual/profiles", headers=h, json=first, timeout=15)
            if back.status_code >= 400:
                return FAIL, f"saving your chart back answered {back.status_code}", {"body": back.text[:300]}
            again = (httpx.get(f"{base}/api/visual/profiles", headers=h, timeout=10).json() or {}).get("profiles", [])
            same = next((p for p in again if p.get("id") == first.get("id")), None)
            if same is None:
                return FAIL, "the chart disappeared after being saved", {"before": first}
            keys = ("root", "timeframe", "region", "window_title_contains", "capture_seconds", "live_seconds")
            differs = {k: (first.get(k), same.get(k)) for k in keys if first.get(k) != same.get(k)}
            if differs:
                return FAIL, f"settings changed when saved and reloaded: {differs}", {"differs": differs}
            return PASS, f"'{name}' saved and reloaded unchanged ({len(profiles)} chart(s) set up)", {
                "profiles": len(profiles), "checked": {k: same.get(k) for k in keys}}
        self._run("profile", "A chart's settings survive saving and reloading", go)

    def s7_window(self, base: str) -> dict | None:
        found: dict = {}

        def go():
            import httpx
            try:
                r = httpx.get(f"{base}/api/visual/windows", headers={"X-Study-Terminal": "1"}, timeout=15)
            except Exception as e:  # noqa: BLE001
                return BLOCKED, f"engine not reachable ({type(e).__name__})", {}
            body = r.json() or {}
            if body.get("window_capture_supported") is False:
                return BLOCKED, (body.get("note") or "this computer cannot capture windows"), {"note": body.get("note")}
            wins = [w for w in (body.get("windows") or []) if isinstance(w, dict) and w.get("kind") == "window"]
            from .screen.platforms import topstepx_title
            from .screen.vision import is_browser
            hits = [w for w in wins if is_browser(w.get("process")) and topstepx_title(w.get("title") or "")]
            if not hits:
                browsers = [w.get("title", "")[:70] for w in wins if is_browser(w.get("process"))][:6]
                return FAIL, ("no Microsoft Edge window is showing a TopstepX chart. The tab is named after the "
                              "contract and its price, like 'NQZ26 $27,686.00'. Open the chart, bring that tab to "
                              "the front, and don't minimise the window."), {"browser_windows_seen": browsers}
            w = hits[0]
            parsed = topstepx_title(w["title"])
            found.update({"hwnd": int(w["id"]), "title": w["title"], "process": w.get("process")})
            return PASS, f"{parsed['contract']} at {parsed['price']:,.2f} in {w.get('process')}", {
                "title": w["title"], "process": w.get("process"), "contract": parsed["contract"],
                "price_in_title": parsed["price"], "other_browser_windows": len([x for x in wins if is_browser(x.get("process"))]) - 1}
        self._run("window", "Your Edge window with the TopstepX chart", go)
        return found or None

    def s8_capture(self, base: str, win: dict | None) -> Any:
        if not win:
            self.add("capture", "Taking a picture of that window", BLOCKED, "no window was found in the previous stage")
            return None
        grabbed: dict = {}

        def go():
            import httpx
            t0 = time.perf_counter()
            r = httpx.get(f"{base}/api/visual/preview", params={"hwnd": win["hwnd"]},
                          headers={"X-Study-Terminal": "1"}, timeout=30)
            ms = int((time.perf_counter() - t0) * 1000)
            if r.status_code != 200:
                return FAIL, f"capture answered {r.status_code}", {"body": r.text[:300]}
            body = r.content
            if len(body) < 2000:
                return FAIL, f"the picture came back almost empty ({len(body)} bytes)", {}
            grabbed["png"] = body
            if self.out_dir:
                p = self.out_dir / "capture.png"
                p.write_bytes(body)
                self.images.append(str(p))
            return PASS, f"{len(body) // 1024} KB in {ms} ms", {"bytes": len(body), "capture_ms": ms,
                                                                "saved": str(self.out_dir / 'capture.png') if self.out_dir else None}
        self._run("capture", "Taking a picture of that window", go)
        return grabbed.get("png")

    def s9_read(self, base: str, win: dict | None) -> dict | None:
        if not win:
            self.add("read", "Reading your actual chart", BLOCKED, "no window was found")
            return None
        out: dict = {}

        def go():
            import httpx
            h = {"X-Study-Terminal": "1"}
            profiles = (httpx.get(f"{base}/api/visual/profiles", headers=h, timeout=10).json() or {}).get("profiles", [])
            if not profiles:
                return BLOCKED, "no chart is set up yet (My chart > Set up a chart)", {}
            prof = profiles[0]
            t0 = time.perf_counter()
            r = httpx.post(f"{base}/api/visual/test-read", headers=h, timeout=120,
                           json={"profile": prof, "hwnd": win["hwnd"]})
            ms = int((time.perf_counter() - t0) * 1000)
            if r.status_code == 503:
                return FAIL, f"the text reader is not working: {r.json().get('detail', {}).get('error')}", r.json()
            if r.status_code != 200:
                return FAIL, f"reading answered {r.status_code}", {"body": r.text[:400]}
            d = r.json()
            out.update(d)
            out["read_ms"] = ms
            if not d.get("ok"):
                return FAIL, "; ".join(d.get("problems") or ["the chart could not be read"])[:300], {
                    "problems": d.get("problems"), "read_ms": ms}
            return PASS, f"read in {ms} ms, {len(d.get('candles') or [])} candles, confidence {d.get('confidence')}", {
                "read_ms": ms, "candles": len(d.get("candles") or []), "confidence": d.get("confidence"),
                "capture_method": d.get("capture_method"), "text_source": d.get("text_source")}
        self._run("read", "Reading your actual chart", go)
        return out or None

    def s10_validate(self, reading: dict | None, win: dict | None) -> None:
        if not reading or not reading.get("ok"):
            self.add("validate", "What it read is right", BLOCKED, "there was no successful reading to check")
            return

        def go():
            inst, tf, price = reading.get("instrument") or {}, reading.get("timeframe") or {}, reading.get("price") or {}
            problems, ev = [], {"instrument": inst.get("value"), "instrument_from": inst.get("source"),
                                "timeframe": tf.get("value"), "timeframe_from": tf.get("source"),
                                "price": price.get("value"), "price_from": price.get("source")}
            if not inst.get("value"):
                problems.append("no market was read")
            if not tf.get("value"):
                problems.append("no timeframe was read (set it in Set up a chart if your captured area leaves the "
                                "chart's own label out)")
            if price.get("value") is None:
                problems.append("no price was read")
            # The strongest check available without a market-data feed: the price read off the pixels against the
            # price TopstepX itself puts in the window title. Two different routes to the same number.
            if win and price.get("value") is not None:
                from .screen.platforms import topstepx_title
                parsed = topstepx_title(win["title"])
                if parsed:
                    ev["price_in_window_title"] = parsed["price"]
                    gap = abs(parsed["price"] - float(price["value"]))
                    ev["difference"] = round(gap, 2)
                    tol = max(2.0, abs(parsed["price"]) * 0.0005)
                    if gap > tol:
                        problems.append(f"the price read off the chart ({price['value']:,.2f}) and the price in the "
                                        f"window title ({parsed['price']:,.2f}) differ by {gap:,.2f}")
                    if parsed["root"] and inst.get("value") and parsed["root"] != inst.get("value"):
                        problems.append(f"the chart says {inst['value']} but the window title says {parsed['root']}")
            if problems:
                return FAIL, "; ".join(problems)[:400], ev
            return PASS, (f"{inst['value']} {tf['value']} at {float(price['value']):,.2f}"
                          + (f", matching the window title to {ev.get('difference', 0):.2f}" if "difference" in ev else "")), ev
        self._run("validate", "What it read is right (market, timeframe, price)", go)

    def s11_freshness(self, reading: dict | None) -> None:
        # `is None` deliberately, not falsiness: a reading that came back empty still has to answer for its stamp.
        if reading is None:
            self.add("fresh", "The reading is stamped and recent", BLOCKED, "there was no reading")
            return

        def go():
            cap = reading.get("captured_at")
            if not cap:
                return FAIL, "the reading carries no capture time, so nothing can tell how old it is", {}
            when = datetime.fromisoformat(cap)
            age = (datetime.now(timezone.utc) - when).total_seconds()
            ev = {"captured_at": cap, "age_seconds": round(age, 1), "read_ms": reading.get("read_ms")}
            if age < 0:
                return FAIL, f"the capture time is {abs(age):.0f}s in the future; clocks disagree", ev
            if age > 120:
                return FAIL, f"the reading is {age:.0f}s old", ev
            return PASS, f"stamped {cap}, {age:.1f}s old", ev
        self._run("fresh", "The reading is stamped and recent", go)

    def s12_pipeline(self, base: str) -> None:
        def go():
            import httpx
            try:
                r = httpx.get(f"{base}/api/visual/status", headers={"X-Study-Terminal": "1"}, timeout=10)
                st = r.json()
            except Exception as e:  # noqa: BLE001
                return BLOCKED, f"could not read monitoring status ({type(e).__name__})", {}
            charts = st.get("charts") or {}
            lat = st.get("latency") or {}
            ev = {"monitoring": st.get("state"), "charts": {k: v.get("status") for k, v in charts.items()}}
            if lat.get("stages"):
                ev["stages_ms"] = {s["name"]: {"p50": s["p50"], "p95": s["p95"]} for s in lat["stages"]}
                ev["slowest"] = lat.get("bottleneck")
                ev["passes"] = lat.get("passes")
            if st.get("state") != "running":
                return INFO, (f"monitoring is {st.get('state')}; start it on My chart to measure the live pipeline. "
                              "Everything above was still tested."), ev
            if not lat.get("stages"):
                return INFO, "monitoring is running but has not completed a timed pass yet; run this again in a minute", ev
            b = lat.get("bottleneck") or {}
            return PASS, (f"{lat.get('passes')} passes measured; slowest working stage is "
                          f"{b.get('what', '?')} at {b.get('p95', 0):.0f} ms (95th percentile)"), ev
        self._run("pipeline", "Live monitoring timings, stage by stage", go)

    # ---------------------------------------------------------------- report

    def run(self, base: str) -> dict:
        print(f"Study Terminal acceptance test — {self.started.isoformat(timespec='seconds')}\n", flush=True)
        self.s1_build()
        self.s2_runtime()
        self.s3_ocr()
        self.s4_subsystems()
        self.s5_backend(base)
        self.s6_profile(base)
        win = self.s7_window(base)
        self.s8_capture(base, win)
        reading = self.s9_read(base, win)
        self.s10_validate(reading, win)
        self.s11_freshness(reading)
        self.s12_pipeline(base)
        return self.report()

    def report(self) -> dict:
        counts = {k: sum(1 for s in self.stages if s.status == k) for k in (PASS, FAIL, BLOCKED, INFO)}
        chart_proved = all(
            any(s.id == sid and s.status == PASS for s in self.stages) for sid in ("window", "capture", "read", "validate", "fresh"))
        return {
            "at": self.started.isoformat(), "finished": datetime.now(timezone.utc).isoformat(),
            "machine": platform.platform(),
            "stages": [s.as_dict() for s in self.stages],
            "counts": counts,
            # The one claim the whole exercise exists to make, and it is only made on the five stages that earn it.
            "real_chart_reading_proved": chart_proved,
            "verdict": ("Study Terminal read your real TopstepX chart on this PC and what it read checks out."
                        if chart_proved else
                        "Study Terminal has NOT been shown to read your real chart on this PC. See the failed or "
                        "blocked stages above."),
            "images": self.images,
        }


def write_report(rep: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = rep["at"].replace(":", "").replace("-", "")[:15]
    j = out_dir / f"acceptance-{stamp}.json"
    j.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    lines = [f"# Study Terminal acceptance test — {rep['at']}", "",
             f"**{rep['verdict']}**", "",
             f"{rep['counts']['PASS']} passed · {rep['counts']['FAIL']} failed · "
             f"{rep['counts']['BLOCKED']} blocked · {rep['counts']['INFO']} informational", "",
             f"Machine: {rep['machine']}", "", "| Stage | Result | Detail | ms |", "|---|---|---|---|"]
    for s in rep["stages"]:
        lines.append(f"| {s['name']} | **{s['status']}** | {s['detail'].replace('|', '/')[:220]} | {s['ms']} |")
    lines += ["", "## Evidence", ""]
    for s in rep["stages"]:
        if s.get("evidence"):
            lines.append(f"### {s['name']}")
            lines.append("```json")
            lines.append(json.dumps(s["evidence"], indent=2)[:2500])
            lines.append("```")
            lines.append("")
    if rep.get("images"):
        lines += ["## Pictures", ""] + [f"- `{p}`" for p in rep["images"]] + [""]
    m = out_dir / f"acceptance-{stamp}.md"
    m.write_text("\n".join(lines), encoding="utf-8")
    return j, m
