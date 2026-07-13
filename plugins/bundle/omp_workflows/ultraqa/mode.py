# -*- coding: utf-8 -*-
"""UltraQAMode — QA cycle engine with 3-agent collaboration."""

from __future__ import annotations

import logging
import shlex
from typing import TYPE_CHECKING, Optional

from agentscope.message import Msg, TextBlock

from qwenpaw.modes.base import AgentMode
from qwenpaw.runtime.slash_command_registry import CommandSpec

if TYPE_CHECKING:
    from typing import Any

    from .gate import UltraQAGate

logger = logging.getLogger(__name__)

_HELP = (
    "**UltraQA** — automated QA cycle engine\n\n"
    "Usage:\n"
    '  `/ultraqa [--tests|--build|--lint|--typecheck|--custom "cmd"]'
    " [--interactive] [target]`\n\n"
    "Runs repeated QA cycles: check → diagnose → fix → re-check.\n"
    "Stops when all checks pass or max cycles reached."
)


class UltraQAMode(AgentMode):
    """AgentMode for the UltraQA workflow."""

    name = "ultraqa"

    def __init__(self) -> None:
        self._gate: UltraQAGate | None = None

    def commands(self) -> list[CommandSpec]:
        return [
            CommandSpec(
                name="ultraqa",
                handler=self._handler,
                category="builtin",
                help_text=_HELP,
                metadata={"builtin": True},
            ),
        ]

    def setup(self, workspace: object) -> None:
        super().setup(workspace)
        from qwenpaw.loop.gates import StopHandler, StopHandlerRegistration

        from .gate import UltraQAGate as _G

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
                    plugin_id="__omp_ultraqa__",
                    handler=handler,
                    priority=0,
                    name="ultraqa-stop-handler",
                    scope="omp-ultraqa",
                ),
            )

    def is_active(self, ctx: Any) -> bool:
        # pylint: disable=protected-access
        return self._gate is not None and self._gate._state() is not None

    async def _handler(self, ctx: "Any", args: str) -> Optional[Msg]:
        if not args or not args.strip() or args.strip().lower() == "help":
            return _info(_HELP)

        parsed = _parse_args(args)
        if parsed is None:
            return _info("Invalid arguments. " + _HELP)

        workspace_dir = getattr(ctx, "workspace_dir", None)
        if not workspace_dir:
            return _info("ERROR: no workspace directory available.")

        from pathlib import Path

        loop_dir = self._gate.activate_for_qa(
            workspace_dir=Path(workspace_dir),
            goal_type=parsed["goal_type"],
            custom_cmd=parsed["custom_cmd"],
            interactive=parsed["interactive"],
        )

        prompt = (
            f"UltraQA activated. Goal: {parsed['goal_type']}.\n"
            f"State directory: {loop_dir}\n"
            f"Read {loop_dir}/state.json and begin the QA cycle."
        )
        _rewrite(ctx, prompt)
        logger.info("UltraQA started: %s", loop_dir)
        return None


def _parse_args(raw: str) -> dict | None:
    """Parse /ultraqa arguments."""
    try:
        tokens = shlex.split(raw)
    except ValueError:
        return None

    goal_type = "tests"
    custom_cmd = ""
    interactive = False

    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t == "--tests":
            goal_type = "tests"
        elif t == "--build":
            goal_type = "build"
        elif t == "--lint":
            goal_type = "lint"
        elif t == "--typecheck":
            goal_type = "typecheck"
        elif t == "--interactive":
            interactive = True
        elif t == "--custom" and i + 1 < len(tokens):
            goal_type = "custom"
            i += 1
            custom_cmd = tokens[i]
        i += 1

    return {
        "goal_type": goal_type,
        "custom_cmd": custom_cmd,
        "interactive": interactive,
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
