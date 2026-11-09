"""Published values for scheduled US releases, from the official BLS public data API (no key needed for v1).

What it provides: the latest released value and the previous one for CPI, core CPI, PPI final demand, nonfarm payrolls and the
unemployment rate, each with its period, the BLS "preliminary" flag, the series ID and the fetch time.
What it does NOT provide: consensus forecasts. No official free source publishes them, so the app shows "forecast: not available"
rather than a number from an unofficial site.

Limits: the unauthenticated v1 API allows about 25 requests per day per IP address, so values are fetched in ONE request at most
every 6 hours. If BLS refuses (daily limit) the last good copy is kept and labeled. An optional free BLS registration key
(STUDY_BLS_API_KEY) switches to v2 with a higher limit.
Series IDs: all five were checked against the live v1 API on 2026-11-08 (latest periods: September 2026 for CPI/PPI, October
2026 for the jobs data).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

V1 = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
V2 = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
SERIES = {
    "CUSR0000SA0": {"name": "CPI (all items, SA)", "kind": "bls_cpi", "show": "pct_mom", "unit": "% m/m"},
    "CUSR0000SA0L1E": {"name": "Core CPI (ex food & energy, SA)", "kind": "bls_cpi", "show": "pct_mom", "unit": "% m/m"},
    "WPSFD4": {"name": "PPI final demand (SA)", "kind": "bls_ppi", "show": "pct_mom", "unit": "% m/m"},
    "CES0000000001": {"name": "Nonfarm payrolls", "kind": "bls_jobs", "show": "diff", "unit": "thousand jobs"},
    "LNS14000000": {"name": "Unemployment rate", "kind": "bls_jobs", "show": "level", "unit": "%"},
}
TTL = 6 * 3600


def parse(payload: dict) -> dict:
    """BLS JSON -> {series_id: {...latest, previous, change...}}. Values are as published; nothing is estimated."""
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError("; ".join(payload.get("message") or ["BLS refused the request"]))
    out = {}
    for s in payload.get("Results", {}).get("series", []):
        sid = s["seriesID"]
        meta = SERIES.get(sid, {"name": sid, "show": "level", "unit": ""})
        pts = [d for d in s.get("data", []) if d.get("period", "").startswith("M") and d["period"] != "M13"]
        if len(pts) < 3:
            continue
        vals = [float(d["value"]) for d in pts[:3]]
        if meta["show"] == "pct_mom":
            latest, previous = 100 * (vals[0] / vals[1] - 1), 100 * (vals[1] / vals[2] - 1)
        elif meta["show"] == "diff":
            latest, previous = vals[0] - vals[1], vals[1] - vals[2]
        else:
            latest, previous = vals[0], vals[1]
        out[sid] = {"series_id": sid, "name": meta["name"], "kind": meta.get("kind"), "unit": meta["unit"],
                    "period": f"{pts[0]['periodName']} {pts[0]['year']}", "previous_period": f"{pts[1]['periodName']} {pts[1]['year']}",
                    "actual": round(latest, 2 if meta["show"] != "diff" else 0), "previous": round(previous, 2 if meta["show"] != "diff" else 0),
                    "preliminary": any((f or {}).get("code") == "P" for f in pts[0].get("footnotes", [])),
                    "forecast": None, "forecast_note": "No official free source publishes consensus forecasts.",
                    "source": "U.S. Bureau of Labor Statistics public data API", "source_url": f"https://data.bls.gov/timeseries/{sid}"}
    return out


class EconData:
    def __init__(self, api_key: str | None = None, transport: httpx.AsyncBaseTransport | None = None):
        self.api_key, self.transport = api_key, transport
        self.values: dict = {}
        self.fetched_at: str | None = None
        self.error: str | None = None
        self._t = 0.0

    async def refresh(self, force: bool = False) -> dict:
        if not force and self._t and time.monotonic() - self._t < TTL:
            return self.snapshot()
        body = {"seriesid": list(SERIES)}
        url = V1
        if self.api_key:
            body["registrationkey"], url = self.api_key, V2
        try:
            async with httpx.AsyncClient(timeout=20, transport=self.transport) as c:
                r = await c.post(url, json=body)
                r.raise_for_status()
                self.values = parse(r.json()) or self.values
            self.fetched_at, self.error = datetime.now(timezone.utc).isoformat(), None
        except Exception as e:  # noqa: BLE001 - keep the last good values, say why they're old
            self.error = f"{type(e).__name__}: {str(e)[:200]}"
        self._t = time.monotonic()
        return self.snapshot()

    def snapshot(self) -> dict:
        return {"values": self.values, "fetched_at": self.fetched_at, "error": self.error,
                "note": "Actual and previous values as published by BLS. Forecasts aren't shown: no official free source exists."}

    def for_kind(self, kind: str) -> list[dict]:
        return [v for v in self.values.values() if v.get("kind") == kind]
