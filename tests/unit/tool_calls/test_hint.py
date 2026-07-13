# -*- coding: utf-8 -*-
"""Tests for completed background tool-call hint messages."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from agentscope.message import TextBlock, ToolCallBlock, ToolResultBlock
from agentscope.tool import ToolResponse

from qwenpaw.tool_calls._hint import make_offload_hint_msg


def _make_entry(
    *,
    tool_call_id: str = "call-bg",
    tool_name: str = "slow_tool",
    end_state: str = "success",
    content: list | None = None,
):
    if content is None:
        content = [TextBlock(type="text", text="done")]
    response = ToolResponse(
        content=content,
        id=tool_call_id,
    )
    return SimpleNamespace(
        end_state=end_state,
        ctx=SimpleNamespace(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
        ),
        final_response=response,
    )


class TestHintMessageStructure:
    """Verify that the hint message contains only ordinary content blocks."""

    def test_no_tool_blocks(self) -> None:
        hint = make_offload_hint_msg(_make_entry())
        for block in hint.content:
            assert not isinstance(block, (ToolCallBlock, ToolResultBlock))

    def test_role_is_assistant(self) -> None:
        hint = make_offload_hint_msg(_make_entry())
        assert hint.role == "assistant"

    def test_notification_text_contains_tool_info(self) -> None:
        hint = make_offload_hint_msg(
            _make_entry(
                tool_call_id="call-123",
                tool_name="web_search",
                end_state="success",
            ),
        )
        notification = hint.content[0]
        assert isinstance(notification, TextBlock)
        assert "web_search" in notification.text
        assert "call-123" in notification.text
        assert "success" in notification.text

    def test_result_blocks_are_flattened(self) -> None:
        result_blocks = [
            TextBlock(type="text", text="first"),
            TextBlock(type="text", text="second"),
        ]
        hint = make_offload_hint_msg(_make_entry(content=result_blocks))
        assert len(hint.content) == 3
        assert hint.content[1].text == "first"
        assert hint.content[2].text == "second"

    def test_empty_result(self) -> None:
        hint = make_offload_hint_msg(_make_entry(content=[]))
        assert len(hint.content) == 1
        assert isinstance(hint.content[0], TextBlock)

    def test_none_result(self) -> None:
        entry = _make_entry()
        entry.final_response.content = None
        hint = make_offload_hint_msg(entry)
        assert len(hint.content) == 1


class TestHintFormatterCompatibility:
    """Verify that formatters produce ordinary assistant wire messages."""

    @pytest.mark.asyncio
    async def test_openai_format_no_tool_messages(self) -> None:
        from agentscope.formatter import OpenAIChatFormatter

        hint = make_offload_hint_msg(_make_entry())
        formatted = await OpenAIChatFormatter().format([hint])
        assert len(formatted) == 1
        assert formatted[0]["role"] == "assistant"
        assert "tool_calls" not in formatted[0]

    @pytest.mark.asyncio
    async def test_anthropic_format_no_tool_messages(self) -> None:
        from agentscope.formatter import AnthropicChatFormatter

        hint = make_offload_hint_msg(_make_entry())
        formatted = await AnthropicChatFormatter().format([hint])
        assert len(formatted) == 1
        assert formatted[0]["role"] == "assistant"
        for block in formatted[0].get("content", []):
            assert block.get("type") != "tool_use"

    @pytest.mark.asyncio
    async def test_gemini_format_no_tool_messages(self) -> None:
        from agentscope.formatter import GeminiChatFormatter

        hint = make_offload_hint_msg(_make_entry())
        formatted = await GeminiChatFormatter().format([hint])
        assert len(formatted) == 1
        assert formatted[0]["role"] == "model"
        for part in formatted[0].get("parts", []):
            assert "function_call" not in part
