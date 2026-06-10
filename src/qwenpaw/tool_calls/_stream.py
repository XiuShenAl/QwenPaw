# -*- coding: utf-8 -*-
"""Fan-out notifier for live tool output subscribers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

_SENTINEL = object()


@dataclass
class ToolStream:
    """Pure fan-out notifier. Holds no chunk storage of its own."""

    tool_call_id: str
    session_id: str
    _subscribers: list[asyncio.Queue[Any]] = field(default_factory=list)
    _is_closed: bool = False

    @property
    def is_closed(self) -> bool:
        return self._is_closed

    def add_subscriber(self, queue: asyncio.Queue[Any]) -> None:
        self._subscribers.append(queue)

    def remove_subscriber(self, queue: asyncio.Queue[Any]) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    async def append(self, chunk: Any) -> None:
        if self._is_closed:
            return
        if self._subscribers:
            await asyncio.gather(
                *(q.put(chunk) for q in self._subscribers),
                return_exceptions=True,
            )

    async def close(self) -> None:
        if self._is_closed:
            return
        self._is_closed = True
        if self._subscribers:
            await asyncio.gather(
                *(q.put(_SENTINEL) for q in self._subscribers),
                return_exceptions=True,
            )

    async def subscribe(self) -> AsyncIterator[Any]:
        queue: asyncio.Queue[Any] = asyncio.Queue()
        self._subscribers.append(queue)
        if self._is_closed:
            await queue.put(_SENTINEL)
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    return
                yield item
        finally:
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass
