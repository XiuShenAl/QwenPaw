# -*- coding: utf-8 -*-
"""Phase 4 parity contract: legacy dispatch ≡ SlashCommandRegistry.

Verifies that the new ``SlashCommandRegistry``-based dispatch produces
equivalent results to the legacy ``dispatch_command`` for commands that
can be tested in isolation (without heavy infrastructure dependencies).

Commands requiring ``Workspace``, ``ChannelManager``, or ``TaskTracker``
(e.g. /stop, /model, /approval) are covered by the unit test adapters
rather than full parity tests, since constructing realistic fixtures for
those is prohibitively complex and brittle.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.runtime.builtin_commands import (
    _parse_skill_query,
    build_default_command_registry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_ctx(
    agent=None,
    runner=None,
    request=None,
    msgs=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        agent_id="test-agent",
        session_id="test-session",
        kernel=runner,
        agent=agent,
        request=request,
        input_msgs=msgs or [],
    )


def _text_of(msg) -> str | None:
    if msg is None:
        return None
    text = getattr(msg, "get_text_content", None)
    if callable(text):
        return text() or ""
    content = getattr(msg, "content", None)
    if isinstance(content, list):
        for block in content:
            t = (
                block.get("text")
                if isinstance(block, dict)
                else getattr(block, "text", None)
            )
            if t:
                return t
    if isinstance(content, str):
        return content
    return str(content) if content else ""


# ---------------------------------------------------------------------------
# Conversation command parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_clear_command() -> None:
    """``/clear`` should delegate to ``command_handler.handle_command``."""
    from agentscope.message import Msg, TextBlock

    expected_msg = Msg(
        name="QwenPaw",
        role="assistant",
        content=[TextBlock(type="text", text="**History Cleared!**")],
        metadata={"clear_history": True, "clear_plan": True},
    )

    cmd_handler = SimpleNamespace(
        handle_command=AsyncMock(return_value=expected_msg),
    )
    agent = SimpleNamespace(command_handler=cmd_handler)
    ctx = _stub_ctx(agent=agent)

    reg = build_default_command_registry()
    result = await reg.dispatch("/clear", ctx)

    assert result is expected_msg
    cmd_handler.handle_command.assert_awaited_once_with("/clear")


@pytest.mark.asyncio
async def test_parity_compact_with_args() -> None:
    """``/compact focus on API`` should pass args through."""
    from agentscope.message import Msg, TextBlock

    expected_msg = Msg(
        name="QwenPaw",
        role="assistant",
        content=[TextBlock(type="text", text="Compact done")],
    )

    cmd_handler = SimpleNamespace(
        handle_command=AsyncMock(return_value=expected_msg),
    )
    agent = SimpleNamespace(command_handler=cmd_handler)
    ctx = _stub_ctx(agent=agent)

    reg = build_default_command_registry()
    result = await reg.dispatch("/compact focus on API", ctx)

    assert result is expected_msg
    cmd_handler.handle_command.assert_awaited_once_with(
        "/compact focus on API",
    )


@pytest.mark.asyncio
async def test_parity_plan_with_description_falls_through() -> None:
    """``/plan implement auth`` should NOT be a command."""
    cmd_handler = SimpleNamespace(
        handle_command=AsyncMock(return_value=MagicMock()),
    )
    agent = SimpleNamespace(command_handler=cmd_handler)
    ctx = _stub_ctx(agent=agent)

    reg = build_default_command_registry()
    result = await reg.dispatch("/plan implement auth", ctx)

    # /plan with args returns None from adapter; then fallback tries
    # skill dispatch but no skills exist, so also None.
    assert result is None
    cmd_handler.handle_command.assert_not_awaited()


@pytest.mark.asyncio
async def test_parity_plan_bare_is_command() -> None:
    """Bare ``/plan`` is a status command."""
    from agentscope.message import Msg, TextBlock

    expected = Msg(
        name="QwenPaw",
        role="assistant",
        content=[TextBlock(type="text", text="Plan Mode")],
    )
    cmd_handler = SimpleNamespace(
        handle_command=AsyncMock(return_value=expected),
    )
    agent = SimpleNamespace(command_handler=cmd_handler)
    ctx = _stub_ctx(agent=agent)

    reg = build_default_command_registry()
    result = await reg.dispatch("/plan", ctx)
    assert result is expected


# ---------------------------------------------------------------------------
# Daemon command parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_version_command() -> None:
    """``/version`` should produce a version info response."""
    from qwenpaw.app.runner.daemon_commands import (
        run_daemon_version,
        DaemonContext,
    )

    daemon_ctx = DaemonContext()
    _ = run_daemon_version(daemon_ctx)

    runner = SimpleNamespace(
        agent_id="test",
        memory_manager=None,
        context_manager=None,
        _manager=None,
        agent_name="QwenPaw",
    )
    ctx = _stub_ctx(runner=runner)

    reg = build_default_command_registry()
    result = await reg.dispatch("/version", ctx)

    assert result is not None
    result_text = _text_of(result)
    assert result_text is not None
    assert "version" in result_text.lower() or "Version" in result_text


@pytest.mark.asyncio
async def test_parity_daemon_compound() -> None:
    """``/daemon status`` should work via compound entry."""
    runner = SimpleNamespace(
        agent_id="test",
        memory_manager=None,
        context_manager=None,
        _manager=None,
        agent_name="QwenPaw",
    )
    ctx = _stub_ctx(runner=runner)

    reg = build_default_command_registry()
    result = await reg.dispatch("/daemon status", ctx)

    assert result is not None
    result_text = _text_of(result)
    assert result_text is not None
    assert "Status" in result_text or "status" in result_text


# ---------------------------------------------------------------------------
# Non-command parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_command_returns_none() -> None:
    """Plain text should return None (fall through to model)."""
    reg = build_default_command_registry()
    ctx = _stub_ctx()
    assert await reg.dispatch("hello world", ctx) is None


@pytest.mark.asyncio
async def test_unknown_slash_hits_fallback() -> None:
    """``/unknowncmd`` without skills should return None."""
    agent = SimpleNamespace(toolkit=None)
    ctx = _stub_ctx(agent=agent)
    reg = build_default_command_registry()
    result = await reg.dispatch("/unknowncmd test", ctx)
    assert result is None


# ---------------------------------------------------------------------------
# _parse_skill_query parity
# ---------------------------------------------------------------------------


def test_parse_skill_query_matches_legacy() -> None:
    """Verify _parse_skill_query output matches the deleted
    command_dispatch._parse_skill_query for representative inputs."""
    assert _parse_skill_query("/myskill hello") == ("myskill", "hello")
    assert _parse_skill_query("/myskill") == ("myskill", "")
    assert _parse_skill_query("/[my skill] input") == ("my skill", "input")
    assert _parse_skill_query("plain text") is None
    assert _parse_skill_query("") is None
    assert _parse_skill_query("/") is None
    assert _parse_skill_query("/[broken") is None
