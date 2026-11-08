"""Mobile companion API: read status, and only the controls that make things SAFER (pause, resume, emergency stop).

Security model (see docs/MOBILE_API.md):
- Off by default. You turn it on in the Automation Center, which shows a random token ONCE; only its SHA-256 hash is stored.
- Every /api/mobile/* request needs `Authorization: Bearer <token>` (checked in constant time). Ten bad tokens from one address
  within a minute lock that address out for a minute.
- Study Terminal still listens on 127.0.0.1 only. To reach it from a phone you use an encrypted private channel you control
  (an SSH tunnel, or a private Tailscale/WireGuard network with its host name listed in STUDY_MOBILE_ALLOWED_HOSTS). Nothing is
  exposed to the public internet by Study Terminal, and those extra host names are accepted for /api/mobile/* only.
- No order placement, no mode changes, no rule changes, no clearing an emergency stop from the phone. Topstep prohibits trading
  from remote servers/VPS, and every order here is simulated anyway; the phone is a monitor with a brake, nothing more.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["mobile"])
_FAILS: dict[str, deque] = defaultdict(deque)
MAX_FAILS, WINDOW = 10, 60.0


def _store(request: Request):
    return request.app.state.settings_store


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def require_token(request: Request) -> None:
    ip = request.client.host if request.client else "?"
    q = _FAILS[ip]
    now = time.monotonic()
    while q and now - q[0] > WINDOW:
        q.popleft()
    if len(q) >= MAX_FAILS:
        raise HTTPException(429, "Too many bad tokens from this address. Wait a minute.")
    st = _store(request)
    if not st.get("mobile.enabled", False) or not st.get("mobile.token_hash"):
        raise HTTPException(403, "Mobile access is turned off. Turn it on in the Automation Center on your computer.")
    auth = request.headers.get("authorization", "")
    tok = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not tok or not hmac.compare_digest(_hash(tok), st.get("mobile.token_hash")):
        q.append(now)
        raise HTTPException(401, "Invalid token.")


# ---------------- desktop-side management (normal local-app protection applies) ----------------

@router.get("/api/mobile-access")
def access_status(request: Request):
    st = _store(request)
    return {"enabled": bool(st.get("mobile.enabled", False)), "has_token": bool(st.get("mobile.token_hash")),
            "token_created": st.get("mobile.token_created") or None,
            "allowed_hosts": [h for h in request.app.state.settings.mobile_allowed_hosts.split(",") if h.strip()],
            "listening_on": f"{request.app.state.settings.host}:{request.app.state.settings.port}",
            "note": "Study Terminal listens on this computer only. Use an SSH tunnel or a private network you control to reach it from a phone; "
                    "see docs/MOBILE_API.md. The phone can read status and pause/resume/emergency-stop automation, nothing else."}


class AccessIn(BaseModel):
    enabled: bool
    new_token: bool = False


@router.post("/api/mobile-access")
def access_set(body: AccessIn, request: Request):
    st = _store(request)
    out: dict = {}
    changes: dict = {"mobile.enabled": body.enabled}
    if body.enabled and (body.new_token or not st.get("mobile.token_hash")):
        tok = secrets.token_urlsafe(32)
        changes |= {"mobile.token_hash": _hash(tok), "mobile.token_created": datetime.now(timezone.utc).isoformat()}
        out["token"] = tok
        out["token_note"] = "Copy this now. It is shown once; only a hash is stored. Making a new one disconnects the old."
    if not body.enabled:
        changes |= {"mobile.token_hash": "", "mobile.token_created": ""}      # turning off revokes the token
    st.update(changes)
    return {**access_status(request), **out}


# ---------------- phone-side (bearer token) ----------------

def _summary(request: Request) -> dict:
    f = request.app.state.futures
    now = datetime.now(timezone.utc)
    a = f.automation.status()
    acct = f.engine.summary(now, f.clock("MES"))
    risk = acct["risk"]
    return {"as_of": now.isoformat(), "simulated": True,
            "automation": {k: a[k] for k in ("mode", "mode_label", "status", "roots", "last_cycle_at", "cycles", "emergency")},
            "contracts": a["per_contract"],
            "account": {"balance": acct["balance"], "equity": acct["equity"], "day_pnl": risk["metrics"].get("day_pnl"),
                        "mll_remaining": risk["official"].get("mll_remaining"), "dll_remaining": risk["official"].get("dll_remaining"),
                        "blocked": risk.get("blocked"), "blocks": [b["text"] for b in risk.get("blocks", [])]},
            "positions": [{k: p.get(k) for k in ("contract", "qty", "avg_price", "mark", "unrealized")} for p in acct["positions"]],
            "working_orders": len(acct["working_orders"]),
            "recent_decisions": [{k: d.get(k) for k in ("contract", "outcome", "reason", "evaluated_at")} for d in f.decisions(limit=10)],
            "log": a["log"][:15],
            "note": "Simulated trading only. Study Terminal can't see or change your real Topstep account."}


@router.get("/api/mobile/status")
def mobile_status(request: Request):
    require_token(request)
    return _summary(request)


@router.get("/api/mobile/alerts")
def mobile_alerts(request: Request, limit: int = 30):
    require_token(request)
    al = request.app.state.alerts
    return {"alerts": al.history(min(limit, 100))}


@router.post("/api/mobile/automation/{action}")
async def mobile_control(action: str, request: Request):
    require_token(request)
    if action not in ("pause", "resume", "emergency-stop"):
        raise HTTPException(404, "Only pause, resume and emergency-stop are available from a phone.")
    a = request.app.state.futures.automation
    try:
        if action == "pause":
            a.pause()
        elif action == "resume":
            await a.resume()
        else:
            await a.emergency_stop("Emergency stop pressed on the mobile companion")
        a._log("info", f"'{action}' requested from the mobile companion.")
        a.save()
    except PermissionError as e:
        raise HTTPException(409, str(e)) from e
    return _summary(request)
