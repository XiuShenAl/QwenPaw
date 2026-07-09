# -*- coding: utf-8 -*-
"""UltraworkMode — parallel execution engine."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from agentscope.message import Msg, TextBlock

from qwenpaw.modes.base import AgentMode
from qwenpaw.runtime.slash_command_registry import CommandSpec

if TYPE_CHECKING:
    from typing import Any

    from .gate import UltraworkGate

logger = logging.getLogger(__name__)

_HELP = (
    "**Ultrawork** — parallel task execution engine\n\n"
    "Usage: `/ultrawork <task description>`\n\n"
    "Decomposes the task into independent sub-tasks and executes\n"
    "them in parallel via spawn_subagent batch mode."
)


class UltraworkMode(AgentMode):
    """AgentMode for Ultrawork parallel execution."""

    name = "ultrawork"

    def __init__(self) -> None:
        self._gate: UltraworkGate | None = None

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="ultrawork",
                handler=self._handler,
                category="builtin",
                help_text=_HELP,
                metadata={"builtin": True},
            ),
        ]

    def setup(self, workspace: object) -> None:
        super().setup(workspace)
        from qwenpaw.loop.gates import StopHandler, StopHandlerRegistration

        from .gate import UltraworkGate as _G

        handler = StopHandler()
        gate = _G()
        handler.register(gate)
        self._gate = gate

        plugins = getattr(workspace, "plugins", None)
        if plugins is not None:
            if not hasattr(plugins, "stop_handlers"):
                plugins.stop_handlers = []
            plugins.stop_handlers.append(
                StopHandlerRegistration(
                    plugin_id="__omp_ultrawork__",
                    handler=handler,
                    priority=0,
                    name="ultrawork-stop-handler",
                    scope="omp-ultrawork",
                ),
            )

    def is_active(self, ctx: Any) -> bool:
        return self._gate is not None and self._gate._state() is not None

    async def _handler(self, ctx: "Any", args: str) -> Optional[Msg]:
        task = (args or "").strip()
        if not task or len(task) < 5 or task.lower() == "help":
            return _info(_HELP)

        workspace_dir = getattr(ctx, "workspace_dir", None)
        if not workspace_dir:
            return _info("ERROR: no workspace directory available.")

        from pathlib import Path

        loop_dir = self._gate.activate_for_work(
            workspace_dir=Path(workspace_dir),
        )

        prompt = (
            f"Ultrawork activated.\n"
            f"Task: {task}\n"
            f"State directory: {loop_dir}\n"
            f"Decompose this task into independent sub-tasks and use "
            f"spawn_subagent batch mode to execute them in parallel."
        )
        _rewrite(ctx, prompt)
        logger.info("Ultrawork started: %s", loop_dir)
        return None


def _info(text: str) -> Msg:
    return Msg(
        name="system",
        content=[TextBlock(type="text", text=text)],
        role="system",
    )


def _rewrite(ctx: "Any", text: str) -> None:
    msgs = getattr(ctx, "input_msgs", None)
    if not msgs:
        return
    last = msgs[-1]
    if isinstance(last, Msg):
        last.content = [TextBlock(type="text", text=text)]
