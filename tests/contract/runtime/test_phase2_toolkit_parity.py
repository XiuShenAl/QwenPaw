# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Phase 2 parity contract: legacy ``_create_toolkit`` ≡ ``AgentBuilder``.

Per ``RUNTIME_REFACTOR_IMPL_PLAN.md`` §3.2, we snapshot the legacy
``react_agent._create_toolkit`` selection logic (sourced from commit
``6500376f``) into ``_legacy_select_tool_names`` and assert that the new
:meth:`AgentBuilder.build_toolkit` path produces the same set of tool
names — and the same underlying tool functions — across three
representative ``agent_config`` fixtures:

1. **default**         — every builtin tool defaults enabled.
2. **coding-mode**     — same config but ``active_modes={"coding"}``
                         plus ``effective_skills={"make-skill"}``.
3. **restricted**      — half the builtins explicitly disabled.

The legacy and new paths intentionally use different iteration orders
(legacy: dict-literal insertion; new: ``pkgutil.iter_modules``
alphabetical), so the comparison is set-based — the user-facing contract
is *which* tools are selected, not their order.

Coding Mode's dynamic ``lsp`` tool is injected by
``CodingModeMixin._collect_coding_mode_tools`` in both paths; this test
covers only the static selection layer.
"""

from __future__ import annotations

from typing import Any

import pytest

from qwenpaw.agents.tools import discover_builtin_tool_funcs
from qwenpaw.config.config import ToolsConfig
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.runtime.tool_registry import ToolRegistry

# ---------------------------------------------------------------------------
# Legacy snapshot (Phase 2 reference)
# ---------------------------------------------------------------------------

# Locked from ``react_agent._create_toolkit`` at commit 6500376f.
_LEGACY_HARDCODED = (
    "execute_shell_command",
    "read_file",
    "write_file",
    "edit_file",
    "grep_search",
    "glob_search",
    "browser_use",
    "desktop_screenshot",
    "view_image",
    "view_video",
    "send_file_to_user",
    "get_current_time",
    "set_user_timezone",
    "get_token_usage",
    "delegate_external_agent",
    "list_agents",
    "chat_with_agent",
    "submit_to_agent",
    "check_agent_task",
)
# Skill-gated hardcoded entry.
_LEGACY_SKILL_GATED = {"materialize_skill": ("make-skill",)}
# Plugin tools that legacy required explicit ``enabled_tools`` opt-in for.
_LEGACY_PLUGIN_TOOLS = ("append_file",)
# Coding-mode tools the legacy added via ``_collect_coding_mode_tools``.
# Only the statically-decorated one shows up at the selection layer;
# ``lsp`` is dynamic and is injected via ``extra_tools`` in both paths.
_LEGACY_CODING_TOOLS = ("ast_search",)


def _legacy_select_tool_names(
    agent_config: Any,
    *,
    effective_skills: set[str],
    active_modes: set[str],
) -> set[str]:
    """Reproduce ``react_agent._create_toolkit`` selection logic.

    Returns the set of tool names the legacy path would have wrapped in
    ``GuardedFunctionTool``. Mirrors the original branching order:

    1. Build ``tool_functions`` from the hardcoded dict + skill-gated
       extras.
    2. Discover plugin tools (legacy did this by importing
       ``tools_module`` and walking ``__all__``; we model it with
       ``_LEGACY_PLUGIN_TOOLS``).
    3. Filter each tool against ``enabled_tools`` with the legacy
       fallback rule: hardcoded defaults stay on when unconfigured,
       plugins drop out when unconfigured.
    4. Append coding-mode tools when the mode is active.
    """
    enabled_tools = {
        n: t.enabled
        for n, t in getattr(
            getattr(agent_config, "tools", None),
            "builtin_tools",
            {},
        ).items()
    }

    tool_functions: dict[str, None] = {n: None for n in _LEGACY_HARDCODED}
    for name, required_skills in _LEGACY_SKILL_GATED.items():
        if any(s in effective_skills for s in required_skills):
            tool_functions[name] = None

    hardcoded = set(tool_functions)
    plugin_tools: set[str] = set()
    for name in _LEGACY_PLUGIN_TOOLS:
        if name not in tool_functions:
            tool_functions[name] = None
            plugin_tools.add(name)

    selected: set[str] = set()
    for name in tool_functions:
        if name in plugin_tools and name not in enabled_tools:
            continue
        if not enabled_tools.get(name, name in hardcoded):
            continue
        selected.add(name)

    if "coding" in active_modes:
        selected.update(_LEGACY_CODING_TOOLS)

    return selected


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _AgentConfigStub:
    """Minimal ``AgentProfileConfig`` stand-in."""

    def __init__(self, tools: ToolsConfig) -> None:
        self.tools = tools


def _default_agent_config() -> _AgentConfigStub:
    return _AgentConfigStub(tools=ToolsConfig())


def _coding_mode_agent_config() -> _AgentConfigStub:
    # The agent_config itself is identical; the difference is the
    # per-request ``active_modes`` / ``effective_skills`` passed below.
    return _default_agent_config()


def _restricted_agent_config() -> _AgentConfigStub:
    # Disable roughly half the hardcoded tools to exercise the
    # ``enabled=False`` branch in both paths.
    tools_cfg = ToolsConfig()
    disabled = {
        "browser_use",
        "desktop_screenshot",
        "view_image",
        "view_video",
        "send_file_to_user",
        "get_token_usage",
        "delegate_external_agent",
        "list_agents",
        "chat_with_agent",
        "submit_to_agent",
        "check_agent_task",
    }
    for name in disabled:
        if name in tools_cfg.builtin_tools:
            tools_cfg.builtin_tools[name].enabled = False
    return _AgentConfigStub(tools=tools_cfg)


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    for fn in discover_builtin_tool_funcs():
        reg.register(fn._tool_descriptor)
    return reg


@pytest.fixture
def builder(registry: ToolRegistry) -> AgentBuilder:
    return AgentBuilder(tool_registry=registry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_path_tool_funcs(
    builder: AgentBuilder,
    agent_config: Any,
    *,
    active_modes: set[str],
    effective_skills: set[str],
) -> dict[str, Any]:
    """Run the new path and return ``{name: underlying_func}``.

    We pull the underlying function out of ``GuardedFunctionTool`` so we
    can prove identity, not just name equality — guards against a future
    regression where the registry binds a tool name to the wrong
    function.
    """
    tk = builder.build_toolkit(
        agent_config,
        active_modes=active_modes,
        effective_skills=effective_skills,
    )
    return {t.name: t._func for t in tk.tool_groups[0].tools}


def _legacy_func_map() -> dict[str, Any]:
    return {
        fn._tool_descriptor.name: fn for fn in discover_builtin_tool_funcs()
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture_name", "agent_config", "active_modes", "effective_skills"),
    [
        ("default", _default_agent_config(), set(), set()),
        (
            "coding_mode",
            _coding_mode_agent_config(),
            {"coding"},
            {"make-skill"},
        ),
        ("restricted", _restricted_agent_config(), set(), set()),
    ],
)
def test_legacy_and_new_paths_select_the_same_tool_set(
    builder: AgentBuilder,
    fixture_name: str,
    agent_config: Any,
    active_modes: set[str],
    effective_skills: set[str],
) -> None:
    """The user-facing contract: same agent_config ⇒ same tool set."""
    expected = _legacy_select_tool_names(
        agent_config,
        effective_skills=effective_skills,
        active_modes=active_modes,
    )
    actual = set(
        _new_path_tool_funcs(
            builder,
            agent_config,
            active_modes=active_modes,
            effective_skills=effective_skills,
        ),
    )
    assert actual == expected, (
        f"[{fixture_name}] parity broken — "
        f"missing in new path: {sorted(expected - actual)}, "
        f"unexpected in new path: {sorted(actual - expected)}"
    )


@pytest.mark.parametrize(
    ("fixture_name", "agent_config", "active_modes", "effective_skills"),
    [
        ("default", _default_agent_config(), set(), set()),
        (
            "coding_mode",
            _coding_mode_agent_config(),
            {"coding"},
            {"make-skill"},
        ),
        ("restricted", _restricted_agent_config(), set(), set()),
    ],
)
def test_each_selected_tool_binds_to_its_canonical_function(
    builder: AgentBuilder,
    fixture_name: str,
    agent_config: Any,
    active_modes: set[str],
    effective_skills: set[str],
) -> None:
    """Same name in both paths ⇒ same underlying function identity."""
    canonical = _legacy_func_map()
    actual = _new_path_tool_funcs(
        builder,
        agent_config,
        active_modes=active_modes,
        effective_skills=effective_skills,
    )
    mismatched = {
        name: (canonical[name], fn)
        for name, fn in actual.items()
        if canonical[name] is not fn
    }
    assert not mismatched, (
        f"[{fixture_name}] new path bound the wrong function for: "
        f"{sorted(mismatched)}"
    )
