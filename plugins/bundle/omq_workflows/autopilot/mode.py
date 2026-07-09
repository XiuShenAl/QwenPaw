# -*- coding: utf-8 -*-
"""AutopilotMode — full lifecycle pipeline."""

from __future__ import annotations

import logging
import shlex
from typing import TYPE_CHECKING, Optional

from agentscope.message import Msg, TextBlock

from qwenpaw.modes.base import AgentMode
from qwenpaw.runtime.slash_command_registry import CommandSpec

if TYPE_CHECKING:
    from typing import Any

    from .gate import AutopilotGate

logger = logging.getLogger(__name__)

_HELP = (
    "**Autopilot** — full lifecycle pipeline\n\n"
    "Usage: `/autopilot [--skip-qa] [--skip-validation] <task>`\n\n"
    "Phases: expansion -> planning -> execution "
    "-> qa -> validation -> cleanup\n"
    "Phase 4 uses 3 parallel reviewers (architect + security + code)."
)


class AutopilotMode(AgentMode):
    """AgentMode for the Autopilot pipeline."""

    name = "autopilot"

    def __init__(self) -> None:
        self._gate: AutopilotGate | None = None

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="autopilot",
                handler=self._handler,
                category="builtin",
                help_text=_HELP,
                metadata={"builtin": True},
            ),
        ]

    def setup(self, workspace: object) -> None:
        super().setup(workspace)
        from qwenpaw.loop.gates import StopHandler, StopHandlerRegistration

        from .gate import AutopilotGate as _G

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
                    plugin_id="__omq_autopilot__",
                    handler=handler,
                    priority=0,
                    name="autopilot-stop-handler",
                    scope="omq-autopilot",
                ),
            )

    def is_active(self, ctx: Any) -> bool:
        return self._gate is not None and self._gate._state() is not None

    async def _handler(self, ctx: "Any", args: str) -> Optional[Msg]:
        if not args or not args.strip() or args.strip().lower() == "help":
            return _info(_HELP)

        parsed = _parse_args(args)
        task = parsed["task"]
        if len(task) < 5:
            return _info("Please provide a task description.\n\n" + _HELP)

        workspace_dir = getattr(ctx, "workspace_dir", None)
        if not workspace_dir:
            return _info("ERROR: no workspace directory available.")

        from pathlib import Path

        loop_dir = self._gate.activate_for_autopilot(
            workspace_dir=Path(workspace_dir),
            skip_qa=parsed["skip_qa"],
            skip_validation=parsed["skip_validation"],
        )

        prompt = (
            f"Autopilot activated.\n"
            f"Task: {task}\n"
            f"State directory: {loop_dir}\n"
            f"Phase: expansion — analyze requirements and create spec.md."
        )
        _rewrite(ctx, prompt)
        logger.info("Autopilot started: %s", loop_dir)
        return None


def _parse_args(raw: str) -> dict:
    try:
        tokens = shlex.split(raw)
    except ValueError:
        return {"task": raw, "skip_qa": False, "skip_validation": False}

    skip_qa = False
    skip_validation = False
    task_parts: list[str] = []

    for t in tokens:
        if t == "--skip-qa":
            skip_qa = True
        elif t == "--skip-validation":
            skip_validation = True
        else:
            task_parts.append(t)

    return {
        "task": " ".join(task_parts),
        "skip_qa": skip_qa,
        "skip_validation": skip_validation,
    }


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
