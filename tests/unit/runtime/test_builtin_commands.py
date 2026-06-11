# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.runtime.builtin_commands``.

Each adapter group is tested by constructing a stub ``ctx`` that
mimics ``HookContext`` and verifying delegation to the underlying
handler.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.runtime.builtin_commands import (
    _collect_conversation_specs,
    _collect_control_specs,
    _collect_daemon_specs,
    _parse_skill_query,
    _skill_fallback_handler,
    collect_builtin_command_specs,
    get_skill_fallback_handler,
)
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_ctx(**kwargs) -> SimpleNamespace:
    defaults = {
        "agent_id": "test-agent",
        "session_id": "test-session",
        "workspace": None,
        "agent": None,
        "request": None,
        "input_msgs": [],
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _build_registry() -> SlashCommandRegistry:
    """Build a fully populated SlashCommandRegistry."""
    reg = SlashCommandRegistry()
    for spec in collect_builtin_command_specs():
        reg.register(spec)
    reg.register_fallback(get_skill_fallback_handler())
    return reg


# ---------------------------------------------------------------------------
# collect_builtin_command_specs
# ---------------------------------------------------------------------------


def test_registry_has_all_command_names() -> None:
    """Registry contains all command names."""
    reg = _build_registry()
    names = reg.names()

    # Conversation commands (11)
    for cmd in (
        "compact",
        "new",
        "clear",
        "history",
        "compact_str",
        "summarize_status",
        "message",
        "dump_history",
        "load_history",
        "proactive",
        "plan",
    ):
        assert cmd in names, f"conversation command /{cmd} not registered"

    # Daemon commands (5 + daemon compound + reload_config alias)
    for cmd in (
        "restart",
        "status",
        "version",
        "logs",
        "reload-config",
        "daemon",
    ):
        assert cmd in names, f"daemon command /{cmd} not registered"
    assert "reload_config" in names, "reload_config alias not registered"

    # Control commands (6 = stop, model, approval, approve, deny, skills)
    for cmd in ("stop", "model", "approval", "approve", "deny", "skills"):
        assert cmd in names, f"control command /{cmd} not registered"


def test_registry_command_count() -> None:
    reg = _build_registry()
    names = reg.names()
    # 11 conversation + 7 daemon (restart, status, version, logs,
    # reload-config, reload_config, daemon) + 6 control = 24+ total
    assert len(names) >= 24


# ---------------------------------------------------------------------------
# Conversation adapters
# ---------------------------------------------------------------------------


def test_conversation_specs_cover_all_system_commands() -> None:
    specs = _collect_conversation_specs()
    names = {s.name for s in specs}
    expected = {
        "compact",
        "new",
        "clear",
        "history",
        "compact_str",
        "summarize_status",
        "message",
        "dump_history",
        "load_history",
        "proactive",
        "plan",
    }
    assert names == expected


def test_conversation_specs_have_correct_category() -> None:
    specs = _collect_conversation_specs()
    for spec in specs:
        assert spec.category == "conversation"


@pytest.mark.asyncio
async def test_plan_with_args_returns_none() -> None:
    """``/plan description`` is NOT a command — should fall through."""
    specs = _collect_conversation_specs()
    plan_spec = next(s for s in specs if s.name == "plan")
    ctx = _stub_ctx(workspace=SimpleNamespace(session=None))
    result = await plan_spec.handler(ctx, "implement auth flow")
    assert result is None


@pytest.mark.asyncio
async def test_conversation_adapter_no_workspace_returns_none() -> None:
    specs = _collect_conversation_specs()
    clear_spec = next(s for s in specs if s.name == "clear")
    ctx = _stub_ctx()
    result = await clear_spec.handler(ctx, "")
    assert result is None


# ---------------------------------------------------------------------------
# Daemon adapters
# ---------------------------------------------------------------------------


def test_daemon_specs_count_and_categories() -> None:
    specs = _collect_daemon_specs()
    assert len(specs) == 6  # 5 subcommands + 1 /daemon compound
    for spec in specs:
        assert spec.category == "daemon"


def test_daemon_reload_config_has_alias() -> None:
    specs = _collect_daemon_specs()
    rc = next(s for s in specs if s.name == "reload-config")
    assert "reload_config" in rc.aliases


@pytest.mark.asyncio
async def test_daemon_adapter_delegates_to_handler() -> None:
    specs = _collect_daemon_specs()
    version_spec = next(s for s in specs if s.name == "version")

    with patch(
        "qwenpaw.app.runner.daemon_commands.DaemonCommandHandlerMixin",
        autospec=False,
    ) as MockMixin:
        mock_msg = MagicMock()
        instance = MagicMock()
        instance.handle_daemon_command = AsyncMock(return_value=mock_msg)
        MockMixin.return_value = instance

        workspace = SimpleNamespace(
            agent_id="test",
            memory_manager=None,
            context_manager=None,
            _manager=None,
        )
        ctx = _stub_ctx(workspace=workspace)
        result = await version_spec.handler(ctx, "")

        assert result is mock_msg
        instance.handle_daemon_command.assert_awaited_once()


# ---------------------------------------------------------------------------
# Control adapters
# ---------------------------------------------------------------------------


def test_control_specs_count_and_categories() -> None:
    specs = _collect_control_specs()
    names = {s.name for s in specs}
    assert "stop" in names
    assert "model" in names
    assert "approval" in names
    assert "approve" in names
    assert "deny" in names
    assert "skills" in names
    for spec in specs:
        assert spec.category == "control"


# ---------------------------------------------------------------------------
# Skill fallback (_parse_skill_query)
# ---------------------------------------------------------------------------


def test_parse_skill_simple() -> None:
    result = _parse_skill_query("/myskill hello world")
    assert result == ("myskill", "hello world")


def test_parse_skill_no_input() -> None:
    result = _parse_skill_query("/myskill")
    assert result == ("myskill", "")


def test_parse_skill_bracket_syntax() -> None:
    result = _parse_skill_query("/[my skill] some input")
    assert result == ("my skill", "some input")


def test_parse_skill_empty_returns_none() -> None:
    assert _parse_skill_query("") is None
    assert _parse_skill_query("hello") is None
    assert _parse_skill_query("/") is None


def test_parse_skill_bracket_no_close_returns_none() -> None:
    assert _parse_skill_query("/[broken name") is None


@pytest.mark.asyncio
async def test_skill_fallback_no_workspace_returns_none() -> None:
    ctx = _stub_ctx()
    result = await _skill_fallback_handler("/someskill test", ctx)
    assert result is None


# ---------------------------------------------------------------------------
# Full registry dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_dispatch_unknown_returns_none() -> None:
    reg = _build_registry()
    ctx = _stub_ctx()
    result = await reg.dispatch("plain text", ctx)
    assert result is None


@pytest.mark.asyncio
async def test_registry_resolves_conversation_command() -> None:
    reg = _build_registry()
    match = reg.resolve("/clear")
    assert match is not None
    spec, _args = match
    assert spec.name == "clear"
    assert spec.category == "conversation"


@pytest.mark.asyncio
async def test_registry_resolves_daemon_command() -> None:
    reg = _build_registry()
    match = reg.resolve("/version")
    assert match is not None
    spec, _args = match
    assert spec.name == "version"
    assert spec.category == "daemon"


@pytest.mark.asyncio
async def test_registry_resolves_control_command() -> None:
    reg = _build_registry()
    match = reg.resolve("/stop session=123")
    assert match is not None
    spec, args = match
    assert spec.name == "stop"
    assert spec.category == "control"
    assert args == "session=123"


@pytest.mark.asyncio
async def test_registry_resolves_daemon_alias() -> None:
    reg = _build_registry()
    match = reg.resolve("/reload_config")
    assert match is not None
    spec, _ = match
    assert spec.name == "reload-config"
