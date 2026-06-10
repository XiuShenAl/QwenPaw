# -*- coding: utf-8 -*-
"""Unit tests for ``QwenPawLocalWorkspace.list_tools()``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.workspace.local_workspace import QwenPawLocalWorkspace
from qwenpaw.runtime.tool_registry import ToolDescriptor, ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _builtin_cfg(enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(enabled=enabled)


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
    requires_features: tuple[str, ...] = (),
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
        requires_features=requires_features,
    )


def _registry_with(*descs: ToolDescriptor) -> ToolRegistry:
    reg = ToolRegistry()
    for d in descs:
        reg.register(d)
    return reg


def _workspace(registry: ToolRegistry) -> QwenPawLocalWorkspace:
    return QwenPawLocalWorkspace(
        tool_registry=registry,
        workdir="/tmp/test-ws",
        workspace_id="test",
        default_mcps=[],
        skill_paths=[],
    )


# ---------------------------------------------------------------------------
# Default (no-arg) selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_returns_default_enabled_tools() -> None:
    reg = _registry_with(
        _desc("read_file"),
        _desc("write_file"),
        _desc("append_file", enabled_by_default=False),
    )
    ws = _workspace(reg)
    tools = await ws.list_tools()
    names = sorted(t.name for t in tools)
    assert names == ["read_file", "write_file"]


# ---------------------------------------------------------------------------
# Config gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_disabled_tool_is_dropped() -> None:
    reg = _registry_with(_desc("read_file"), _desc("write_file"))
    ws = _workspace(reg)
    cfg = _agent_config({"read_file": _builtin_cfg(False)})

    tools = await ws.list_tools(agent_config=cfg)
    names = [t.name for t in tools]
    assert names == ["write_file"]


@pytest.mark.asyncio
async def test_explicit_plugin_enable_preserves_defaults() -> None:
    reg = _registry_with(
        _desc("read_file"),
        _desc("write_file"),
        _desc("append_file", enabled_by_default=False),
    )
    ws = _workspace(reg)
    cfg = _agent_config({"append_file": _builtin_cfg(True)})

    tools = await ws.list_tools(agent_config=cfg)
    names = sorted(t.name for t in tools)
    assert names == ["append_file", "read_file", "write_file"]


# ---------------------------------------------------------------------------
# Mode / skill / feature gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_requires_modes_gate() -> None:
    reg = _registry_with(
        _desc("read_file"),
        _desc("ast_search", requires_modes=("coding",)),
    )
    ws = _workspace(reg)

    without = await ws.list_tools()
    assert {t.name for t in without} == {"read_file"}

    with_mode = await ws.list_tools(active_modes={"coding"})
    assert {t.name for t in with_mode} == {"read_file", "ast_search"}


@pytest.mark.asyncio
async def test_requires_skills_gate() -> None:
    reg = _registry_with(
        _desc("read_file"),
        _desc("materialize_skill", requires_skills=("make-skill",)),
    )
    ws = _workspace(reg)

    without = await ws.list_tools()
    assert {t.name for t in without} == {"read_file"}

    with_skill = await ws.list_tools(active_skills={"make-skill"})
    assert {t.name for t in with_skill} == {
        "read_file",
        "materialize_skill",
    }


@pytest.mark.asyncio
async def test_requires_features_gate() -> None:
    reg = _registry_with(
        _desc("read_file"),
        _desc("beta_tool", requires_features=("beta",)),
    )
    ws = _workspace(reg)

    without = await ws.list_tools()
    assert {t.name for t in without} == {"read_file"}

    with_feat = await ws.list_tools(enabled_features={"beta"})
    assert {t.name for t in with_feat} == {"read_file", "beta_tool"}


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_guarded_function_tool_instances() -> None:
    from agentscope.tool import ToolBase

    reg = _registry_with(_desc("read_file"))
    ws = _workspace(reg)
    tools = await ws.list_tools()

    assert len(tools) == 1
    assert isinstance(tools[0], ToolBase)
