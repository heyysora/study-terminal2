"""Optional, read-only client for the TopstepX API (ProjectX Gateway), the documented and authorized way to get
TopstepX market data. Off by default; nothing here is needed to use Study Terminal or its simulator.

You need your own TopstepX API Access subscription (billed by ProjectX: $29/month, $14.50 with Topstep's code,
as of 2026-11-07) and an API key from TopstepX > Settings > API. Put them in the .env file, never in the UI:
    STUDY_PROJECTX_USERNAME=your_topstepx_username
    STUDY_PROJECTX_API_KEY=your_key

Safety: a TopstepX API key can place real orders. This client can only call the paths in READ_ONLY_PATHS
(login, contract search, historical bars, and, if you switch it on, account balances). Any other path raises
before a request is made. There is no order, position-change or cancel code here.

Docs used (checked 2026-11-08): https://gateway.docs.projectx.com/docs/getting-started/authenticate/authenticate-api-key ,
.../api-reference/market-data/retrieve-bars , .../api-reference/market-data/search-contracts ,
.../api-reference/account/search-accounts , .../getting-started/rate-limits
NOT TESTED against a real TopstepX account (no credentials were available while building this).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

DEFAULT_BASE = "https://api.topstepx.com"
READ_ONLY_PATHS = frozenset({"/api/Auth/loginKey", "/api/Contract/search", "/api/History/retrieveBars", "/api/Account/search"})
UNIT_MINUTE = 2


class ProjectXError(Exception):
    pass


class _Window:
    """Sliding-window limiter: `n` requests per `seconds`."""

    def __init__(self, n: int, seconds: float):
        self.n, self.seconds, self.t = n, seconds, deque()

    async def acquire(self) -> None:
        while True:
            now = time.monotonic()
            while self.t and now - self.t[0] > self.seconds:
                self.t.popleft()
            if len(self.t) < self.n:
                self.t.append(now)
                return
            await asyncio.sleep(self.seconds - (now - self.t[0]) + 0.05)


class ProjectXClient:
    def __init__(self, username: str, api_key: str, base_url: str = DEFAULT_BASE, live: bool = False,
                 transport: httpx.AsyncBaseTransport | None = None):
        if not username or not api_key:
            raise ProjectXError("TopstepX API username and key are both required.")
        self._user, self._key = username, api_key
        self.base = base_url.rstrip("/")
        self.live = live
        self._token: str | None = None
        self._token_at = 0.0
        self._bars_limit = _Window(45, 30)      # documented: 50 / 30 s for retrieveBars (kept under it)
        self._other_limit = _Window(180, 60)    # documented: 200 / 60 s for everything else
        self._http = httpx.AsyncClient(base_url=self.base, timeout=20, transport=transport,
                                       headers={"accept": "text/plain", "Content-Type": "application/json"})
        self._contracts: dict[str, dict] = {}
        self.last_error: str | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, body: dict, auth: bool = True) -> dict:
        if path not in READ_ONLY_PATHS:
            raise ProjectXError(f"Blocked: {path} is not a read-only endpoint. Study Terminal never sends orders.")
        await (self._bars_limit if path == "/api/History/retrieveBars" else self._other_limit).acquire()
        headers = {}
        if auth:
            await self._ensure_token()
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            r = await self._http.post(path, json=body, headers=headers)
        except httpx.HTTPError as e:
            self.last_error = f"Network error talking to TopstepX: {type(e).__name__}"
            raise ProjectXError(self.last_error) from e
        if r.status_code == 401 and auth:
            self._token = None
            raise ProjectXError("TopstepX rejected the session token (401). It will log in again on the next request.")
        if r.status_code == 429:
            self.last_error = "TopstepX rate limit hit (429). Backing off."
            raise ProjectXError(self.last_error)
        if r.status_code >= 400:
            self.last_error = f"TopstepX returned HTTP {r.status_code}."
            raise ProjectXError(self.last_error)
        data = r.json()
        if not data.get("success", False):
            self.last_error = f"TopstepX error {data.get('errorCode')}: {data.get('errorMessage') or 'no message'}"
            raise ProjectXError(self.last_error)
        return data

    async def _ensure_token(self) -> None:
        if self._token and time.monotonic() - self._token_at < 23 * 3600:   # tokens last 24 h
            return
        data = await self._post("/api/Auth/loginKey", {"userName": self._user, "apiKey": self._key}, auth=False)
        if not data.get("token"):
            raise ProjectXError("TopstepX login returned no token.")
        self._token, self._token_at = data["token"], time.monotonic()

    async def token(self) -> str:
        """Session token for the documented SignalR hubs (passed as ?access_token=). Refreshed before its 24 h expiry."""
        await self._ensure_token()
        return self._token

    def invalidate_token(self) -> None:
        self._token, self._token_at = None, 0.0

    async def find_contract(self, name: str) -> dict:
        """Look a contract up by its platform name (e.g. 'MNQZ6'). Never guesses an ID."""
        if name in self._contracts:
            return self._contracts[name]
        data = await self._post("/api/Contract/search", {"searchText": name, "live": self.live})
        hits = [c for c in data.get("contracts", []) if str(c.get("name", "")).upper() == name.upper()]
        if not hits:
            raise ProjectXError(f"TopstepX has no contract named {name}.")
        self._contracts[name] = hits[0]
        return hits[0]

    async def bars(self, contract_name: str, minutes: int, start: datetime, end: datetime | None = None, limit: int = 5000) -> list[dict]:
        c = await self.find_contract(contract_name)
        end = end or datetime.now(timezone.utc)
        data = await self._post("/api/History/retrieveBars", {
            "contractId": c["id"], "live": self.live, "startTime": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
            "endTime": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "unit": UNIT_MINUTE, "unitNumber": minutes,
            "limit": min(limit, 20000), "includePartialBar": False})
        out = []
        for b in data.get("bars", []):
            ts = datetime.fromisoformat(str(b["t"]).replace("Z", "+00:00")).astimezone(timezone.utc)
            out.append({"ts": ts, "open": float(b["o"]), "high": float(b["h"]), "low": float(b["l"]), "close": float(b["c"]),
                        "volume": float(b.get("v") or 0)})
        out.sort(key=lambda x: x["ts"])
        return out

    async def accounts(self) -> list[dict]:
        """Balances of your active accounts. Read-only; only called if you turned on account reading."""
        data = await self._post("/api/Account/search", {"onlyActiveAccounts": True})
        return [{"id": a.get("id"), "name": a.get("name"), "balance": a.get("balance"), "can_trade": a.get("canTrade")}
                for a in data.get("accounts", [])]

    async def check(self) -> dict:
        try:
            await self._ensure_token()
            return {"ok": True, "detail": "Logged in to the TopstepX API (read-only use)."}
        except ProjectXError as e:
            return {"ok": False, "detail": str(e)}


def lookback_start(days: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)
