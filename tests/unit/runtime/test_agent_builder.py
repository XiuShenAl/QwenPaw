# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for ``qwenpaw.runtime.builder.AgentBuilder``.

Tool filtering logic has been migrated to
``QwenPawLocalWorkspace.list_tools()`` (see ``tests/unit/workspace/``).
These tests cover the remaining AgentBuilder responsibilities:
``build_toolkit`` integration, ``extra_tools``, ``memory_tools``,
static helpers, and ``_build_middlewares``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.runtime.tool_registry import ToolDescriptor, ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_config(builtin_tools: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        tools=SimpleNamespace(builtin_tools=builtin_tools or {}),
    )


def _desc(
    name: str,
    *,
    enabled_by_default: bool = True,
    requires_modes: tuple[str, ...] = (),
    requires_skills: tuple[str, ...] = (),
) -> ToolDescriptor:
    async def _fn():
        return None

    _fn.__name__ = name
    return ToolDescriptor(
        name=name,
        func=_fn,
        enabled_by_default=enabled_by_default,
        requires_modes=requires_modes,
        requires_skills=requires_skills,
    )


def _registry_with(*descs: ToolDescriptor) -> ToolRegistry:
    reg = ToolRegistry()
    for d in descs:
        reg.register(d)
    return reg


def _make_ctx_with_workspace(registry: ToolRegistry) -> SimpleNamespace:
    """Build a minimal ctx with a workspace backed by *registry*."""
    from qwenpaw.app.workspace.local_workspace import QwenPawLocalWorkspace

    ws = QwenPawLocalWorkspace(
        tool_registry=registry,
        workdir="/tmp/test-ws",
        workspace_id="test",
        default_mcps=[],
        skill_paths=[],
    )
    workspace = SimpleNamespace(local_workspace=ws)
    return SimpleNamespace(workspace=workspace)


# ---------------------------------------------------------------------------
# build_toolkit integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_toolkit_returns_default_tools_via_workspace() -> None:
    reg = _registry_with(_desc("read_file"), _desc("write_file"))
    ctx = _make_ctx_with_workspace(reg)
    builder = AgentBuilder()

    tk = await builder.build_toolkit(_agent_config(), ctx=ctx)
    names = sorted(t.name for t in tk.tool_groups[0].tools)
    assert names == ["read_file", "write_file"]


@pytest.mark.asyncio
async def test_build_toolkit_filters_by_modes_via_workspace() -> None:
    reg = _registry_with(
        _desc("read_file"),
        _desc("ast_search", requires_modes=("coding",)),
    )
    ctx = _make_ctx_with_workspace(reg)
    builder = AgentBuilder()

    tk_inactive = await builder.build_toolkit(_agent_config(), ctx=ctx)
    assert {t.name for t in tk_inactive.tool_groups[0].tools} == {"read_file"}

    tk_active = await builder.build_toolkit(
        _agent_config(),
        active_modes={"coding"},
        ctx=ctx,
    )
    assert {t.name for t in tk_active.tool_groups[0].tools} == {
        "read_file",
        "ast_search",
    }


@pytest.mark.asyncio
async def test_build_toolkit_without_workspace_returns_empty() -> None:
    ctx = SimpleNamespace(workspace=None)
    builder = AgentBuilder()

    tk = await builder.build_toolkit(_agent_config(), ctx=ctx)
    assert len(tk.tool_groups[0].tools) == 0


# ---------------------------------------------------------------------------
# Extras
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extra_tools_are_appended_after_workspace_tools() -> None:
    class _StubTool:
        def __init__(self, name: str) -> None:
            self.name = name

    reg = _registry_with(_desc("read_file"))
    ctx = _make_ctx_with_workspace(reg)
    builder = AgentBuilder()
    extra = [_StubTool("lsp")]

    tk = await builder.build_toolkit(
        _agent_config(),
        extra_tools=extra,
        ctx=ctx,
    )
    names = [t.name for t in tk.tool_groups[0].tools]
    assert names == ["read_file", "lsp"]


@pytest.mark.asyncio
async def test_memory_tools_are_wrapped_and_appended() -> None:
    async def fake_memory_tool():
        return None

    reg = _registry_with(_desc("read_file"))
    ctx = _make_ctx_with_workspace(reg)
    builder = AgentBuilder()

    tk = await builder.build_toolkit(
        _agent_config(),
        agent_id="agent-1",
        memory_tools=[fake_memory_tool],
        ctx=ctx,
    )
    names = [t.name for t in tk.tool_groups[0].tools]
    assert names == ["read_file", "fake_memory_tool"]


# ---------------------------------------------------------------------------
# Phase boundaries
# ---------------------------------------------------------------------------


def test_build_methods_are_implemented() -> None:
    builder = AgentBuilder()
    for method_name in ("build", "build_prompt", "build_model"):
        assert callable(getattr(builder, method_name))


# ---------------------------------------------------------------------------
# _get_local_workspace
# ---------------------------------------------------------------------------


def test_get_local_workspace_no_workspace() -> None:
    ctx = SimpleNamespace()
    assert AgentBuilder._get_local_workspace(ctx) is None


def test_get_local_workspace_returns_workspace() -> None:
    sentinel = object()
    ctx = SimpleNamespace(workspace=SimpleNamespace(local_workspace=sentinel))
    assert AgentBuilder._get_local_workspace(ctx) is sentinel


# ---------------------------------------------------------------------------
# _get_mcp_clients_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_clients_async_no_workspace() -> None:
    ctx = SimpleNamespace()
    result = await AgentBuilder._get_mcp_clients_async(ctx)
    assert result is None


@pytest.mark.asyncio
async def test_mcp_clients_async_no_mcp_manager() -> None:
    ctx = SimpleNamespace(workspace=SimpleNamespace())
    result = await AgentBuilder._get_mcp_clients_async(ctx)
    assert result is None


@pytest.mark.asyncio
async def test_mcp_clients_async_success() -> None:
    from unittest.mock import AsyncMock

    mock_mgr = SimpleNamespace(get_clients=AsyncMock(return_value=["c1"]))
    ctx = SimpleNamespace(workspace=SimpleNamespace(mcp_manager=mock_mgr))
    result = await AgentBuilder._get_mcp_clients_async(ctx)
    assert result == ["c1"]


@pytest.mark.asyncio
async def test_mcp_clients_async_exception_returns_none() -> None:
    from unittest.mock import AsyncMock

    mock_mgr = SimpleNamespace(
        get_clients=AsyncMock(side_effect=RuntimeError("fail")),
    )
    ctx = SimpleNamespace(workspace=SimpleNamespace(mcp_manager=mock_mgr))
    result = await AgentBuilder._get_mcp_clients_async(ctx)
    assert result is None


# ---------------------------------------------------------------------------
# _build_middlewares
# ---------------------------------------------------------------------------


def test_build_middlewares_empty_when_no_context_manager() -> None:
    ctx = SimpleNamespace(workspace=None)
    result = AgentBuilder._build_middlewares(ctx, None)
    assert not result


def test_build_middlewares_includes_context_manager() -> None:
    sentinel = object()
    ctx = SimpleNamespace(
        workspace=SimpleNamespace(context_manager=sentinel),
    )
    result = AgentBuilder._build_middlewares(ctx, None)
    assert result == [sentinel]
