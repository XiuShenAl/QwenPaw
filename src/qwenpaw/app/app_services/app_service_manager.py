# -*- coding: utf-8 -*-
"""The single cross-Kernel service container.

Strict whitelist of three fields (``task_tracker`` / ``tool_coordinator`` /
``approval_coordinator``) per ``runtime_refactor_v2.html`` §0. Adding any
other field here is a contract break — per-Kernel state belongs on
``Kernel.service_manager`` / ``Kernel.plugins`` instead.

``start`` / ``stop`` are called by FastAPI lifespan (Phase 1 of startup,
the very first thing to come up so hooks running in any later phase can
read ``ctx.app_services.*`` safely). The existing ``TaskTracker`` has no
lifecycle methods yet, so ``start``/``stop`` delegate via ``hasattr`` to
stay forward-compatible without forcing an out-of-scope edit to
``task_tracker.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .approval_coordinator import ApprovalCoordinator
from .tool_coordinator import ToolCoordinator

if TYPE_CHECKING:
    from ..approvals.service import ApprovalService
    from ..runner.task_tracker import TaskTracker


class AppServiceManager:
    """Hold the three cross-Kernel coordinators and own their lifecycle.

    Fields (frozen by contract — do not extend):

    * ``task_tracker``        — :class:`TaskTracker`
    * ``tool_coordinator``    — :class:`ToolCoordinator`
    * ``approval_coordinator` — :class:`ApprovalCoordinator`
    """

    __slots__ = (
        "task_tracker",
        "tool_coordinator",
        "approval_coordinator",
    )

    def __init__(
        self,
        *,
        task_tracker: "TaskTracker | None" = None,
        approval_service: "ApprovalService | None" = None,
    ) -> None:
        if task_tracker is None:
            from ..runner.task_tracker import TaskTracker

            task_tracker = TaskTracker()
        self.task_tracker = task_tracker
        self.tool_coordinator = ToolCoordinator(task_tracker=self.task_tracker)
        self.approval_coordinator = ApprovalCoordinator(
            service=approval_service,
        )

    async def start(self) -> None:
        """Bring coordinators online; called once in lifespan startup."""
        start_fn = getattr(self.task_tracker, "start", None)
        if callable(start_fn):
            await start_fn()  # pylint: disable=not-callable

    async def stop(self) -> None:
        """Tear down coordinators in reverse dependency order."""
        await self.tool_coordinator.shutdown()
        stop_fn = getattr(self.task_tracker, "stop", None)
        if callable(stop_fn):
            await stop_fn()  # pylint: disable=not-callable


__all__ = ["AppServiceManager"]
