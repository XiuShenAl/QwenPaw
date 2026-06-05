# -*- coding: utf-8 -*-
"""Cross-Kernel HITL tool-call coordinator.

Manages per-request tool call lifecycle: PENDING → RUNNING → DONE/CANCELLED,
with BACKGROUND as an escape hatch that delegates to TaskTracker.

See ``RUNTIME_REFACTOR_PSEUDOCODE.md`` §8.1 for the full design.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..runner.task_tracker import TaskTracker

logger = logging.getLogger(__name__)


class ToolCallState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    BACKGROUND = "background"
    DONE = "done"
    CANCELLED = "cancelled"


@dataclass
class ToolCall:
    """Record of one in-flight tool invocation."""

    call_id: str
    agent_id: str
    tool_name: str
    session_id: str = ""
    root_session_id: str = ""
    state: ToolCallState = ToolCallState.PENDING
    started_at: float = field(default_factory=time.time)
    future: asyncio.Future | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolCoordinator:
    """Cross-Kernel registry of active tool calls.

    职责分界 (IMPL_PLAN §8.1):
    - ToolCoordinator: per-request tool call 状态
      (PENDING/RUNNING/DONE/CANCELLED)
    - TaskTracker: 跨 request 的 BACKGROUND 任务管理
    - 接口面仅在 BACKGROUND 转换点接触
    """

    def __init__(self, *, task_tracker: "TaskTracker") -> None:
        self._task_tracker = task_tracker
        self._calls: dict[str, ToolCall] = {}
        self._lock = asyncio.Lock()

    async def register(self, call: ToolCall) -> None:
        """Register a tool call before execution starts."""
        async with self._lock:
            self._calls[call.call_id] = call

    async def mark_running(self, call_id: str) -> None:
        """Transition from PENDING to RUNNING."""
        async with self._lock:
            call = self._calls.get(call_id)
            if call and call.state == ToolCallState.PENDING:
                call.state = ToolCallState.RUNNING

    async def mark_done(self, call_id: str) -> None:
        """Transition to DONE."""
        async with self._lock:
            call = self._calls.get(call_id)
            if call and call.state in (
                ToolCallState.PENDING,
                ToolCallState.RUNNING,
            ):
                call.state = ToolCallState.DONE

    async def move_to_background(self, call_id: str) -> None:
        """Move a running call to BACKGROUND and delegate to TaskTracker."""
        async with self._lock:
            call = self._calls.get(call_id)
            if not call:
                return
            if call.state not in (
                ToolCallState.PENDING,
                ToolCallState.RUNNING,
            ):
                return
            call.state = ToolCallState.BACKGROUND

        task_id = f"toolcall-{call_id}"
        register_fn = getattr(
            self._task_tracker,
            "register_external_task",
            None,
        )
        unregister_fn = getattr(
            self._task_tracker,
            "unregister_external_task",
            None,
        )
        if callable(register_fn):
            await register_fn(task_id)

            async def _waiter() -> None:
                try:
                    if call.future and not call.future.done():
                        await call.future
                except Exception:
                    pass
                finally:
                    if callable(unregister_fn):
                        try:
                            await unregister_fn(task_id)
                        except Exception:
                            logger.debug(
                                "unregister_external_task failed for %s",
                                task_id,
                            )

            asyncio.create_task(_waiter())

    async def cancel(self, call_id: str) -> None:
        """Cancel a tool call by setting its future to CancelledError."""
        async with self._lock:
            call = self._calls.get(call_id)
            if not call:
                return
            if call.state in (ToolCallState.DONE, ToolCallState.CANCELLED):
                return
            call.state = ToolCallState.CANCELLED
            if call.future and not call.future.done():
                call.future.set_exception(
                    asyncio.CancelledError("user cancelled"),
                )

    def list_active(
        self,
        *,
        root_session_id: str | None = None,
    ) -> list[ToolCall]:
        """Return tool calls in active states (PENDING/RUNNING/BACKGROUND)."""
        active_states = (
            ToolCallState.PENDING,
            ToolCallState.RUNNING,
            ToolCallState.BACKGROUND,
        )
        out = [c for c in self._calls.values() if c.state in active_states]
        if root_session_id is not None:
            out = [c for c in out if c.root_session_id == root_session_id]
        return out

    async def shutdown(self) -> None:
        """Cancel all pending futures and clear state."""
        async with self._lock:
            for call in self._calls.values():
                if call.future and not call.future.done():
                    call.future.cancel()
            self._calls.clear()


__all__ = ["ToolCall", "ToolCallState", "ToolCoordinator"]
