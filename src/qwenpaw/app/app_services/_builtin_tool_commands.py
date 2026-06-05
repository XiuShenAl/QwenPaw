# -*- coding: utf-8 -*-
"""HITL slash commands for tool-call management.

Provides ``/tools``, ``/tool-bg``, and ``/tool-cancel`` as
:class:`CommandSpec` instances registered into the per-Kernel
:class:`SlashCommandRegistry` via lifespan bootstrap.

See ``RUNTIME_REFACTOR_PSEUDOCODE.md`` §8.3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...runtime.slash_command_registry import CommandSpec

if TYPE_CHECKING:
    from .tool_coordinator import ToolCoordinator


def build_tool_command_specs(
    tool_coordinator: "ToolCoordinator",
) -> list[CommandSpec]:
    """Create the three HITL command specs bound to *tool_coordinator*."""

    async def _tools_handler(ctx: Any, _args: str) -> Any:
        from agentscope.message import Msg
        from agentscope.message._block import TextBlock

        root_sid = getattr(ctx, "root_session_id", None)
        active = tool_coordinator.list_active(root_session_id=root_sid)
        if not active:
            text = "No active tool calls."
        else:
            lines = [f"Active tool calls ({len(active)}):"]
            for c in active:
                lines.append(
                    f"- `{c.call_id[:8]}` **{c.tool_name}** [{c.state.value}]",
                )
            text = "\n".join(lines)
        return Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text=text)],
        )

    async def _tool_bg_handler(_ctx: Any, args: str) -> Any:
        from agentscope.message import Msg
        from agentscope.message._block import TextBlock

        call_id = args.strip()
        if not call_id:
            return Msg(
                name="assistant",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text="Usage: `/tool-bg <call_id>`",
                    ),
                ],
            )
        await tool_coordinator.move_to_background(call_id)
        return Msg(
            name="assistant",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=f"Tool call `{call_id[:8]}` moved to background.",
                ),
            ],
        )

    async def _tool_cancel_handler(_ctx: Any, args: str) -> Any:
        from agentscope.message import Msg
        from agentscope.message._block import TextBlock

        call_id = args.strip()
        if not call_id:
            return Msg(
                name="assistant",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text="Usage: `/tool-cancel <call_id>`",
                    ),
                ],
            )
        await tool_coordinator.cancel(call_id)
        return Msg(
            name="assistant",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=f"Tool call `{call_id[:8]}` cancelled.",
                ),
            ],
        )

    return [
        CommandSpec(
            name="tools",
            handler=_tools_handler,
            category="control",
            help_text="List active tool calls in the current session.",
        ),
        CommandSpec(
            name="tool-bg",
            handler=_tool_bg_handler,
            category="control",
            help_text="Move a running tool call to background.",
        ),
        CommandSpec(
            name="tool-cancel",
            handler=_tool_cancel_handler,
            category="control",
            help_text="Cancel a running tool call.",
        ),
    ]


__all__ = ["build_tool_command_specs"]
