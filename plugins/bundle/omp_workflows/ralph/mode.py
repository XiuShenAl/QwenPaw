# -*- coding: utf-8 -*-
"""RalphMode — PRD-driven continuous implementation loop."""

from __future__ import annotations

import logging
import shlex
from typing import TYPE_CHECKING, Optional

from agentscope.message import Msg, TextBlock

from qwenpaw.modes.base import AgentMode
from qwenpaw.runtime.slash_command_registry import CommandSpec

if TYPE_CHECKING:
    from typing import Any

    from .gate import RalphGate

logger = logging.getLogger(__name__)

_HELP = (
    "**Ralph** — PRD-driven continuous implementation loop\n\n"
    "Usage: `/ralph [--no-deslop] "
    "[--critic=architect|critic|codex] <task>`\n\n"
    "Creates a PRD with user stories, implements each one,\n"
    "verifies acceptance criteria, and runs reviewer verification."
)


class RalphMode(AgentMode):
    """AgentMode for the Ralph workflow."""

    name = "ralph"

    def __init__(self) -> None:
        self._gate: RalphGate | None = None

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="ralph",
                handler=self._handler,
                category="builtin",
                help_text=_HELP,
                metadata={"builtin": True},
            ),
        ]

    def setup(self, workspace: object) -> None:
        super().setup(workspace)
        from qwenpaw.loop.gates import StopHandler, StopHandlerRegistration

        from .gate import RalphGate as _G

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
                    plugin_id="__omp_ralph__",
                    handler=handler,
                    priority=0,
                    name="ralph-stop-handler",
                    scope="omp-ralph",
                ),
            )

    def is_active(self, ctx: Any) -> bool:
        # Follows upstream MissionMode pattern (LoopGate lacks public API)
        # pylint: disable=protected-access
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

        loop_dir = self._gate.activate_for_ralph(
            workspace_dir=Path(workspace_dir),
            no_deslop=parsed["no_deslop"],
            critic_type=parsed["critic_type"],
        )

        from .prompts import build_initial_prd_prompt

        prompt = build_initial_prd_prompt(task, loop_dir)
        _rewrite(ctx, prompt)
        logger.info("Ralph started: %s", loop_dir)
        return None


def _parse_args(raw: str) -> dict:
    """Parse /ralph arguments."""
    try:
        tokens = shlex.split(raw)
    except ValueError:
        return {"task": raw, "no_deslop": False, "critic_type": "architect"}

    no_deslop = False
    critic_type = "architect"
    task_parts: list[str] = []

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "--no-deslop":
            no_deslop = True
        elif t.startswith("--critic="):
            critic_type = t.split("=", 1)[1]
            if critic_type not in ("architect", "critic", "codex"):
                critic_type = "architect"
        else:
            task_parts.append(t)
        i += 1

    return {
        "task": " ".join(task_parts),
        "no_deslop": no_deslop,
        "critic_type": critic_type,
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
