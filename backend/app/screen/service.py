"""Screen intelligence service: consent-gated, event-driven, local.

Loop: capture the chosen window -> skip if nothing changed -> OCR/CV (at most every few seconds)
-> recognize ticker/timeframe/price -> fuse with market data -> re-evaluate signals for that
chart -> push updates; a deeper AI explanation runs only on material changes, and only if enabled.

Privacy: OFF until you explicitly start it with consent. Captures only the one window or screen
you choose. Frames stay in memory and are discarded. Login/password screens are detected and
skipped. Nothing is uploaded unless you turn on AI vision, and then only a chart image on a
material change.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import cv2

from ..market_data.types import Timeframe
from . import capture as cap
from .vision import analyze_image, is_browser, title_looks_like_trading

log = logging.getLogger(__name__)


class ScreenService:
    def __init__(self, monitor, signals, settings, broadcaster, assistant_fn=None):
        self.monitor, self.signals, self.settings, self.broadcaster = monitor, signals, settings, broadcaster
        self.assistant_fn = assistant_fn
        self.target: cap.Target | None = None
        self.state = "off"                # off | running | paused | error
        self.state_reason = "Screen monitoring is off. Nothing is being captured."
        self.consent_at: str | None = None
        self.observation: dict | None = None
        self.fusion: dict | None = None
        self.capture_method: str | None = None
        self.frames = 0
        self.processed = 0
        self.last_change_at: float | None = None
        self._last_frame = None
        self._last_ocr = 0.0
        self._last_ai = 0.0
        self._task: asyncio.Task | None = None
        self.ai_explanation: dict | None = None
        self.holding = False              # True while a browser window shows a non-chart tab

    # ---------------- control ----------------

    def status(self) -> dict:
        return {"state": self.state, "reason": self.state_reason, "target": self.target.__dict__ if self.target else None,
                "consent_at": self.consent_at, "capture_method": self.capture_method, "frames_seen": self.frames,
                "frames_analyzed": self.processed, "holding_non_chart": self.holding, "observation": self.observation, "fusion": self.fusion,
                "ai_explanation": self.ai_explanation,
                "privacy": "Frames are processed in memory and never saved. Only the selected target is captured."}

    def _push(self) -> None:
        self.broadcaster.publish({"type": "screen", "data": self.status()})

    async def start(self, target: dict, consent: bool) -> dict:
        if not consent:
            raise PermissionError("Screen monitoring needs your explicit consent.")
        self.target = cap.Target(kind=target["kind"], id=int(target["id"]), title=target.get("title", ""), process=target.get("process"))
        self.consent_at = datetime.now(timezone.utc).isoformat()
        self.state, self.state_reason = "running", f"Watching: {self.target.title}"
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
        self.monitor._event("info", "screen", f"Screen monitoring started on '{self.target.title}' (you consented).")
        self._push()
        return self.status()

    def pause(self) -> dict:
        if self.state == "running":
            self.state, self.state_reason = "paused", "Paused by you. Nothing is being captured."
            self._push()
        return self.status()

    def resume(self) -> dict:
        if self.state == "paused" and self.target:
            self.state, self.state_reason = "running", f"Watching: {self.target.title}"
            self._push()
        return self.status()

    async def stop(self) -> dict:
        self.state, self.state_reason = "off", "Stopped by you. Nothing is being captured."
        if self._task:
            self._task.cancel()
            self._task = None
        self._last_frame, self.observation, self.fusion = None, None, None
        if self.signals:
            self.signals.focus.clear()
        self.monitor._event("info", "screen", "Screen monitoring stopped.")
        self._push()
        return self.status()

    # ---------------- loop ----------------

    async def _loop(self) -> None:
        while True:
            fps = float(self.settings.get("screen.capture_fps", 2.0)) or 2.0
            await asyncio.sleep(1 / max(0.2, min(fps, 5)))
            if self.state != "running" or not self.target:
                continue
            try:
                await self.tick()
            except Exception:
                log.exception("screen tick failed")

    async def tick(self) -> None:
        title = cap.window_title(self.target.id) if self.target.kind == "window" else self.target.title
        if self.target.kind == "window" and title is None:
            self.state, self.state_reason = "error", "The selected window was closed. Pick another window."
            self._push()
            return
        if self.target.kind == "window" and is_browser(self.target.process) and not title_looks_like_trading(title or "", self.target.process):
            # Privacy: the browser window switched to a tab that isn't a chart (email, bank...). Don't even capture it.
            if not self.holding:
                self.holding = True
                self._last_frame, self.observation, self.fusion = None, None, None
                self.state_reason = ("This browser window now shows something that doesn't look like a chart, so nothing is "
                                     "being captured or read. Switch back to your chart tab to continue.")
                self._push()
            return
        if self.holding:
            self.holding = False
            self.state_reason = f"Watching: {title}"
            self._push()
        frame, method = await asyncio.to_thread(cap.capture, self.target)
        if frame is None:
            self.state_reason = f"Capture failed: {method}"
            self._push()
            return
        self.capture_method = method
        self.frames += 1
        changed = cap.frame_change(self._last_frame, frame)
        now = time.monotonic()
        if changed > 1.5:
            self.last_change_at = now
        interval = float(self.settings.get("screen.ocr_interval_seconds", 3.0)) or 3.0
        due = (changed > 1.5 and now - self._last_ocr >= interval) or now - self._last_ocr > 30
        self._last_frame = frame
        if due:
            self._last_ocr = now
            await self.process(frame, title or "", self.target.process)

    async def process(self, frame, title: str, process: str | None) -> dict:
        obs = await asyncio.to_thread(analyze_image, frame, title, process)
        obs["at"] = datetime.now(timezone.utc).isoformat()
        prev = self.observation
        self.observation = obs
        self.processed += 1
        if obs.get("blocked"):
            self.fusion = {"blocked": True, "reason": obs["reason"]}
            self._push()
            return obs
        self.fusion = await self.fuse(obs, prev)
        material = (not prev or prev.get("ticker") != obs.get("ticker") or prev.get("timeframe") != obs.get("timeframe")
                    or bool(self.fusion.get("discrepancy")))
        if material and self.settings.get("ai.vision", False) and self.assistant_fn and time.monotonic() - self._last_ai > 120:
            self._last_ai = time.monotonic()
            ok, png = cv2.imencode(".png", frame)
            self.ai_explanation = await self.assistant_fn(obs, self.fusion, png.tobytes() if ok else None)
        self._push()
        return obs

    async def fuse(self, obs: dict, prev: dict | None) -> dict:
        """Combine what's on screen with independently retrieved market data."""
        sym, tf_s = obs.get("ticker"), obs.get("timeframe")
        out: dict = {"ticker": sym, "timeframe": tf_s, "checks": []}
        if not sym:
            out["status"] = "I can't read a ticker on this screen reliably, so I won't guess. Make the symbol visible or use a supported layout."
            return out
        q = await self.monitor.quote(sym)
        last, label = q.get("last"), q.get("label") or {}
        if not last:
            out["status"] = f"'{sym}' was read from the screen but market data has no quote for it. It may be misread, or not a US stock."
            out["ticker_confirmed"] = False
            return out
        out["ticker_confirmed"] = True
        out["market_price"], out["market_label"] = last["price"], label
        if self.signals:
            self.signals.focus = {sym}
            await self.monitor.refresh_symbols()
        vp = obs.get("visible_price")
        if vp is not None:
            diff = 100 * (vp / last["price"] - 1)
            out["visible_price"], out["price_diff_pct"] = vp, round(diff, 3)
            if abs(diff) > 0.5:
                out["discrepancy"] = (f"Screen shows ${vp:,.2f} but market data shows ${last['price']:,.2f} ({label.get('status')}), "
                                      f"{diff:+.2f}% apart. The screen or one of the feeds may be delayed, the chart may be a different "
                                      "symbol/exchange, or the screen is frozen. Recommendations use market data only.")
            out["checks"].append({"check": "visible price vs market data", "ok": abs(diff) <= 0.5, "detail": f"{diff:+.2f}%"})
        if self.last_change_at and time.monotonic() - self.last_change_at > 90 and label.get("status") in ("near_realtime", "realtime"):
            out["stale_screen"] = "The screen hasn't changed for 90+ seconds while the market is live. The chart may be frozen or paused."
        tf = Timeframe(tf_s) if tf_s else (self.signals.timeframes[0] if self.signals else Timeframe.M5)
        if not tf_s:
            out["checks"].append({"check": "timeframe", "ok": False, "detail": f"Couldn't read the chart timeframe; using {tf.value}."})
        if self.signals:
            try:
                ev, snap, _ = await self.signals.evaluate_symbol(sym, tf)
                out["analysis_timeframe"] = tf.value
                out["action"], out["best_signal"], out["reasons"] = ev["action"], ev.get("best") or ev.get("watch"), ev["reasons"]
                out["bias"] = snap.get("bias")
                levels = [lv for lv in snap.get("levels", []) if abs(lv.get("distance_pct", 99)) < 2]
                out["your_drawn_levels"] = [{**d, "nearest_known_level": min(levels, key=lambda lv: abs(lv["price"] - d["price_estimate"]))["label"]
                                             if levels else None} for d in obs.get("drawn_levels", [])]
            except Exception as e:
                out["status"] = f"Analysis unavailable: {e}"
        return out

    async def analyze_upload(self, png_bytes: bytes, title: str = "") -> dict:
        """Analyze a screenshot you provide (works on any OS). Not stored."""
        import numpy as np

        img = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Not an image")
        obs = await asyncio.to_thread(analyze_image, img, title, None)
        if obs.get("blocked"):
            return {"observation": obs}
        return {"observation": obs, "fusion": await self.fuse(obs, None)}
