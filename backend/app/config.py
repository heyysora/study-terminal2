"""Application configuration.

Nothing here is required. The app launches with zero configuration: no brokerage
account, no API keys. Every setting has a working default and can be overridden
in the repo-root `.env` file or environment variables.

Order execution is a local simulator only (`execution_mode` accepts just "paper").
There is no code path that sends an order to any broker.
"""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

VERSION = "0.14.1"
BUILD = "0.14.1"   # shown in About; each delivered build gets its own backup
FROZEN = bool(getattr(sys, "frozen", False))      # running from the installed app (PyInstaller bundle)
# Where the code and bundled files live: the repo when run from source, the bundle's folder when installed.
REPO_ROOT = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "StudyTerminal"
    return Path.home() / ".study-terminal"


# Optional settings file. Installed app: %LOCALAPPDATA%\StudyTerminal\.env (survives updates and uninstall).
# From source: the repo's .env as well (it wins if both set the same key).
ENV_FILES = tuple(str(p) for p in (_default_data_dir() / ".env", REPO_ROOT / ".env"))
# The installer build's self-test sets this so a test run never loads your real settings or credentials.
if os.environ.get("STUDY_TERMINAL_NO_ENV_FILE") == "1":
    ENV_FILES = ()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- app ---
    app_env: Literal["development", "test", "production"] = "development"
    host: str = "127.0.0.1"  # localhost only
    port: int = 8765
    log_level: str = "INFO"
    data_dir: Path = Field(default_factory=_default_data_dir, alias="STUDY_TERMINAL_DATA_DIR")
    # Extra Host names accepted ONLY for /api/mobile/* (e.g. a private Tailscale name), comma-separated. Empty = localhost only.
    # Study Terminal never binds to a public interface itself; see docs/MOBILE_API.md.
    mobile_allowed_hosts: str = Field(default="", alias="STUDY_MOBILE_ALLOWED_HOSTS")
    database_url: str | None = None
    allowed_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ]

    # --- market data (no keys needed) ---
    market_data_provider: Literal["yahoo"] = "yahoo"
    # stream_and_poll: Yahoo's unofficial streaming socket for ticks + 1-min bar polling to fill gaps
    # poll_only:       1-min bar polling only (labeled POLLING, never "real-time")
    live_mode: Literal["stream_and_poll", "poll_only"] = "stream_and_poll"
    poll_interval_seconds: float = 30.0       # 1-min bar refresh for monitored symbols
    max_live_symbols: int = 40                # protects against Yahoo rate limiting
    max_requests_per_minute: int = 60         # app-wide throttle for Yahoo HTTP requests

    # --- freshness ---
    regular_hours_stale_seconds: float = 120.0
    extended_hours_stale_seconds: float = 900.0

    # --- paper trading simulator ---
    execution_mode: Literal["paper"] = "paper"
    paper_starting_cash: float = 25_000.0
    paper_margin_multiplier: float = 2.0      # 1.0 = cash account (no shorting)
    paper_allow_short: bool = True
    paper_commission_per_share: float = 0.0
    paper_commission_per_order: float = 0.0
    paper_slippage_bps: float = 1.0           # adverse slippage on market/stop fills: max(1 bp, 1 cent)
    paper_slippage_min: float = 0.01
    paper_short_borrow_fee_annual_pct: float = 3.0  # simulated; real borrow rates are not available

    # --- risk limits (spec defaults) ---
    risk_max_per_trade_pct: float = 0.5
    risk_max_daily_loss_pct: float = 2.0
    risk_max_open_positions: int = 3
    risk_min_reward_risk: float = 2.0
    risk_require_stop: bool = True

    # --- optional AI (the app works fully without it) ---
    anthropic_api_key: SecretStr | None = None   # only needed if you choose the Claude provider

    # --- optional TopstepX API (read-only market data; you pay ProjectX for it; never used for orders) ---
    projectx_username: str | None = Field(default=None, alias="STUDY_PROJECTX_USERNAME")
    projectx_api_key: SecretStr | None = Field(default=None, alias="STUDY_PROJECTX_API_KEY")
    projectx_base_url: str = Field(default="https://api.topstepx.com", alias="STUDY_PROJECTX_BASE_URL")
    projectx_rtc_url: str = Field(default="https://rtc.topstepx.com", alias="STUDY_PROJECTX_RTC_URL")   # SignalR hubs (docs: Connection URLs)

    # --- watchlist seeded on first run ---
    default_watchlist: Annotated[list[str], NoDecode] = ["SPY", "QQQ", "AAPL", "TSLA", "NVDA"]
    news_enabled: bool = True   # Yahoo news/earnings/analyst polling and the official macro calendars

    @field_validator("default_watchlist", "allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @field_validator("default_watchlist")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return [s.strip().upper() for s in v if s.strip()]

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'study_terminal.db').as_posix()}"

    def secret_values(self) -> list[str]:
        """Raw values of any SecretStr settings (for log redaction). None exist today;
        future optional data-provider keys added as SecretStr are redacted automatically."""
        out = []
        for name in type(self).model_fields:
            v = getattr(self, name)
            if isinstance(v, SecretStr) and v.get_secret_value():
                out.append(v.get_secret_value())
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
