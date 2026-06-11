# -*- coding: utf-8 -*-
"""Unit tests for HITL slash commands (``_builtin_tool_commands``)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.app_services._builtin_tool_commands import (
    build_tool_command_specs,
)
from qwenpaw.tool_calls import ToolCallEntry, ToolCallStatus
from qwenpaw.tool_calls._context import ToolCallContext
from qwenpaw.tool_calls._stream import ToolStream


def _stub_coordinator() -> MagicMock:
    tc = MagicMock()
    tc.list_entries = MagicMock(return_value=[])
    tc.request_offload = AsyncMock(return_value=True)
    tc.cancel = AsyncMock(return_value=True)
    return tc


def _make_entry(
    tool_call_id: str = "abc12345",
    tool_name: str = "shell",
    status: ToolCallStatus = ToolCallStatus.RUNNING,
) -> ToolCallEntry:
    ctx = ToolCallContext(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        session_id="s1",
        agent_id="a1",
        root_session_id="rs1",
        started_at=asyncio.get_event_loop().time(),
        deadline=None,
        cancel_event=asyncio.Event(),
    )
    return ToolCallEntry(
        ctx=ctx,
        stream=ToolStream(tool_call_id=tool_call_id, session_id="s1"),
        final_response=None,
        status=status,
    )


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
    tc.list_entries.return_value = [_make_entry()]
    specs = build_tool_command_specs(tc)
    tools_spec = next(s for s in specs if s.name == "tools")

    ctx = SimpleNamespace(root_session_id=None)
    msg = await tools_spec.handler(ctx, "")
    assert "abc12345" in msg.content[0].text
    assert "shell" in msg.content[0].text


@pytest.mark.asyncio
async def test_tool_bg_calls_request_offload() -> None:
    tc = _stub_coordinator()
    specs = build_tool_command_specs(tc)
    bg_spec = next(s for s in specs if s.name == "tool-bg")

    ctx = SimpleNamespace()
    msg = await bg_spec.handler(ctx, "abc123")
    tc.request_offload.assert_awaited_once()
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
    tc.cancel.assert_awaited_once()
    assert "cancelled" in msg.content[0].text.lower()
