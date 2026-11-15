"""Data-health drill for the INSTALLED Windows app: starts it without a window, lets its own background checks run against the
real sources from this machine, and confirms the results are honest, stored, and survive a restart. Standard library only.

    python datahealth_drill.py <app command...> --data <seed data folder> --work <scratch folder> --port 8841 --out results.json

What a pass means here: the app classified every source using its defined statuses, did NOT mark anything validated that this
machine can't validate (FOMO and pump.fun must be UNSUPPORTED; the TopstepX chart must be UNVERIFIED because no TopstepX is
open here), paused every market whose data wasn't good, and kept its evidence across a restart. A live source being offline
from this machine is reported in the detail and is not, by itself, a failure of the software.
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import recovery_drill as R  # noqa: E402  (same argument format; reuses its app launcher)

STATUSES = {"VERIFIED", "HEALTHY", "DELAYED", "DEGRADED", "STALE", "CONFLICTING", "UNVERIFIED", "OFFLINE", "UNSUPPORTED"}
GOOD = {"VERIFIED", "HEALTHY", "DELAYED"}
MUST = {"fomo": "UNSUPPORTED", "pumpfun_direct": "UNSUPPORTED", "topstepx_chart": "UNVERIFIED"}
LIVE = ["yahoo_stocks", "yahoo_futures", "crypto_exchanges", "memecoin_data", "solana_rpc"]


def wait_checked(timeout: float = 240) -> dict:
    t0, d = time.time(), {}
    while time.time() - t0 < timeout:
        code, d = R.http("GET", "/datahealth", timeout=20)
        if code == 200 and d.get("enforcing"):
            by = {s["source"]: s for s in d.get("sources", [])}
            if all(by.get(k, {}).get("checked_at") and not by[k].get("from_previous_run") for k in LIVE):
                return d
        time.sleep(3)
    return d


def main() -> int:
    shutil.rmtree(R.WORK, ignore_errors=True)
    (R.WORK.parent / f"app-{R.WORK.name}.log").unlink(missing_ok=True)
    shutil.copytree(R.SEED, R.WORK)
    for p in R.WORK.glob(R.DB + "-*"):
        p.unlink()
    app = R.App(R.WORK)
    R.record("Data checks: app starts", app.start(), "installed app started without a window")
    d = wait_checked()
    by = {s["source"]: s for s in d.get("sources", [])}
    R.record("Data checks: run by themselves after start", bool(d.get("enforcing")) and all(by.get(k, {}).get("checked_at") for k in LIVE),
             f"background checks on: {d.get('enforcing')}; sources checked: {sum(1 for k in LIVE if by.get(k, {}).get('checked_at'))} of {len(LIVE)}")
    for k in LIVE + list(MUST):
        s = by.get(k) or {}
        st = s.get("status")
        ok = st == MUST[k] if k in MUST else st in STATUSES
        R.record(f"Data checks: {k} classified", ok, f"LIVE FROM THIS MACHINE: {st}. {str(s.get('why', ''))[:170]}")
    markets = (d.get("safety") or {}).get("markets") or {}
    src_of = {"stocks": "yahoo_stocks", "futures": "yahoo_futures", "crypto": "crypto_exchanges", "memecoins": "memecoin_data"}
    wrong = [m for m, src in src_of.items() if markets.get(m, {}).get("allowed") != (by.get(src, {}).get("status") in GOOD)]
    R.record("Data checks: safety controller matches the data", bool(markets) and not wrong,
             "; ".join(f"{m} {'allowed' if v.get('allowed') else 'paused'}" for m, v in markets.items()) + (f"; MISMATCH: {wrong}" if wrong else ""))
    code, rep = R.http("GET", "/datahealth/report", timeout=60)
    n1 = {k: len((rep.get("history") or {}).get(k) or []) for k in LIVE}
    first = ((rep.get("history") or {}).get("crypto_exchanges") or [{}])[0]
    R.record("Data checks: evidence stored with versions", code == 200 and all(n1.values()) and bool(first.get("app_version")) and bool(first.get("test_version")),
             f"records per source {n1}; app {first.get('app_version')}, checks {first.get('test_version')}")
    code, ran = R.http("POST", "/datahealth/run", timeout=180)
    R.record("Data checks: 'check everything now' works", code == 200 and len(ran.get("sources", [])) >= 8, f"HTTP {code}; {len(ran.get('sources', []))} sources")
    stopped = app.stop()
    ok = app.start()
    code, d0 = R.http("GET", "/datahealth", timeout=20)
    d2 = wait_checked()
    code, rep2 = R.http("GET", "/datahealth/report", timeout=60)
    n2 = {k: len((rep2.get("history") or {}).get(k) or []) for k in LIVE}
    R.record("Data checks: evidence survives a restart and is re-checked", stopped and ok and all(n2[k] > n1[k] for k in LIVE) and bool(d2.get("enforcing")),
             f"clean stop {stopped}; records before {n1}, after {n2}")
    R.record("Data checks: clean shutdown", app.stop(), "stopped through its stop file")
    R.OUT.write_text(json.dumps(R.RESULTS, indent=1))
    (R.OUT.parent / "datahealth-live-windows.json").write_text(json.dumps({"sources": [{k: s.get(k) for k in ("source", "name", "status", "why", "coverage", "checked_at", "latency_ms")}
                                                                                     for s in d2.get("sources", [])], "safety": d2.get("safety")}, indent=1))
    return 0 if all(r["outcome"] == "pass" for r in R.RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
