"""A local MOCK of a SignalR market hub (JSON protocol) for tests. It is not TopstepX and proves nothing about the real service:
it only lets the client's protocol handling, reconnection and data handling be tested without network access."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.server import serve

RS = "\x1e"


class MockHub:
    def __init__(self, refuse: set[str] | None = None):
        self.refuse = refuse or set()
        self.conns: list = []
        self.invocations: list[dict] = []
        self.tokens: list[str] = []
        self.connects = 0
        self.server = None
        self.port = None

    async def __aenter__(self):
        self.server = await serve(self._handler, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *a):
        self.server.close()
        await self.server.wait_closed()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    async def _handler(self, ws):
        self.connects += 1
        q = parse_qs(urlparse(ws.request.path).query)
        self.tokens.append((q.get("access_token") or [""])[0])
        hs = await ws.recv()
        assert json.loads(hs.rstrip(RS)) == {"protocol": "json", "version": 1}
        await ws.send("{}" + RS)
        self.conns.append(ws)
        try:
            async for raw in ws:
                for part in str(raw).split(RS):
                    if not part:
                        continue
                    m = json.loads(part)
                    if m.get("type") == 1:
                        self.invocations.append(m)
                        if m.get("invocationId"):
                            if m["target"] in self.refuse:
                                await ws.send(json.dumps({"type": 3, "invocationId": m["invocationId"], "error": "No market data subscription"}) + RS)
                            else:
                                await ws.send(json.dumps({"type": 3, "invocationId": m["invocationId"], "result": None}) + RS)
        except Exception:  # noqa: BLE001
            pass
        finally:
            if ws in self.conns:
                self.conns.remove(ws)

    async def push(self, target: str, *args) -> None:
        msg = json.dumps({"type": 1, "target": target, "arguments": list(args)}) + RS
        for ws in list(self.conns):
            await ws.send(msg)

    async def drop_all(self) -> None:
        for ws in list(self.conns):
            await ws.close()

    async def wait_conns(self, n: int = 1, timeout: float = 5) -> None:
        for _ in range(int(timeout / 0.02)):
            if len(self.conns) >= n and len(self.invocations) >= 2 * n:
                return
            await asyncio.sleep(0.02)
        raise TimeoutError("mock hub: client didn't connect/subscribe")
