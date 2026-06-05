# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.runtime.builder.AgentBuilder``.

The builder's job is to translate an ``agent_config`` + per-request
gates (modes / skills / features / allowed / denied) into a populated
:class:`Toolkit` by way of :class:`ToolRegistry.filter`. These tests
exercise the bridge against a hand-built registry — they're independent
of the real ``discover_builtin_tool_funcs`` so a future tool addition
can't accidentally make them green.
"""

from __future__ import annotations

from types import SimpleNamespace

from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.runtime.tool_registry import ToolDescriptor, ToolRegistry


def _builtin_cfg(enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(enabled=enabled)


def _agent_config(builtin_tools: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        tools=SimpleNamespace(builtin_tools=builtin_tools or {}),
    )


def _registry_with(*descs: ToolDescriptor) -> ToolRegistry:
    reg = ToolRegistry()
    for d in descs:
        reg.register(d)
    return reg


def _desc(
    name: str,
    *,
    enabled_by_default: bool = True,
    requires_modes: tuple[str, ...] = (),
    requires_skills: tuple[str, ...] = (),
) -> ToolDescriptor:
    # GuardedFunctionTool derives ``.name`` from ``func.__name__``, so each
    # descriptor needs its own named function for the toolkit assertions to
    # read meaningfully.
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


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_default_config_picks_default_enabled_tools_only() -> None:
    reg = _registry_with(
        _desc("read_file"),
        _desc("write_file"),
        _desc("append_file", enabled_by_default=False),  # plugin
    )
    builder = AgentBuilder(tool_registry=reg)

    tk = builder.build_toolkit(_agent_config())
    names = sorted(t.name for t in tk.tool_groups[0].tools)
    assert names == ["read_file", "write_file"]


def test_explicit_plugin_enable_does_not_drop_other_defaults() -> None:
    """Regression guard for the bridge — Phase 2 §3.2 pseudocode trap."""
    reg = _registry_with(
        _desc("read_file"),
        _desc("write_file"),
        _desc("append_file", enabled_by_default=False),
    )
    builder = AgentBuilder(tool_registry=reg)
    cfg = _agent_config({"append_file": _builtin_cfg(True)})

    tk = builder.build_toolkit(cfg)
    names = sorted(t.name for t in tk.tool_groups[0].tools)
    # All three should show up: the two hardcoded defaults + the
    # explicitly opted-in plugin tool.
    assert names == ["append_file", "read_file", "write_file"]


def test_config_disabled_tool_is_dropped() -> None:
    reg = _registry_with(_desc("read_file"), _desc("write_file"))
    builder = AgentBuilder(tool_registry=reg)
    cfg = _agent_config({"read_file": _builtin_cfg(False)})

    tk = builder.build_toolkit(cfg)
    names = [t.name for t in tk.tool_groups[0].tools]
    assert names == ["write_file"]


def test_requires_modes_gate_is_honoured() -> None:
    reg = _registry_with(
        _desc("read_file"),
        _desc("ast_search", requires_modes=("coding",)),
    )
    builder = AgentBuilder(tool_registry=reg)

    inactive = builder.build_toolkit(_agent_config())
    assert {t.name for t in inactive.tool_groups[0].tools} == {"read_file"}

    active = builder.build_toolkit(
        _agent_config(),
        active_modes={"coding"},
    )
    assert {t.name for t in active.tool_groups[0].tools} == {
        "read_file",
        "ast_search",
    }


def test_requires_skills_gate_is_honoured() -> None:
    reg = _registry_with(
        _desc("read_file"),
        _desc("materialize_skill", requires_skills=("make-skill",)),
    )
    builder = AgentBuilder(tool_registry=reg)

    without = builder.build_toolkit(_agent_config())
    assert {t.name for t in without.tool_groups[0].tools} == {"read_file"}

    with_skill = builder.build_toolkit(
        _agent_config(),
        effective_skills={"make-skill"},
    )
    assert {t.name for t in with_skill.tool_groups[0].tools} == {
        "read_file",
        "materialize_skill",
    }


# ---------------------------------------------------------------------------
# Extras
# ---------------------------------------------------------------------------


def test_extra_tools_are_appended_after_registry_tools() -> None:
    """Coding Mode's dynamic LSP tool comes in via ``extra_tools``."""

    class _StubTool:
        def __init__(self, name: str) -> None:
            self.name = name

    reg = _registry_with(_desc("read_file"))
    builder = AgentBuilder(tool_registry=reg)
    extra = [_StubTool("lsp")]

    tk = builder.build_toolkit(_agent_config(), extra_tools=extra)
    names = [t.name for t in tk.tool_groups[0].tools]
    # Order: registry first, extras second.
    assert names == ["read_file", "lsp"]


def test_memory_tools_are_wrapped_and_appended() -> None:
    """Memory manager tools wrap in GuardedFunctionTool just like builtins."""

    async def fake_memory_tool():
        return None

    reg = _registry_with(_desc("read_file"))
    builder = AgentBuilder(tool_registry=reg)

    tk = builder.build_toolkit(
        _agent_config(),
        agent_id="agent-1",
        memory_tools=[fake_memory_tool],
    )
    names = [t.name for t in tk.tool_groups[0].tools]
    assert names == ["read_file", "fake_memory_tool"]


# ---------------------------------------------------------------------------
# Phase boundaries
# ---------------------------------------------------------------------------


def test_build_methods_are_implemented() -> None:
    """build/build_prompt/build_model exist."""
    builder = AgentBuilder(tool_registry=ToolRegistry())
    for method_name in ("build", "build_prompt", "build_model"):
        assert callable(getattr(builder, method_name))
