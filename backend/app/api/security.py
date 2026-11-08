"""Local-API protection.

The API listens on 127.0.0.1 only, but your browser can still reach it from any web page.
Two guards stop a web page from using it:

1. Host check (DNS rebinding). A malicious site can point its own domain at 127.0.0.1 and then
   read responses as "same origin". Requests are accepted only when the Host header is
   127.0.0.1 / localhost / [::1] on our port, so a rebinding domain gets 421.

2. Intent header (cross-site requests). Every state-changing request (POST/PUT/PATCH/DELETE)
   must carry `X-Study-Terminal`. A cross-site form or `fetch` without CORS approval cannot set a
   custom header, and the CORS preflight it triggers is refused, so it can't change anything.
   The optional Chrome extension uses `X-Study-Token` instead (a pairing token you copy from
   Settings), checked in the extension routes.
"""
from __future__ import annotations

import json

INTENT_HEADER = b"x-study-terminal"
AUTH_HEADER = b"authorization"
MOBILE_PREFIX = "/api/mobile/"
TOKEN_HEADER = b"x-study-token"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def allowed_hosts(port: int, extra: list[str] | None = None) -> set[str]:
    base = {"127.0.0.1", "localhost", "[::1]"}
    out = set(base) | {f"{h}:{port}" for h in base}
    for h in extra or []:
        out.add(h)
    return out


class LocalOnlyMiddleware:
    def __init__(self, app, port: int, extra_hosts: list[str] | None = None, mobile_hosts: list[str] | None = None):
        self.app = app
        self.hosts = allowed_hosts(port, extra_hosts)
        # Mobile hosts are accepted for /api/mobile/* only, and those routes always require a bearer token.
        self.mobile_hosts = {h.strip().lower() for h in (mobile_hosts or []) if h.strip()}

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        host = headers.get(b"host", b"").decode("latin-1").lower()
        mobile = scope["type"] == "http" and scope["path"].startswith(MOBILE_PREFIX)
        if host not in self.hosts and not (mobile and host in self.mobile_hosts):
            return await self._deny(scope, send, 421, "Requests must be addressed to 127.0.0.1 or localhost.")
        if mobile:
            if AUTH_HEADER not in headers:
                return await self._deny(scope, send, 401, "Mobile API requests need 'Authorization: Bearer <token>'.")
            return await self.app(scope, receive, send)
        if scope["type"] == "http" and scope["method"] in UNSAFE and scope["path"].startswith("/api/"):
            if INTENT_HEADER not in headers and TOKEN_HEADER not in headers:
                return await self._deny(scope, send, 403, "Missing X-Study-Terminal header. Changes must come from the "
                                                          "Study Terminal app itself.")
        return await self.app(scope, receive, send)

    @staticmethod
    async def _deny(scope, send, status: int, message: str):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        body = json.dumps({"detail": message}).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
