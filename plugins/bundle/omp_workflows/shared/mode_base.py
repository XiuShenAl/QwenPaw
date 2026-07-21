# -*- coding: utf-8 -*-
"""Shared AgentMode scaffolding for OMP workflow modes."""

from __future__ import annotations

from typing import Any

from agentscope.message import Msg, TextBlock

from qwenpaw.modes.base import AgentMode
from qwenpaw.runtime.hooks import HookContext


class OMPModeBase(AgentMode):
    """Common setup / lifecycle for OMP workflow modes.

    Subclasses must set ``name``, ``gate_cls``, ``plugin_id``,
    ``handler_name``, and ``scope``.
    """

    gate_cls: type
    plugin_id: str
    handler_name: str
    scope: str

    def __init__(self) -> None:
        self._gate: Any = None

    def setup(self, workspace: object) -> None:
        super().setup(workspace)
        from qwenpaw.loop.gates import StopHandler, StopHandlerRegistration

        handler = StopHandler()
        gate = self.gate_cls()
        handler.register(gate)
        self._gate = gate

        plugins = getattr(workspace, "plugins", None)
        if plugins is not None:
            # Defensive: matches MissionMode / older WorkspacePlugins
            if not hasattr(plugins, "stop_handlers"):
                plugins.stop_handlers = []
            plugins.stop_handlers.append(
                StopHandlerRegistration(
                    plugin_id=self.plugin_id,
                    handler=handler,
                    priority=0,
                    name=self.handler_name,
                    scope=self.scope,
                ),
            )

    def is_active(self, ctx: Any) -> bool:  # noqa: ARG002
        # Follows upstream MissionMode pattern (LoopGate lacks public API)
        # pylint: disable=protected-access
        return self._gate is not None and self._gate._state() is not None

    def on_conversation_reset(
        self,
        ctx: HookContext,  # noqa: ARG002
    ) -> None:
        """Clear gate state on /new and /clear."""
        if self._gate is not None:
            self._gate.reset_session()


def info_msg(text: str) -> Msg:
    """Build a system info message for slash-command help/errors."""
    return Msg(
        name="system",
        content=[TextBlock(type="text", text=text)],
        role="system",
    )


def rewrite_user_msg(ctx: Any, text: str) -> None:
    """Replace the last user message content with *text*."""
    msgs = getattr(ctx, "input_msgs", None)
    if not msgs:
        return
    last = msgs[-1]
    if isinstance(last, Msg):
        last.content = [TextBlock(type="text", text=text)]


__all__ = ["OMPModeBase", "info_msg", "rewrite_user_msg"]
