"""Provider registry. Add new providers here; nothing else needs to change."""
from __future__ import annotations

from collections.abc import Callable

from ...config import Settings
from .base import MarketDataProvider


def _yahoo(settings: Settings) -> MarketDataProvider:
    from .yahoo import YahooProvider

    return YahooProvider(requests_per_minute=settings.max_requests_per_minute, cache_dir=settings.data_dir / "yf-cache")


PROVIDERS: dict[str, Callable[[Settings], MarketDataProvider]] = {
    "yahoo": _yahoo,
    # "finnhub": _finnhub,   # free API key; real-time trade websocket (candidate, see docs)
}


def create_provider(settings: Settings) -> MarketDataProvider:
    try:
        factory = PROVIDERS[settings.market_data_provider]
    except KeyError:
        raise ValueError(f"Unknown market data provider {settings.market_data_provider!r}; available: {sorted(PROVIDERS)}")
    return factory(settings)
