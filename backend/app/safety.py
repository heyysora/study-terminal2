"""Global Trading Safety Controller. One gate that every market's signals and practice orders pass through.

It can only say "no". It answers: may Study Terminal show an actionable idea (BUY, SELL, SHORT, EXIT) for this market or symbol
right now? It says no when the data for that market isn't trusted (Data Health), when Stop everything is active, or when the
app started in recovery mode. No scanner or strategy has a way to switch it off; while the background checks aren't running
(unit tests that build the app without them) it reports that it isn't enforcing instead of pretending it checked.
"""
from __future__ import annotations

from .market_data import hours

ACTIONABLE = {"BUY", "SELL", "SHORT", "EXIT", "STRONG BUY", "STRONG SHORT", "LONG"}


class SafetyController:
    def __init__(self, datahealth=None, stopped_fn=lambda: False, recovery_fn=lambda: False):
        self.dh, self.stopped_fn, self.recovery_fn = datahealth, stopped_fn, recovery_fn
        self.blocked_count = 0

    @staticmethod
    def market_of(symbol: str) -> str:
        return {"crypto": "crypto", "futures": "futures"}.get(hours.asset_kind(symbol), "stocks")

    def permit(self, market: str, symbol: str | None = None) -> tuple[bool, str]:
        """(allowed, plain reason). `market`: stocks | futures | crypto | memecoins."""
        if self.recovery_fn():
            return self._no("Study Terminal is in recovery mode, so it isn't giving trade ideas.")
        if self.stopped_fn():
            return self._no("Stop everything is on.")
        if self.dh is not None:
            ok, why = self.dh.permit(market, symbol)
            if not ok:
                return self._no(why)
            return True, why
        return True, "Data checks aren't attached."

    def permit_symbol(self, symbol: str) -> tuple[bool, str]:
        return self.permit(self.market_of(symbol), symbol)

    def _no(self, why: str) -> tuple[bool, str]:
        self.blocked_count += 1
        return False, why

    def status(self) -> dict:
        markets = {m: dict(zip(("allowed", "reason"), self.permit(m), strict=True)) for m in ("stocks", "futures", "crypto", "memecoins")}
        self.blocked_count -= sum(1 for v in markets.values() if not v["allowed"])       # asking for status isn't a blocked signal
        return {"markets": markets, "stop_everything": bool(self.stopped_fn()), "recovery_mode": bool(self.recovery_fn()),
                "enforcing": bool(self.dh and self.dh.enforcing), "blocked_since_start": self.blocked_count,
                "note": "This controller can only stop ideas and practice orders. It can't place, change or cancel anything."}
