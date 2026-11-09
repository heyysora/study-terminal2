"""MOCK TopstepX server for manual UI checks of the Live Market screen. NOT real market data and NOT TopstepX.

It imitates only the documented shapes Study Terminal uses: REST /api/Auth/loginKey, /api/Contract/search, /api/History/retrieveBars,
and a SignalR JSON-protocol market hub at /hubs/market that pushes synthetic GatewayQuote/GatewayTrade events (random walk).
Use it to see the chart update, the LIVE / STALE / DISCONNECTED states and reconnection without a TopstepX account:

    python -m research.mock_topstepx            # listens on 127.0.0.1:8790
    set STUDY_PROJECTX_USERNAME=demo, STUDY_PROJECTX_API_KEY=demo,
        STUDY_PROJECTX_BASE_URL=http://127.0.0.1:8790, STUDY_PROJECTX_RTC_URL=http://127.0.0.1:8790
    then choose "TopstepX API" as the futures data source.

POST /mock/pause and /mock/resume stop/start the synthetic trades (to see STALE); POST /mock/drop closes hub connections.
"""
from __future__ import annotations

import asyncio
import json
import random
from datetime import datetime, timedelta, timezone

import uvicorn
from fastapi import FastAPI, Request, WebSocket

from app.futures import contracts as fc
from app.futures.sessions import FuturesClock

RS = "\x1e"
app = FastAPI()
BASE = {"NQ": 25000.0, "MNQ": 25000.0, "ES": 6800.0, "MES": 6800.0}
state = {"paused": False, "conns": set(), "last": dict(BASE)}


def _contracts():
    today = datetime.now(fc.CT).date()
    out = {}
    for r in BASE:
        c = fc.front_contract(r, today)
        out[c.short_code] = {"id": f"CON.F.US.{r}.{fc.MONTH_CODES[c.month - 1]}{c.year % 100}", "name": c.short_code, "root": r,
                             "description": f"MOCK {r}", "tickSize": float(c.spec.tick_size), "tickValue": float(c.spec.tick_value),
                             "activeContract": True, "symbolId": f"F.US.{r}"}
    return out


def _snap(p, root):
    t = float(fc.get(root).tick_size)
    return round(round(p / t) * t, 6)


@app.post("/api/Auth/loginKey")
async def login(req: Request):
    return {"token": "mock-jwt", "success": True, "errorCode": 0, "errorMessage": None}


@app.post("/api/Contract/search")
async def search(req: Request):
    b = await req.json()
    txt = str(b.get("searchText", "")).upper()
    return {"contracts": [c for n, c in _contracts().items() if n.startswith(txt)], "success": True, "errorCode": 0, "errorMessage": None}


MINUTES: dict[str, dict] = {}            # root -> {minute start: bar}: one consistent synthetic history, then live minutes


def _seed(root: str) -> None:
    if root in MINUTES:
        return
    clock = FuturesClock(fc.get(root))
    rnd = random.Random(root)
    px, out = BASE[root], {}
    t = (datetime.now(timezone.utc) - timedelta(days=14)).replace(second=0, microsecond=0)
    stop = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    while t < stop:
        if clock.window_at(t) is not None:
            o = hi = lo = px
            for _ in range(4):
                px = _snap(px + rnd.gauss(0, 1.5 if "N" in root else 0.5), root)
                hi, lo = max(hi, px), min(lo, px)
            out[t] = {"o": o, "h": hi, "l": lo, "c": px, "v": rnd.randint(20, 300)}
        t += timedelta(minutes=1)
    MINUTES[root], state["last"][root] = out, px


@app.post("/api/History/retrieveBars")
async def bars(req: Request):
    b = await req.json()
    c = next(x for x in _contracts().values() if x["id"] == b["contractId"])
    root = c["root"]
    _seed(root)
    clock = FuturesClock(fc.get(root))
    unit_s = {1: 1, 2: 60, 3: 3600, 4: 86400}[b["unit"]] * int(b["unitNumber"])
    start = datetime.fromisoformat(b["startTime"].replace("Z", "+00:00"))
    end = min(datetime.fromisoformat(b["endTime"].replace("Z", "+00:00")), datetime.now(timezone.utc))
    agg: dict = {}
    for t, m in sorted(MINUTES[root].items()):
        if not (start <= t and t + timedelta(minutes=1) <= end):
            continue
        w = clock.window_at(t)
        k = w.open + timedelta(seconds=int((t - w.open).total_seconds() // unit_s) * unit_s) if w else t
        a = agg.get(k)
        if a is None:
            agg[k] = dict(m)
        else:
            a["h"], a["l"], a["c"], a["v"] = max(a["h"], m["h"]), min(a["l"], m["l"]), m["c"], a["v"] + m["v"]
    out = [{"t": k.astimezone(timezone.utc).isoformat(), **v} for k, v in agg.items()]
    out.reverse()                                             # the docs' example lists newest first
    return {"bars": out[: int(b.get("limit", 20000))], "success": True, "errorCode": 0, "errorMessage": None}


@app.post("/mock/{action}")
async def control(action: str):
    if action in ("pause", "resume"):
        state["paused"] = action == "pause"
    elif action == "drop":
        for ws in list(state["conns"]):
            await ws.close()
    return {"paused": state["paused"], "connections": len(state["conns"])}


@app.websocket("/hubs/market")
async def hub(ws: WebSocket):
    await ws.accept()
    await ws.receive_text()                                   # {"protocol":"json","version":1}
    await ws.send_text("{}" + RS)
    subs: set[str] = set()
    state["conns"].add(ws)
    ids = {c["id"]: c["root"] for c in _contracts().values()}

    async def pump():
        rnd = random.Random()
        while True:
            await asyncio.sleep(0.2)
            if state["paused"]:
                continue
            for cid in list(subs):
                root = ids[cid]
                _seed(root)
                p = _snap(state["last"][root] + rnd.choice([-1, 0, 0, 1]) * float(fc.get(root).tick_size), root)
                state["last"][root] = p
                vol = rnd.randint(1, 5)
                m0 = datetime.now(timezone.utc).replace(second=0, microsecond=0)
                mb = MINUTES[root].setdefault(m0, {"o": p, "h": p, "l": p, "c": p, "v": 0})
                mb["h"], mb["l"], mb["c"], mb["v"] = max(mb["h"], p), min(mb["l"], p), p, mb["v"] + vol
                now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                t = float(fc.get(root).tick_size)
                await ws.send_text(json.dumps({"type": 1, "target": "GatewayTrade", "arguments": [cid, [
                    {"symbolId": f"F.US.{root}", "price": p, "timestamp": now, "type": rnd.randint(0, 1), "volume": vol}]]}) + RS)
                await ws.send_text(json.dumps({"type": 1, "target": "GatewayQuote", "arguments": [cid, {
                    "symbol": f"F.US.{root}", "lastPrice": p, "bestBid": p - t, "bestAsk": p, "timestamp": now}]}) + RS)
    task = asyncio.create_task(pump())
    try:
        while True:
            raw = await ws.receive_text()
            for part in raw.split(RS):
                if not part:
                    continue
                m = json.loads(part)
                if m.get("type") == 1 and m["target"] in ("SubscribeContractQuotes", "SubscribeContractTrades"):
                    subs.add(m["arguments"][0])
                    await ws.send_text(json.dumps({"type": 3, "invocationId": m.get("invocationId"), "result": None}) + RS)
    except Exception:  # noqa: BLE001
        pass
    finally:
        task.cancel()
        state["conns"].discard(ws)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8790, log_level="warning")
