"""Feed-health watcher: turns connection problems into visible alerts.

Runs every 15 seconds while the app is up. Raises an alert (once, deduplicated) when, during
premarket/regular/after-hours:
  - the streaming socket has been down for over 60 s (data falls back to polling, which lags)
  - polling has been failing for over 60 s (no fresh data at all; signals are off)
  - an open paper position's price is STALE/UNAVAILABLE (its P&L is not current)
and a "restored" alert when the feed recovers. The stream reconnects on its own with backoff;
this only makes the state impossible to miss.
"""
from __future__ import annotations

import asyncio
import logging
import time

from .types import DataStatus

log = logging.getLogger(__name__)
DOWN_AFTER_S = 60


class FeedHealthWatcher:
    def __init__(self, monitor, alerts, positions_fn=lambda: []):
        self.monitor, self.alerts, self.positions_fn = monitor, alerts, positions_fn
        self._down_since: dict[str, float] = {}
        self._alerted: set[str] = set()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(15)
            try:
                self.check()
            except Exception:
                log.exception("feed health check failed")

    def _cond(self, key: str, down: bool, title: str, body: str, severity: str, restored: str) -> None:
        now = time.monotonic()
        if down:
            since = self._down_since.setdefault(key, now)
            if now - since >= DOWN_AFTER_S and key not in self._alerted:
                self._alerted.add(key)
                self.alerts.emit("system", severity, title, body, key=f"health|{key}", fingerprint="down")
        else:
            self._down_since.pop(key, None)
            if key in self._alerted:
                self._alerted.discard(key)
                self.alerts.emit("system", "low", restored, "Data is updating again.", key=f"health|{key}", fingerprint="up")

    def check(self) -> None:
        m = self.monitor
        session = m.clock.session_at().session.value
        if not m.monitoring_enabled or session == "closed":
            return
        tr = m.tracker
        if m.streaming_enabled:
            self._cond("stream", not tr.stream_connected, "Live stream disconnected",
                       f"Yahoo's streaming socket is down ({tr.stream_reason}). Prices now come from polling and can lag "
                       "1-2 minutes; 1-minute and 2-minute signals are off. Reconnecting automatically.",
                       "medium", "Live stream reconnected")
        healthy, why = tr.provider_health()
        self._cond("provider", not healthy, "Market data unavailable",
                   f"{why}. No fresh prices: new signals are disabled until data returns.", "high", "Market data restored")
        for p in self.positions_fn():
            sym = p["symbol"]
            st = m.label(sym).status
            self._cond(f"pos|{sym}", st in (DataStatus.STALE, DataStatus.UNAVAILABLE),
                       f"Stale price for your open position {sym}",
                       f"{sym} hasn't updated recently ({st.value}). Its P&L and stop/target monitoring are not current.",
                       "high", f"{sym} price updating again")
