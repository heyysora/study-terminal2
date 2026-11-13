"""Chart check: a guided test of the Visual Monitor against YOUR TopstepX chart in Microsoft Edge. Records what happened.

Two kinds of steps:
  * compare steps: Study Terminal shows exactly what it read (with how it got each value: read directly, worked out from the
    price scale, estimated from the picture, or unavailable) and you say whether it matches what TopstepX shows.
    The live-price step saves the very picture it read, so you compare against that picture and timing can't skew the result.
  * watch steps: you do something to the window (minimize it, switch tabs, resize, zoom, go offline...). Study Terminal records
    which reliability status the watchdog reported, and whether it came back to normal after you undid it.

Results go to <data dir>/chart_checks/results.jsonl (one line per result, never rewritten) with pictures in the same folder.
A result only counts as real-world evidence when it came from real screen capture; results from test or demo sources are kept
but labelled "test source" and never counted.
"""
from __future__ import annotations

import base64
import json
import platform
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

CLASS_WORDS = {"DIRECTLY_READ": "read directly", "CALCULATED_FROM_CALIBRATION": "worked out from the price scale",
               "VISUALLY_ESTIMATED": "estimated from the picture", "UNAVAILABLE": "not available"}

STEPS: list[dict] = [
    {"id": "contract", "kind": "compare", "title": "Contract", "need": 1,
     "how": "Look at the contract name at the top of your TopstepX chart (for example MNQZ6). Does it match what Study Terminal read?"},
    {"id": "timeframe", "kind": "compare", "title": "Timeframe", "need": 1,
     "how": "Look at the timeframe at the top of your chart (for example 5m). Does it match?"},
    {"id": "price", "kind": "compare", "title": "Live price", "need": 20,
     "how": "Study Terminal grabs a picture of your chart's price scale and reads the price box in it. Compare its number with the "
            "price box in that picture. Do this about 20 times over a session, in fast and quiet moments."},
    {"id": "scale", "kind": "compare", "title": "Price scale", "need": 3,
     "how": "Study Terminal lists the price labels it found on the right side of your chart. Check they match the labels you see."},
    {"id": "candle", "kind": "compare", "title": "Candles", "need": 10,
     "how": "Hover over the last COMPLETED candle in TopstepX (the one just left of the newest) and type its open, high, low and "
            "close. Study Terminal compares them with its estimate. Candles are estimated from the picture, so small differences "
            "are expected."},
    {"id": "indicators", "kind": "compare", "title": "Indicators (VWAP, EMAs)", "need": 5,
     "how": "Type the VWAP and moving-average values TopstepX shows for the newest candle. Lines whose color isn't set up in chart "
            "settings show as not available; that is recorded, not counted as wrong."},
    {"id": "resize", "kind": "watch", "title": "Resizing the window", "expect": ["REQUIRES_RECALIBRATION", "UNREADABLE", "HEALTHY"],
     "do": "Drag a corner of the Edge window to make it clearly smaller. Wait 15 seconds.",
     "undo": "Make the window its original size again.", "within": 30, "recover": 60,
     "pass": "Study Terminal either kept reading correctly or reported that the chart needs checking, and came back afterwards."},
    {"id": "zoom", "kind": "watch", "title": "Zooming the chart", "expect": ["REQUIRES_RECALIBRATION", "UNREADABLE", "DEGRADED", "HEALTHY"],
     "do": "Scroll on the TopstepX chart to zoom in a lot. Wait 15 seconds.", "undo": "Zoom back out to how it was.",
     "within": 30, "recover": 60,
     "pass": "After zooming, the price Study Terminal shows still matches TopstepX (do a Live price check), or it says to check settings."},
    {"id": "tab", "kind": "watch", "title": "Switching Edge tabs", "expect": ["UNREADABLE"],
     "do": "In the same Edge window, click a different tab.", "undo": "Click back to the TopstepX tab.", "within": 15, "recover": 30,
     "pass": "Within 15 seconds it says it can't read the chart (and captures nothing from the other tab), then recovers."},
    {"id": "minimize", "kind": "watch", "title": "Minimizing Edge", "expect": ["DISCONNECTED"],
     "do": "Minimize the Edge window.", "undo": "Restore the Edge window.", "within": 15, "recover": 30,
     "pass": "Within 15 seconds it says it can't find the chart, then recovers after you restore it."},
    {"id": "frozen", "kind": "watch", "title": "Frozen chart", "expect": ["STALE"], "market_open": True,
     "do": "Turn off your internet connection (Wi-Fi or cable) so TopstepX stops updating. Leave it off for 2 minutes.",
     "undo": "Turn your internet back on and wait for TopstepX to reconnect.", "within": 150, "recover": 120,
     "pass": "Within about 2 minutes it says the chart isn't updating, suggests nothing, and recovers after you reconnect."},
    {"id": "interrupt", "kind": "watch", "title": "Closing and reopening TopstepX", "expect": ["DISCONNECTED", "UNREADABLE"],
     "do": "Close the TopstepX tab (or the whole Edge window).", "undo": "Open TopstepX again in Edge with the same chart.",
     "within": 20, "recover": 120,
     "pass": "It notices the chart is gone, then picks it up again by itself once TopstepX is open."},
    {"id": "restart", "kind": "manual", "title": "Restarting Study Terminal",
     "how": "While watching is on, quit Study Terminal from its icon near the clock (right-click, Quit), then open it again. "
            "Answer: did watching start again by itself, and is Stop everything still on if you had pressed it?"},
]
BY_ID = {s["id"]: s for s in STEPS}


class ChartCheck:
    def __init__(self, data_dir: Path, visual, watchdog, version: str):
        self.dir = Path(data_dir) / "chart_checks"
        self.visual, self.watchdog, self.version = visual, watchdog, version
        self.samples: dict[str, dict] = {}               # sample id -> what was shown (until you answer)
        self.watch: dict | None = None                   # the watch step in progress

    # ---------------- helpers ----------------
    def _real(self) -> bool:
        return getattr(self.visual, "capture_fn", None) is None

    def _rt(self, pid: str | None = None):
        rts = getattr(self.visual, "runtimes", {}) or {}
        if pid:
            return rts.get(pid)
        return next((r for r in rts.values() if r.status == "screen_capture"), next(iter(rts.values()), None))

    def _base(self, step: str, rt) -> dict:
        return {"id": uuid.uuid4().hex[:12], "step": step, "at": datetime.now(timezone.utc).isoformat(), "version": self.version,
                "source": "real screen capture" if self._real() else "TEST SOURCE (doesn't count as real-world evidence)",
                "counts": self._real(), "chart": {"profile": rt.profile.name, "window": rt.title, "capture_method": rt.capture_method}
                if rt else None, "machine": {"os": platform.platform(), "python": platform.python_version()}}

    def _save(self, rec: dict, image: bytes | None = None) -> dict:
        self.dir.mkdir(parents=True, exist_ok=True)
        if image:
            name = f"{rec['id']}.jpg"
            (self.dir / name).write_bytes(image)
            rec["image"] = name
        with (self.dir / "results.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        return rec

    def results(self) -> list[dict]:
        p = self.dir / "results.jsonl"
        if not p.exists():
            return []
        out = []
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    @staticmethod
    def _jpg(img) -> bytes | None:
        import cv2
        if img is None:
            return None
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        return buf.tobytes() if ok else None

    def _tick(self, rt) -> float:
        from ..futures import contracts as fc
        try:
            root = rt.reading.instrument.value if rt.reading is not None and rt.reading.instrument.value else rt.profile.root
            return float(fc.get(root if root and root != "auto" else "MNQ").tick_size)
        except Exception:  # noqa: BLE001
            return 0.25

    # ---------------- summary ----------------
    def summary(self) -> dict:
        res = self.results()
        steps = []
        for s in STEPS:
            mine = [r for r in res if r["step"] == s["id"]]
            real = [r for r in mine if r.get("counts")]
            judged = [r for r in real if r.get("outcome") in ("pass", "fail")]
            passed = sum(1 for r in judged if r["outcome"] == "pass")
            unavailable = sum(1 for r in real if r.get("outcome") == "unavailable")
            need = s.get("need", 1)
            if not judged:
                status = "NOT TESTED"
            elif passed < len(judged):
                status = "PROBLEMS FOUND" if len(judged) >= need else "IN PROGRESS"
            else:
                status = "PASSED" if len(judged) >= need else "IN PROGRESS"
            steps.append({**{k: s.get(k) for k in ("id", "kind", "title", "how", "do", "undo", "pass", "need", "within", "recover")},
                          "status": status, "real_results": len(real), "passed": passed, "failed": len(judged) - passed,
                          "unavailable": unavailable, "test_source_results": len(mine) - len(real),
                          "last": mine[-1] if mine else None})
        return {"steps": steps, "real_capture": self._real(), "watch": self.watch_state(),
                "note": "Only results from real screen capture of your TopstepX chart count. Synthetic or demo results never do."}

    # ---------------- compare steps ----------------
    def sample(self, step: str, pid: str | None = None) -> dict:
        """What Study Terminal reads right now, for you to compare. Nothing is recorded until you answer."""
        if step not in BY_ID or BY_ID[step]["kind"] != "compare":
            raise ValueError("Unknown compare step.")
        rt = self._rt(pid)
        if rt is None:
            raise ValueError("No chart is set up yet. Connect your chart first.")
        if rt.status != "screen_capture" or rt.reading is None:
            raise ValueError("Study Terminal isn't reading your chart right now. Turn watching on and make sure the chart is visible.")
        r = rt.reading
        shown: dict = {"chart_status": rt.status}
        image = None
        if step == "contract":
            shown["values"] = {"contract": {"value": r.instrument.value, "how": CLASS_WORDS.get(r.instrument.cls, r.instrument.cls),
                                            "confidence": r.instrument.confidence}}
        elif step == "timeframe":
            shown["values"] = {"timeframe": {"value": r.timeframe.value, "how": CLASS_WORDS.get(r.timeframe.cls, r.timeframe.cls),
                                             "confidence": r.timeframe.confidence}}
        elif step == "price":
            from ..screen.live_price import read_tag
            img = rt.last_img
            if img is None:
                raise ValueError("No picture of the chart yet. Wait a few seconds.")
            last = rt.tape.last() if rt.tape else None
            tr = read_tag(img, r.axis, self._tick(rt), last[1] if last else None)
            ax = r.axis or {}
            x0 = int(max(0, ax.get("x_left", img.shape[1] * 0.85) - 160))
            y0, y1 = 0, img.shape[0]
            if tr.value is not None and ax.get("slope"):
                yc = int((tr.value - float(ax["intercept"])) / float(ax["slope"]))      # where the scale puts this price
                y0, y1 = max(0, yc - 110), min(img.shape[0], yc + 110)
            image = self._jpg(img[y0:y1, x0:])
            shown["values"] = {"price": {"value": tr.value, "how": "read directly from the price box" if tr.value is not None
                                         else f"not accepted: {tr.why}", "confidence": tr.confidence}}
            shown["tick"] = self._tick(rt)
        elif step == "scale":
            ax = r.axis or {}
            shown["values"] = {"scale": {"value": f"{ax.get('labels')} labels, {ax.get('price_per_pixel')} points per pixel",
                                         "how": CLASS_WORDS.get(ax.get("class"), ax.get("class")), "confidence": ax.get("confidence")}}
            img = rt.last_img
            if img is not None:
                x0 = int(max(0, ax.get("x_left", img.shape[1] * 0.85) - 10))
                image = self._jpg(img[:, x0:])
        elif step == "candle":
            cs = r.candles
            if len(cs) < 2:
                raise ValueError("Not enough candles readable.")
            c = cs[-2]
            shown["values"] = {k: {"value": getattr(c, k), "how": "estimated from the picture", "confidence": c.confidence}
                               for k in ("open", "high", "low", "close")}
            shown["tick"] = self._tick(rt)
            shown["tolerance"] = max(2 * shown["tick"], 1.5 * float((r.axis or {}).get("price_per_pixel") or 0))
        elif step == "indicators":
            vals = {}
            for name, v in (r.indicators or {}).items():
                if isinstance(v, dict):
                    vals[name] = {"value": v.get("last"), "how": CLASS_WORDS.get(v.get("class"), v.get("class")),
                                  "confidence": v.get("confidence"), "note": v.get("source")}
            shown["values"] = vals
            shown["tick"] = self._tick(rt)
            shown["tolerance"] = max(4 * shown["tick"], 2 * float((r.axis or {}).get("price_per_pixel") or 0))
        sid = uuid.uuid4().hex[:12]
        self.samples[sid] = {"step": step, "pid": rt.profile.id, "shown": shown, "image": image, "at": datetime.now(timezone.utc).isoformat()}
        out = {"sample": sid, "step": step, "shown": shown}
        if image:
            out["image"] = "data:image/jpeg;base64," + base64.b64encode(image).decode()
        return out

    def answer(self, sid: str, matches: bool | None, actual: dict | None = None, note: str = "") -> dict:
        """Your answer for a sample. `actual` = what TopstepX shows (for candles/indicators: numbers; otherwise optional)."""
        s = self.samples.pop(sid, None)
        if s is None:
            raise KeyError("That check has expired; take a new one.")
        rt = self._rt(s["pid"])
        rec = self._base(s["step"], rt) | {"shown": s["shown"], "shown_at": s["at"], "actual": actual or {}, "note": note[:500]}
        step, vals = s["step"], s["shown"].get("values", {})
        if step in ("candle", "indicators"):
            tol = float(s["shown"].get("tolerance") or 0.5)
            errs, unavailable = {}, []
            for k, typed in (actual or {}).items():
                if typed in (None, ""):
                    continue
                read = (vals.get(k) or {}).get("value")
                if read is None:
                    unavailable.append(k)
                    continue
                errs[k] = round(float(read) - float(typed), 6)
            rec["errors"], rec["tolerance"], rec["unavailable"] = errs, tol, unavailable
            if not errs and unavailable:
                rec["outcome"] = "unavailable"
            elif not errs:
                raise ValueError("Type at least one value from TopstepX.")
            else:
                rec["outcome"] = "pass" if all(abs(e) <= tol + 1e-9 for e in errs.values()) else "fail"
        else:
            if matches is None:
                raise ValueError("Say whether it matches.")
            read = next(iter(vals.values()), {}).get("value") if vals else None
            if step == "price" and read is None:
                rec["outcome"] = "unavailable" if matches else "fail"      # nothing accepted: not a wrong price, but not a read either
            else:
                rec["outcome"] = "pass" if matches else "fail"
        return self._save(rec, s.get("image"))

    # ---------------- watch steps ----------------
    def watch_state(self) -> dict | None:
        w = self.watch
        if not w:
            return None
        self._observe()
        return {k: w[k] for k in ("step", "phase", "started", "timeline", "pid", "deadline")}

    def _code(self, pid: str) -> str | None:
        st = self.watchdog.check(restart=False)
        c = (st.get("charts") or {}).get(pid)
        return c["code"] if c else None

    def _observe(self) -> None:
        w = self.watch
        if not w:
            return
        code = self._code(w["pid"])
        if code and (not w["timeline"] or w["timeline"][-1]["code"] != code):
            w["timeline"].append({"t": round(time.monotonic() - w["t0"], 1), "phase": w["phase"], "code": code})

    def watch_start(self, step: str, pid: str | None = None) -> dict:
        s = BY_ID.get(step)
        if not s or s["kind"] != "watch":
            raise ValueError("Unknown watch step.")
        rt = self._rt(pid)
        if rt is None:
            raise ValueError("No chart is set up yet.")
        if getattr(self.visual, "state", "") != "running":
            raise ValueError("Turn watching on first.")
        code = self._code(rt.profile.id)
        if code != "HEALTHY":
            raise ValueError(f"Start from a chart that is being read normally (now: {code}).")
        self.watch = {"step": step, "pid": rt.profile.id, "phase": "before", "t0": time.monotonic(),
                      "started": datetime.now(timezone.utc).isoformat(), "timeline": [], "deadline": None}
        self._observe()
        return self.watch_state()

    def watch_phase(self, phase: str) -> dict:
        """phase 'did' = you did the action; 'undid' = you put it back."""
        if not self.watch:
            raise ValueError("No watch check is running.")
        self.watch["phase"] = phase
        self.watch[f"{phase}_at"] = round(time.monotonic() - self.watch["t0"], 1)
        self._observe()
        return self.watch_state()

    def watch_finish(self, note: str = "", price_still_right: bool | None = None) -> dict:
        w = self.watch
        if not w:
            raise ValueError("No watch check is running.")
        self._observe()
        s = BY_ID[w["step"]]
        did, undid = w.get("did_at"), w.get("undid_at")
        tl = w["timeline"]
        detected = next((e for e in tl if did is not None and e["t"] >= did and e["code"] in s["expect"] and e["code"] != "HEALTHY"), None)
        recovered = next((e for e in tl if undid is not None and e["t"] >= undid and e["code"] == "HEALTHY"), None)
        final = tl[-1]["code"] if tl else None
        rt = self._rt(w["pid"])
        rec = self._base(w["step"], rt) | {"timeline": tl, "did_at_s": did, "undid_at_s": undid, "note": note[:500],
                                          "expected": s["expect"], "price_still_right": price_still_right}
        rec["detected"] = detected is not None
        rec["detected_after_s"] = round(detected["t"] - did, 1) if detected else None
        rec["recovered"] = recovered is not None
        rec["recovered_after_s"] = round(recovered["t"] - undid, 1) if recovered else None
        quiet_ok = "HEALTHY" in s["expect"] and price_still_right is True and final == "HEALTHY"   # resize/zoom: kept reading correctly
        if did is None or undid is None:
            rec["outcome"] = "incomplete"
        elif (detected and detected["t"] - did <= s["within"]) or quiet_ok:
            rec["outcome"] = "pass" if (recovered and recovered["t"] - undid <= s["recover"]) or final == "REQUIRES_RECALIBRATION" else "fail"
            if final == "REQUIRES_RECALIBRATION":
                rec["follow_up"] = "Detected correctly; chart settings need to be redone before it reads again."
        else:
            rec["outcome"] = "fail"
        self.watch = None
        return self._save(rec)

    def manual(self, step: str, answers: dict, note: str = "") -> dict:
        if step not in BY_ID or BY_ID[step]["kind"] != "manual":
            raise ValueError("Unknown step.")
        rec = self._base(step, self._rt()) | {"answers": answers, "note": note[:500]}
        given = [v for v in answers.values() if v is not None]          # None = didn't apply (for example Stop everything wasn't on)
        rec["outcome"] = "pass" if given and all(v is True for v in given) else "fail"
        return self._save(rec)
