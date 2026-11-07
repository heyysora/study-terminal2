"""In-process pub/sub used to fan market events out to WebSocket clients (and later,
the scanner, signal engine and alert system). Slow consumers drop their oldest
messages instead of slowing the market data path down."""
from __future__ import annotations

import asyncio
from typing import Any


class Broadcaster:
    def __init__(self, queue_size: int = 2000):
        self._subs: set[asyncio.Queue] = set()
        self._size = queue_size

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=self._size)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subs):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(event)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)
