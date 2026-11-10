"""User settings editable from the UI, persisted in SQLite, applied live (no restart).
Defaults come from .env/config; anything changed in the UI overrides them."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from ..db.models import SettingRecord
from ..db.session import Database

SCHEMA: dict[str, tuple[type, Any]] = {
    # risk
    "risk.max_per_trade_pct": (float, None), "risk.max_daily_loss_pct": (float, None), "risk.max_open_positions": (int, None),
    "risk.min_reward_risk": (float, None), "risk.require_stop": (bool, None), "risk.max_consecutive_losses": (int, 3),
    "risk.max_exposure_pct": (float, 100.0),
    # paper simulator
    "paper.slippage_bps": (float, None), "paper.slippage_min": (float, None), "paper.commission_per_share": (float, None),
    "paper.commission_per_order": (float, None), "paper.allow_short": (bool, None), "paper.margin_multiplier": (float, None),
    "paper.borrow_fee_annual_pct": (float, None),
    # signals
    "signals.timeframes": (list, ["5Min", "15Min", "1Hour"]), "signals.enabled_setups": (list, []), "signals.params": (dict, {}),
    # alerts
    "journal.max_trades_per_day": (int, 3), "extension.enabled": (bool, False), "extension.token": (str, ""), "alerts.desktop": (bool, True), "events.warn_minutes": (int, 30), "visual.last_state": (str, "stopped"), "mobile.enabled": (bool, False), "mobile.token_hash": (str, ""), "mobile.token_created": (str, ""), "alerts.watch_only_ideas": (bool, False), "alerts.sound": (bool, False), "alerts.min_severity_desktop": (str, "medium"),
    "alerts.min_severity_sound": (str, "high"), "alerts.categories": (dict, {"entry": True, "position": True, "market": True, "system": True}),
    # scanner
    "scanner.filters": (dict, {}), "scanner.interval_seconds": (float, 180.0), "scanner.enabled": (bool, True),
    # AI
    "ai.provider": (str, "auto"), "ai.model": (str, ""), "ai.ollama_url": (str, "http://localhost:11434"), "ai.vision": (bool, False),
    # learning
    "learning.level": (str, "beginner"),
    # screen
    "screen.capture_fps": (float, 2.0), "screen.ocr_interval_seconds": (float, 2.0),
    # desktop
    "futures.prop": (dict, {}), "futures.personal": (dict, {}), "futures.paper": (dict, {}), "futures.fees": (dict, {}),
    "futures.default_root": (str, "MES"), "futures.stream_enabled": (bool, True), "futures.stream_stale_seconds": (float, 30.0), "futures.watch": (list, ["NQ", "MNQ", "ES", "MES", "CL", "GC"]), "futures.data_source": (str, "yahoo"),
    "futures.projectx_live_data": (bool, False), "futures.projectx_read_account": (bool, False), "futures.rth": (dict, {}),
    "screen.platform": (str, "auto"), "futures.platform": (str, "topstepx"), "automation.autostart": (bool, True), "futures.profiles": (dict, {}), "screen.read_account_info": (bool, False), "app.market_mode": (str, "equities"),
    # interface: display only. Changing these never changes limits, permissions or calculations.
    "ui.mode": (str, "simple"), "ui.setup_dismissed": (bool, False), "ui.trades_chosen": (bool, False),
    "desktop.start_on_login": (bool, False), "desktop.keep_awake_while_monitoring": (bool, False),
}


class SettingsStore:
    def __init__(self, db: Database):
        self.db = db
        self._values: dict[str, Any] = {}
        self.listeners: list = []
        with db.session() as s:
            for r in s.scalars(select(SettingRecord)).all():
                if r.key in SCHEMA:
                    self._values[r.key] = json.loads(r.value)

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._values:
            return self._values[key]
        d = SCHEMA.get(key, (None, default))[1]
        return default if d is None else d

    def all(self) -> dict:
        return {k: self.get(k) for k in SCHEMA}

    def update(self, changes: dict[str, Any]) -> dict:
        clean = {}
        for k, v in changes.items():
            if k not in SCHEMA:
                raise KeyError(f"Unknown setting {k!r}")
            typ = SCHEMA[k][0]
            if v is None:
                clean[k] = None
                continue
            if typ is float and isinstance(v, (int, float)) and not isinstance(v, bool):
                v = float(v)
            if typ is int and isinstance(v, float) and v.is_integer():
                v = int(v)
            if not isinstance(v, typ) or (typ is int and isinstance(v, bool)):
                raise ValueError(f"{k} must be {typ.__name__}")
            if k == "ui.mode" and v not in ("simple", "advanced"):
                raise ValueError("ui.mode must be simple or advanced")
            if typ in (float, int) and v < 0:
                raise ValueError(f"{k} cannot be negative")
            clean[k] = v
        with self.db.session() as s:
            for k, v in clean.items():
                rec = s.get(SettingRecord, k)
                if v is None:
                    if rec:
                        s.delete(rec)
                    self._values.pop(k, None)
                    continue
                if rec:
                    rec.value = json.dumps(v)
                else:
                    s.add(SettingRecord(key=k, value=json.dumps(v)))
                self._values[k] = v
        for fn in self.listeners:
            fn(clean)
        return self.all()
