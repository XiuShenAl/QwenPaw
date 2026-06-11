# -*- coding: utf-8 -*-
"""HITL slash commands for tool-call management.

Provides ``/tools``, ``/tool-bg``, and ``/tool-cancel`` as
:class:`CommandSpec` instances registered into the per-Kernel
:class:`SlashCommandRegistry` via lifespan bootstrap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...runtime.slash_command_registry import CommandSpec

if TYPE_CHECKING:
    from ...tool_calls import ToolCoordinator


def build_tool_command_specs(
    tool_coordinator: "ToolCoordinator",
) -> list[CommandSpec]:
    """Create the three HITL command specs bound to *tool_coordinator*."""

    async def _tools_handler(ctx: Any, _args: str) -> Any:
        from agentscope.message import Msg
        from agentscope.message._block import TextBlock

        root_sid = getattr(ctx, "root_session_id", None)
        active = tool_coordinator.list_entries(session_id=root_sid)
        if not active:
            text = "No active tool calls."
        else:
            lines = [f"Active tool calls ({len(active)}):"]
            for e in active:
                elapsed = ""
                try:
                    import asyncio

                    elapsed_s = (
                        asyncio.get_running_loop().time() - e.ctx.started_at
                    )
                    elapsed = f" {elapsed_s:.1f}s"
                except Exception:
                    pass
                lines.append(
                    f"- `{e.ctx.tool_call_id[:8]}` "
                    f"**{e.ctx.tool_name}** [{e.status.value}]{elapsed}",
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
        from ...tool_calls import OffloadReason

        ok = await tool_coordinator.request_offload(
            call_id,
            reason=OffloadReason.USER,
        )
        text = (
            f"Tool call `{call_id[:8]}` moved to background."
            if ok
            else f"Tool call `{call_id[:8]}` not found or already offloaded."
        )
        return Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text=text)],
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
        from ...tool_calls import CancelReason

        ok = await tool_coordinator.cancel(
            call_id,
            reason=CancelReason.USER,
        )
        text = (
            f"Tool call `{call_id[:8]}` cancelled."
            if ok
            else f"Tool call `{call_id[:8]}` not found."
        )
        return Msg(
            name="assistant",
            role="assistant",
            content=[TextBlock(type="text", text=text)],
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
