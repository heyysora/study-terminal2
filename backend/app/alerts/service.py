"""Alerts: dedupe, history, in-app push, Windows desktop toast, optional sound.

Duplicate suppression: each alert has a key (e.g. "signal|TSLA|vwap_reclaim|5Min") and a
fingerprint of what matters (state, action, levels). The same key + fingerprint is never
sent twice; a changed fingerprint is a material change and alerts again.
"""
from __future__ import annotations

import json
import logging
import sys
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import desc, select, update

from ..db.models import AlertRecord
from ..db.session import Database

log = logging.getLogger(__name__)
SEVERITY_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3}


class Notifier:
    """Windows toast + sound. Silently degrades to in-app only elsewhere (or if the toast lib is missing)."""

    def __init__(self, app_url: str):
        self.app_url = app_url
        self.available = sys.platform == "win32"
        self.last_error: str | None = None

    def toast(self, title: str, body: str, link: str | None) -> bool:
        if not self.available:
            return False
        try:
            from win11toast import notify  # pip install win11toast (Windows only)

            url = self.app_url + (link or "/") if (link or "/").startswith("/") else link
            # default app id: a custom id must be registered with Windows or the toast may not show
            threading.Thread(target=lambda: notify(title, body[:250], on_click=url), daemon=True).start()
            return True
        except Exception as e:
            self.last_error = f"toast failed: {e}"
            log.warning(self.last_error)
            return False

    def sound(self, severity: str) -> None:
        if sys.platform != "win32":
            return
        try:
            import winsound

            flag = {"high": winsound.MB_ICONHAND, "medium": winsound.MB_ICONEXCLAMATION}.get(severity, winsound.MB_OK)
            winsound.MessageBeep(flag)
        except Exception as e:
            self.last_error = f"sound failed: {e}"


class AlertService:
    def __init__(self, db: Database, broadcaster, notifier: Notifier):
        self.db, self.broadcaster, self.notifier = db, broadcaster, notifier
        self._seen: dict[str, tuple[str, float]] = {}
        self.prefs = {"desktop": True, "sound": False, "min_severity_desktop": "medium", "min_severity_sound": "high",
                      "categories": {"entry": True, "position": True, "market": True, "system": True},
                      "cooldown_seconds": 600}
        self.sent = 0
        self.suppressed = 0

    def emit(self, category: str, severity: str, title: str, body: str, *, key: str, fingerprint: str,
             symbol: str | None = None, data: dict | None = None, link: str | None = None) -> bool:
        now = time.monotonic()
        prev = self._seen.get(key)
        if prev and prev[0] == fingerprint and now - prev[1] < self.prefs["cooldown_seconds"] * 6:
            self.suppressed += 1
            return False
        self._seen[key] = (fingerprint, now)
        if not self.prefs["categories"].get(category, True):
            return False
        with self.db.session() as s:
            rec = AlertRecord(category=category, severity=severity, symbol=symbol, title=title[:200], body=body,
                              data=json.dumps(data or {}, default=str))
            s.add(rec)
            s.flush()
            rid = rec.id
        payload = {"id": rid, "ts": datetime.now(timezone.utc).isoformat(), "category": category, "severity": severity,
                   "symbol": symbol, "title": title, "body": body, "data": data or {}, "link": link}
        self.broadcaster.publish({"type": "alert", "data": payload})
        if self.prefs["desktop"] and SEVERITY_ORDER[severity] >= SEVERITY_ORDER[self.prefs["min_severity_desktop"]]:
            self.notifier.toast(title, body, link)
        if self.prefs["sound"] and SEVERITY_ORDER[severity] >= SEVERITY_ORDER[self.prefs["min_severity_sound"]]:
            self.notifier.sound(severity)
        self.sent += 1
        return True

    def history(self, limit: int = 200, symbol: str | None = None) -> list[dict]:
        with self.db.session() as s:
            q = select(AlertRecord).order_by(desc(AlertRecord.id)).limit(limit)
            if symbol:
                q = q.where(AlertRecord.symbol == symbol)
            return [{"id": r.id, "ts": r.ts.isoformat(), "category": r.category, "severity": r.severity, "symbol": r.symbol,
                     "title": r.title, "body": r.body, "data": json.loads(r.data), "read": bool(r.read)}
                    for r in s.scalars(q).all()]

    def mark_read(self) -> None:
        with self.db.session() as s:
            s.execute(update(AlertRecord).values(read=1))


def signal_alert_text(sig: dict) -> tuple[str, str]:
    d = "LONG" if sig["direction"] == "long" else "SHORT"
    title = f"{sig['action']} - {sig['symbol']} ({sig['setup_name']}, {sig['timeframe']})"
    t = sig["targets"]
    body = (f"Direction: {d} | Price ${sig['price']:,.2f}\n"
            f"Entry ${sig['entry_range'][0]:,.2f}-${sig['entry_range'][1]:,.2f} | Stop ${sig['stop']:,.2f}\n"
            f"T1 ${t['t1']:,.2f} | T2 ${t['t2']:,.2f} | R:R {sig['reward_risk']}:1 | Size {sig['position_size']['shares']} sh\n"
            f"State: {sig['state']} - {sig['state_reason']}\n"
            f"Confirmation: {sig['confirmation']}\nInvalidation: ${sig['invalidation']:,.2f}\n"
            f"Why: {sig['education']['why']}")
    return title, body
