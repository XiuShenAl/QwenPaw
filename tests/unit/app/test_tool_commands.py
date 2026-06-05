# -*- coding: utf-8 -*-
"""Unit tests for HITL slash commands (``_builtin_tool_commands``)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.app_services._builtin_tool_commands import (
    build_tool_command_specs,
)
from qwenpaw.app.app_services.tool_coordinator import (
    ToolCall,
    ToolCallState,
)


def _stub_coordinator() -> MagicMock:
    tc = MagicMock()
    tc.list_active = MagicMock(return_value=[])
    tc.move_to_background = AsyncMock()
    tc.cancel = AsyncMock()
    return tc


def test_builds_three_command_specs() -> None:
    specs = build_tool_command_specs(_stub_coordinator())
    names = {s.name for s in specs}
    assert names == {"tools", "tool-bg", "tool-cancel"}


@pytest.mark.asyncio
async def test_tools_command_no_active() -> None:
    tc = _stub_coordinator()
    specs = build_tool_command_specs(tc)
    tools_spec = next(s for s in specs if s.name == "tools")

    ctx = SimpleNamespace(root_session_id=None)
    msg = await tools_spec.handler(ctx, "")
    assert "No active tool calls" in msg.content[0].text


@pytest.mark.asyncio
async def test_tools_command_with_active() -> None:
    tc = _stub_coordinator()
    tc.list_active.return_value = [
        ToolCall(
            call_id="abc12345",
            agent_id="a1",
            tool_name="shell",
            state=ToolCallState.RUNNING,
        ),
    ]
    specs = build_tool_command_specs(tc)
    tools_spec = next(s for s in specs if s.name == "tools")

    ctx = SimpleNamespace(root_session_id=None)
    msg = await tools_spec.handler(ctx, "")
    assert "abc12345" in msg.content[0].text
    assert "shell" in msg.content[0].text


@pytest.mark.asyncio
async def test_tool_bg_calls_move_to_background() -> None:
    tc = _stub_coordinator()
    specs = build_tool_command_specs(tc)
    bg_spec = next(s for s in specs if s.name == "tool-bg")

    ctx = SimpleNamespace()
    msg = await bg_spec.handler(ctx, "abc123")
    tc.move_to_background.assert_awaited_once_with("abc123")
    assert "background" in msg.content[0].text.lower()


@pytest.mark.asyncio
async def test_tool_bg_no_arg_returns_usage() -> None:
    tc = _stub_coordinator()
    specs = build_tool_command_specs(tc)
    bg_spec = next(s for s in specs if s.name == "tool-bg")

    ctx = SimpleNamespace()
    msg = await bg_spec.handler(ctx, "")
    assert "Usage" in msg.content[0].text


@pytest.mark.asyncio
async def test_tool_cancel_calls_cancel() -> None:
    tc = _stub_coordinator()
    specs = build_tool_command_specs(tc)
    cancel_spec = next(s for s in specs if s.name == "tool-cancel")

    ctx = SimpleNamespace()
    msg = await cancel_spec.handler(ctx, "xyz789")
    tc.cancel.assert_awaited_once_with("xyz789")
    assert "cancelled" in msg.content[0].text.lower()
