# -*- coding: utf-8 -*-
"""Tests for unified tool governance registration (issue #6114)."""

from __future__ import annotations

from qwenpaw.governance.policy import (
    GovernanceAction,
    GovernancePolicy,
    ToolCallSpec,
)
from qwenpaw.governance.tool_registry import (
    DEFAULT_REGISTRY,
    ToolRegistry,
    assert_no_governance_gaps,
    register_tool_governance,
    snake_to_pascal,
)


def _tc(tool_name: str, target: str = "") -> ToolCallSpec:
    return ToolCallSpec(
        tool_name=tool_name,
        target=target,
        agent_id="test-agent",
        session_id="test-session",
    )


class TestRegisterToolGovernance:
    def test_idempotent_register(self):
        registry = ToolRegistry()
        pname = register_tool_governance(
            registry,
            python_name="__ut_plugin_tool__",
            tool_type="network",
            policy_name="UtPluginTool",
        )
        assert pname == "UtPluginTool"
        assert registry.get_type("UtPluginTool") == "network"
        register_tool_governance(
            registry,
            python_name="__ut_plugin_tool__",
            tool_type="shell",  # ignored — already registered
            policy_name="UtPluginTool",
        )
        assert registry.get_type("UtPluginTool") == "network"

    def test_snake_to_pascal(self):
        assert snake_to_pascal("generate_image_qwen") == "GenerateImageQwen"


class TestBuiltinDescriptorGovernance:
    def test_no_governance_gaps(self):
        gaps = assert_no_governance_gaps()
        assert not gaps

    def test_ast_search_registered(self):
        assert DEFAULT_REGISTRY.get_type("AstSearch") == "file"
        assert (
            DEFAULT_REGISTRY.python_to_policy_name("ast_search") == "AstSearch"
        )

    def test_core_builtins_registered(self):
        expected = {
            "Read": "file",
            "Write": "file",
            "Bash": "shell",
            "WebSearch": "network",
            "WebFetch": "network",
            "Browser": "network",
            "GetCurrentTime": "internal",
            "RecallHistory": "internal",
            "RecallHistoryPython": "shell",
            "MemorySearch": "internal",
        }
        for name, tool_type in expected.items():
            assert DEFAULT_REGISTRY.get_type(name) == tool_type, name

    def test_python_name_mappings(self):
        assert (
            DEFAULT_REGISTRY.python_to_policy_name("execute_shell_command")
            == "Bash"
        )
        assert DEFAULT_REGISTRY.python_to_policy_name("read_file") == "Read"
        assert (
            DEFAULT_REGISTRY.python_to_policy_name("web_search") == "WebSearch"
        )


class TestPluginGovernanceIssue6114:
    """Plugin tools must pass Phase 0 after register_tool_governance."""

    def test_plugin_tools_not_denied_as_unregistered(self):
        plugin_tools = [
            "generate_image_qwen",
            "edit_image_qwen",
            "generate_image_gpt",
            "edit_image_gpt",
            "text_to_video_wan",
            "image_to_video_wan",
            "reference_to_video_wan",
        ]
        for py_name in plugin_tools:
            register_tool_governance(
                DEFAULT_REGISTRY,
                python_name=py_name,
                tool_type="network",
            )

        policy = GovernancePolicy(execution_level="smart")
        for py_name in plugin_tools:
            pname = DEFAULT_REGISTRY.python_to_policy_name(py_name)
            assert DEFAULT_REGISTRY.get_type(pname) == "network"
            decision = policy.evaluate(_tc(pname))
            assert (
                decision.action is not GovernanceAction.DENY
            ), f"{pname} denied: {decision.reason}"
            assert "Unregistered tool" not in (decision.reason or "")

    def test_unknown_still_denied(self):
        policy = GovernancePolicy(execution_level="smart")
        decision = policy.evaluate(_tc("TotallyUnknownToolXYZ"))
        assert decision.action is GovernanceAction.DENY
        assert "Unregistered tool" in decision.reason
