# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for ``qwenpaw.agents.tools.discover_builtin_tool_funcs``.

These tests guard the Phase 2 contract: every legacy hardcoded tool in
``react_agent._create_toolkit`` plus the two coding-mode / skill tools
must be discoverable from the tools subpackage without any explicit
list mutation.
"""

from __future__ import annotations

from qwenpaw.agents.tools import discover_builtin_tool_funcs
from qwenpaw.runtime.tool_registry import ToolDescriptor

# Locked from the legacy ``tool_functions`` dict (19 hardcoded entries)
# plus ``append_file`` (plugin), ``materialize_skill`` (skill-gated) and
# ``ast_search`` (coding-mode-gated).
_EXPECTED_TOOL_NAMES = frozenset(
    {
        "execute_shell_command",
        "read_file",
        "write_file",
        "edit_file",
        "append_file",
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
        "materialize_skill",
        "ast_search",
    },
)


def test_discover_returns_every_decorated_builtin() -> None:
    funcs = discover_builtin_tool_funcs()
    names = {fn._tool_descriptor.name for fn in funcs}
    missing = _EXPECTED_TOOL_NAMES - names
    extra = names - _EXPECTED_TOOL_NAMES
    assert not missing, f"missing tool descriptors: {sorted(missing)}"
    assert not extra, f"unexpected tool descriptors: {sorted(extra)}"


def test_each_discovered_func_has_valid_descriptor() -> None:
    for fn in discover_builtin_tool_funcs():
        desc = fn._tool_descriptor
        assert isinstance(desc, ToolDescriptor)
        assert desc.name
        assert desc.func is fn


def test_gating_mirrors_legacy_create_toolkit_semantics() -> None:
    by_name = {
        fn._tool_descriptor.name: fn._tool_descriptor
        for fn in discover_builtin_tool_funcs()
    }
    # ``append_file`` was the only plugin tool the legacy treated as
    # opt-in via config.
    assert by_name["append_file"].enabled_by_default is False
    # ``materialize_skill`` was gated on ``"make-skill" in effective_skills``.
    assert by_name["materialize_skill"].requires_skills == ("make-skill",)
    # ``ast_search`` was gated on coding mode.
    assert by_name["ast_search"].requires_modes == ("coding",)
    # Every other tool registered without gates in the legacy path.
    unconditional = {
        "read_file",
        "write_file",
        "edit_file",
        "grep_search",
        "glob_search",
        "execute_shell_command",
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
    }
    for name in unconditional:
        d = by_name[name]
        assert d.enabled_by_default, f"{name} should be enabled by default"
        assert not d.requires_modes, f"{name} should be mode-unconditional"
        assert not d.requires_skills, f"{name} should be skill-unconditional"
