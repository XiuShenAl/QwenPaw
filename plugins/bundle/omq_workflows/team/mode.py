# -*- coding: utf-8 -*-
"""TeamMode — multi-agent collaboration pipeline."""

from __future__ import annotations

import logging
import re
import shlex
from typing import TYPE_CHECKING, Optional

from agentscope.message import Msg, TextBlock

from qwenpaw.modes.base import AgentMode
from qwenpaw.runtime.slash_command_registry import CommandSpec

if TYPE_CHECKING:
    from typing import Any

    from .gate import TeamPipelineGate

logger = logging.getLogger(__name__)

_HELP = (
    "**Team** — multi-agent collaboration pipeline\n\n"
    "Usage: `/team [N:role] <task>`\n\n"
    "Examples:\n"
    "  `/team 3:executor Implement authentication`\n"
    "  `/team ralph Build the REST API`\n\n"
    "Phases: plan -> prd -> exec -> verify -> fix (retry)"
)


class TeamMode(AgentMode):
    """AgentMode for the Team pipeline."""

    name = "team"

    def __init__(self) -> None:
        self._gate: TeamPipelineGate | None = None

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="team",
                handler=self._handler,
                category="builtin",
                help_text=_HELP,
                metadata={"builtin": True},
            ),
        ]

    def setup(self, workspace: object) -> None:
        super().setup(workspace)
        from qwenpaw.loop.gates import StopHandler, StopHandlerRegistration

        from .gate import TeamPipelineGate as _G

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
                    plugin_id="__omq_team__",
                    handler=handler,
                    priority=0,
                    name="team-stop-handler",
                    scope="omq-team",
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

        loop_dir = self._gate.activate_for_team(
            workspace_dir=Path(workspace_dir),
            agent_count=parsed["agent_count"],
            agent_role=parsed["agent_role"],
        )

        prompt = (
            f"Team pipeline activated.\n"
            f"Task: {task}\n"
            f"Workers: {parsed['agent_count']}, Role: {parsed['agent_role']}\n"
            f"State directory: {loop_dir}\n"
            f"Phase: plan — explore the codebase and create a task breakdown."
        )
        _rewrite(ctx, prompt)
        logger.info("Team started: %s", loop_dir)
        return None


_TEAM_SPEC_RE = re.compile(r"^(\d+):(\w[\w-]*)$")


def _parse_args(raw: str) -> dict:
    try:
        tokens = shlex.split(raw)
    except ValueError:
        return {"task": raw, "agent_count": 3, "agent_role": "executor"}

    agent_count = 3
    agent_role = "executor"
    task_parts: list[str] = []

    for i, t in enumerate(tokens):
        m = _TEAM_SPEC_RE.match(t)
        if m and i == 0:
            agent_count = int(m.group(1))
            agent_role = m.group(2)
        elif t in ("executor", "ralph") and i == 0:
            agent_role = t
        else:
            task_parts.append(t)

    return {
        "task": " ".join(task_parts),
        "agent_count": max(1, min(agent_count, 10)),
        "agent_role": agent_role,
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
