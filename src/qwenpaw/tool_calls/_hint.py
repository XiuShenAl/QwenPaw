# -*- coding: utf-8 -*-
"""Construct hint messages for completed background tool calls."""

from __future__ import annotations

from typing import Any


def make_offload_hint_msg(entry: Any) -> Any:
    """Construct a hint Msg for a completed offloaded tool call.

    The hint flattens the finalized response content blocks (TextBlock,
    ImageBlock, etc.) directly into the message so that provider formatters
    treat it as an ordinary assistant message — no ToolResultBlock means no
    orphan ``role=tool`` wire message and no tool-call pairing issues.
    """
    from agentscope.message import Msg, TextBlock

    end = entry.end_state or "unknown"
    notification = TextBlock(
        type="text",
        text=(
            "<system-notification>\n"
            f"Background tool call `{entry.ctx.tool_name}` "
            f"(id={entry.ctx.tool_call_id}) "
            f"completed with state={end}. "
            "Result below.\n"
            "</system-notification>"
        ),
    )
    result_blocks = list(entry.final_response.content or [])
    return Msg(
        name="system",
        role="assistant",
        content=[notification] + result_blocks,
        metadata={
            "hint_type": "tool_completed",
            "tool_call_id": entry.ctx.tool_call_id,
            "tool_name": entry.ctx.tool_name,
            "end_state": end,
        },
    )
