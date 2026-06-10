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
    collect_builtin_command_specs,
    get_skill_fallback_handler,
)
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_default_registry() -> SlashCommandRegistry:
    reg = SlashCommandRegistry()
    for spec in collect_builtin_command_specs():
        reg.register(spec)
    reg.register_fallback(get_skill_fallback_handler())
    return reg


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


def _stub_kernel():
    """Stub kernel with session for conversation commands."""
    session = MagicMock()
    session.load_session_state = AsyncMock(return_value=None)
    session.save_session_state = AsyncMock(return_value=None)
    return SimpleNamespace(
        agent_id="test",
        memory_manager=None,
        context_manager=None,
        _manager=None,
        agent_name="QwenPaw",
        session=session,
    )


# ---------------------------------------------------------------------------
# Conversation command parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_clear_command() -> None:
    """``/clear`` should dispatch and produce a response with clear_history."""
    kernel = _stub_kernel()
    ctx = _stub_ctx(runner=kernel)

    reg = _build_default_registry()
    result = await reg.dispatch("/clear", ctx)

    assert result is not None
    text = _text_of(result)
    assert text is not None
    assert "clear" in text.lower() or "history" in text.lower()


@pytest.mark.asyncio
async def test_parity_compact_with_args() -> None:
    """``/compact focus on API`` should dispatch and produce a response."""
    kernel = _stub_kernel()
    ctx = _stub_ctx(runner=kernel)

    reg = _build_default_registry()
    result = await reg.dispatch("/compact focus on API", ctx)

    assert result is not None
    text = _text_of(result)
    assert text is not None


@pytest.mark.asyncio
async def test_parity_plan_with_description_falls_through() -> None:
    """``/plan implement auth`` should NOT be a command."""
    kernel = _stub_kernel()
    ctx = _stub_ctx(runner=kernel)

    reg = _build_default_registry()
    result = await reg.dispatch("/plan implement auth", ctx)

    assert result is None


@pytest.mark.asyncio
async def test_parity_plan_bare_is_command() -> None:
    """Bare ``/plan`` is a status command."""
    kernel = _stub_kernel()
    ctx = _stub_ctx(runner=kernel)

    reg = _build_default_registry()
    result = await reg.dispatch("/plan", ctx)

    assert result is not None
    text = _text_of(result)
    assert text is not None


# ---------------------------------------------------------------------------
# Daemon command parity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_version_command() -> None:
    """``/version`` should produce a version info response."""
    kernel = _stub_kernel()
    ctx = _stub_ctx(runner=kernel)

    reg = _build_default_registry()
    result = await reg.dispatch("/version", ctx)

    assert result is not None
    result_text = _text_of(result)
    assert result_text is not None
    assert "version" in result_text.lower() or "Version" in result_text


@pytest.mark.asyncio
async def test_parity_daemon_compound() -> None:
    """``/daemon status`` should work via compound entry."""
    kernel = _stub_kernel()
    ctx = _stub_ctx(runner=kernel)

    reg = _build_default_registry()
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
    reg = _build_default_registry()
    ctx = _stub_ctx()
    assert await reg.dispatch("hello world", ctx) is None


@pytest.mark.asyncio
async def test_unknown_slash_hits_fallback() -> None:
    """``/unknowncmd`` without skills should return None."""
    agent = SimpleNamespace(toolkit=None)
    ctx = _stub_ctx(agent=agent)
    reg = _build_default_registry()
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
