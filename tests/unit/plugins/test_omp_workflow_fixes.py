# -*- coding: utf-8 -*-
# pylint: disable=protected-access,import-outside-toplevel
"""Regression tests for OMP post-#5882 hardening fixes."""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from qwenpaw.agents.acp.meta import ACP_CODING_PROJECT_META_KEY
from qwenpaw.app.workspace.workspace_plugins import WorkspacePlugins
from qwenpaw.loop.gates.base import StopAction
from qwenpaw.runtime.builder import AgentBuilder


class _Workspace:
    """Minimal weakref-capable workspace duck type for mode.setup()."""

    def __init__(self) -> None:
        self.plugins = WorkspacePlugins()


# ---------------------------------------------------------------------------
# P1: per-workspace mode isolation
# ---------------------------------------------------------------------------


class TestOMPModeWorkspaceIsolation:
    """register_mode must not share gate state across workspaces."""

    def test_register_mode_cls_creates_independent_instances(self):
        from plugins.bundle.omp_workflows.ultrawork.mode import UltraworkMode
        from qwenpaw.plugins.api import PluginApi
        from qwenpaw.plugins.registry import PluginRegistry

        old = PluginRegistry._instance
        PluginRegistry._instance = None
        try:
            registry = PluginRegistry()
            api = PluginApi(
                "omp-test",
                config={},
                manifest={"id": "omp-test"},
            )
            api.set_registry(registry)

            ws1 = _Workspace()
            ws2 = _Workspace()
            mgr = MagicMock()
            mgr.agents = {"agent-a": ws1, "agent-b": ws2}
            registry.set_workspace_manager(mgr)

            api._register_mode_cls_to_all_workspaces(UltraworkMode)

            m1 = ws1.plugins.modes[0]
            m2 = ws2.plugins.modes[0]
            assert m1 is not m2
            assert m1._gate is not m2._gate
            assert len(ws1.plugins.stop_handlers) == 1
            assert len(ws2.plugins.stop_handlers) == 1
            assert (
                ws1.plugins.stop_handlers[0].handler
                is not ws2.plugins.stop_handlers[0].handler
            )

            # Activate only workspace-1 gate; workspace-2 stays inactive.
            loop = Path(tempfile.mkdtemp())
            m1._gate.activate_for_work(loop)
            assert m1.is_active(MagicMock()) is True
            assert m2.is_active(MagicMock()) is False
        finally:
            PluginRegistry._instance = old

    def test_claim_workflow_does_not_cross_workspaces(self):
        from plugins.bundle.omp_workflows.ralph.mode import RalphMode
        from plugins.bundle.omp_workflows.ultrawork.mode import UltraworkMode

        ws1 = _Workspace()
        ws2 = _Workspace()
        a = UltraworkMode()
        b = UltraworkMode()
        a.setup(ws1)
        b.setup(ws2)

        loop1 = Path(tempfile.mkdtemp())
        loop2 = Path(tempfile.mkdtemp())
        a._gate.activate_for_work(loop1)
        b._gate.activate_for_work(loop2)
        assert a.is_active(MagicMock())
        assert b.is_active(MagicMock())

        # Different mode name on same workspace (slash cmds must not collide).
        peer = RalphMode()
        peer.setup(ws1)
        peer.claim_workflow()
        assert a.is_active(MagicMock()) is False
        assert b.is_active(MagicMock()) is True


# ---------------------------------------------------------------------------
# P1: deny-all / whitelist semantics
# ---------------------------------------------------------------------------


class TestSubagentToolWhitelist:
    def test_none_inherits(self):
        tools = [SimpleNamespace(name="read_file"), SimpleNamespace(name="x")]
        out = AgentBuilder.apply_subagent_tool_whitelist(tools, {})
        assert [AgentBuilder._tool_name(t) for t in out] == [
            "read_file",
            "x",
        ]

    def test_empty_denies_all(self):
        tools = [
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="memory_search"),
        ]
        out = AgentBuilder.apply_subagent_tool_whitelist(
            tools,
            {"subagent_allowed_tools": []},
        )
        assert out == []

    def test_partial_allow(self):
        tools = [
            SimpleNamespace(name="read_file"),
            SimpleNamespace(name="memory_search"),
            SimpleNamespace(name="write_file"),
        ]
        out = AgentBuilder.apply_subagent_tool_whitelist(
            tools,
            {"subagent_allowed_tools": ["read_file", "write_file"]},
        )
        assert [AgentBuilder._tool_name(t) for t in out] == [
            "read_file",
            "write_file",
        ]

    def test_unknown_names_drop_all_known(self):
        tools = [SimpleNamespace(name="read_file")]
        out = AgentBuilder.apply_subagent_tool_whitelist(
            tools,
            {"subagent_allowed_tools": ["not_a_real_tool"]},
        )
        assert out == []


# ---------------------------------------------------------------------------
# P1: fork project dir plumbing
# ---------------------------------------------------------------------------


class TestForkProjectDirWiring:
    def test_apply_request_coding_project_reads_fork_project_dir(self):
        from qwenpaw.config.config import AgentProfileConfig

        with tempfile.TemporaryDirectory() as tmp:
            worktree = Path(tmp) / "fork-wt"
            worktree.mkdir()
            cfg = AgentProfileConfig(id="default", name="Default")
            updated = AgentBuilder._apply_request_coding_project(
                cfg,
                {"fork_project_dir": str(worktree)},
            )
            assert updated.coding_mode.enabled is True
            assert Path(updated.coding_mode.project_dir) == worktree.resolve()

    def test_apply_request_coding_project_prefers_acp_key(self):
        from qwenpaw.config.config import AgentProfileConfig

        with tempfile.TemporaryDirectory() as tmp:
            acp_dir = Path(tmp) / "acp"
            fork_dir = Path(tmp) / "fork"
            acp_dir.mkdir()
            fork_dir.mkdir()
            cfg = AgentProfileConfig(id="default", name="Default")
            updated = AgentBuilder._apply_request_coding_project(
                cfg,
                {
                    ACP_CODING_PROJECT_META_KEY: str(acp_dir),
                    "fork_project_dir": str(fork_dir),
                },
            )
            assert Path(updated.coding_mode.project_dir) == acp_dir.resolve()


# ---------------------------------------------------------------------------
# P2: cleanup keeps audit artifacts
# ---------------------------------------------------------------------------


class TestWorkflowStateCleanup:
    def test_cleanup_keeps_audit_files(self):
        from plugins.bundle.omp_workflows.shared.state import WorkflowState

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            wf = WorkflowState(root, "team")
            inst = wf.create_instance()
            (inst / "handoffs").mkdir()
            (inst / "handoffs" / "plan.md").write_text(
                "plan",
                encoding="utf-8",
            )
            (inst / "results").mkdir()
            (inst / "results" / "a.json").write_text("{}", encoding="utf-8")
            (inst / "spec.md").write_text("spec", encoding="utf-8")
            (inst / "state.json").write_text("{}", encoding="utf-8")
            (inst / "prd.json").write_text("{}", encoding="utf-8")
            (inst / "state.json.tmp").write_text("{}", encoding="utf-8")

            wf.cleanup()

            assert (inst / "handoffs" / "plan.md").exists()
            assert (inst / "results" / "a.json").exists()
            assert (inst / "spec.md").exists()
            assert (inst / "progress.txt").exists()
            assert not (inst / "state.json").exists()
            assert not (inst / "prd.json").exists()
            assert not (inst / "state.json.tmp").exists()


# ---------------------------------------------------------------------------
# P2 / P1: Autopilot cleanup phase + fork hard gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAutopilotGatePhases:
    async def test_cleanup_continues_completed_terminates(self):
        from plugins.bundle.omp_workflows.autopilot.gate import AutopilotGate
        from plugins.bundle.omp_workflows.autopilot.prompts import PHASES

        assert "cleanup" in PHASES
        assert "completed" in PHASES

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = AutopilotGate()
            loop = gate.activate_for_autopilot(root)
            # Seed forks_integrated so post-exec phases are allowed.
            from plugins.bundle.omp_workflows.shared.state import WorkflowState

            wf = WorkflowState.from_existing(root, "autopilot", loop)
            wf.write_state(
                {
                    "phase": "cleanup",
                    "forks_integrated": True,
                    "validation_round": 0,
                },
            )

            result = await gate.check({})
            assert result is not None
            assert result.action == StopAction.INTERRUPT_AND_CONTINUE
            prompt = gate.build_continuation()
            assert 'phase="completed"' in prompt or "phase=" in prompt
            assert "cleanup" in prompt.lower()

            wf.write_state(
                {
                    "phase": "completed",
                    "forks_integrated": True,
                },
            )
            # Keep gate active after previous check.
            done = await gate.check({})
            assert done is not None
            assert done.action == StopAction.TERMINATE
            assert not (loop / "state.json").exists()

    async def test_rejects_qa_without_forks_integrated(self):
        from plugins.bundle.omp_workflows.autopilot.gate import AutopilotGate
        from plugins.bundle.omp_workflows.shared.state import WorkflowState

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = AutopilotGate()
            loop = gate.activate_for_autopilot(root)
            wf = WorkflowState.from_existing(root, "autopilot", loop)
            wf.write_state({"phase": "qa"})

            result = await gate.check({})
            assert result is not None
            assert result.action == StopAction.INTERRUPT_AND_CONTINUE
            assert "forks" in (result.reason or "").lower()
            assert wf.read_state().get("phase") == "execution"
            assert "forks_integrated" in gate.build_continuation()


@pytest.mark.asyncio
class TestUltraworkForkGate:
    async def test_done_without_merge_is_blocked(self):
        from plugins.bundle.omp_workflows.shared.state import WorkflowState
        from plugins.bundle.omp_workflows.ultrawork.gate import UltraworkGate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = UltraworkGate()
            loop = gate.activate_for_work(root)
            wf = WorkflowState.from_existing(root, "ultrawork", loop)
            wf.write_state({"phase": "done"})

            result = await gate.check({})
            assert result is not None
            assert result.action == StopAction.INTERRUPT_AND_CONTINUE
            assert wf.read_state().get("phase") == "working"
            assert "BLOCKED" in gate.build_continuation()

            wf.update_state(
                {"phase": "done", "forks_integrated": True},
            )
            done = await gate.check({})
            assert done is not None
            assert done.action == StopAction.TERMINATE


@pytest.mark.asyncio
class TestTeamForkGate:
    async def test_verify_without_merge_is_blocked(self):
        from plugins.bundle.omp_workflows.shared.state import WorkflowState
        from plugins.bundle.omp_workflows.team.gate import TeamPipelineGate

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gate = TeamPipelineGate()
            loop = gate.activate_for_team(root)
            wf = WorkflowState.from_existing(root, "team", loop)
            wf.write_state({"current_phase": "verify"})

            result = await gate.check({})
            assert result is not None
            assert result.action == StopAction.INTERRUPT_AND_CONTINUE
            assert "forks" in (result.reason or "").lower()
            assert wf.read_state().get("current_phase") == "exec"
            assert "BLOCKED" in gate.build_continuation()


# ---------------------------------------------------------------------------
# Optional nits from review: ACP key write + agent-side deny-all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSpawnForkedAcpKey:
    async def test_spawn_forked_writes_acp_coding_project_key(
        self,
        monkeypatch,
    ):
        from qwenpaw.agents.tools import agent_management as am

        async def _fake_fork_api(**_kwargs):
            return {
                "fork_session_id": "fork-sess",
                "worktree_path": "/tmp/omp-fork-wt",
                "worktree_branch": "fork/omp-test",
            }

        captured: dict = {}

        def _fake_submit(_base, payload, _agent_id, _timeout):
            captured["payload"] = payload
            return {"task_id": "task-1"}

        monkeypatch.setattr(am, "_call_fork_api", _fake_fork_api)
        monkeypatch.setattr(am, "submit_agent_chat_task", _fake_submit)
        monkeypatch.setattr(
            am,
            "_build_spawn_request_context",
            lambda agent_id: {
                "_spawn_subagent": True,
                "root_agent_id": agent_id,
            },
        )
        monkeypatch.setattr(
            "qwenpaw.app.agent_context.get_current_session_id",
            lambda: "parent-sess",
        )
        monkeypatch.setattr(
            "qwenpaw.app.agent_context.get_current_user_id",
            lambda: "user-1",
        )
        monkeypatch.setattr(
            "qwenpaw.app.agent_context.get_current_channel",
            lambda: "console",
        )

        await am._spawn_forked_subagent(
            task="do work",
            current_agent_id="agent-1",
            subagent_session_id="sub-1",
            background=True,
            timeout=30,
        )

        rc = captured["payload"]["request_context"]
        assert rc["fork_project_dir"] == "/tmp/omp-fork-wt"
        assert rc[ACP_CODING_PROJECT_META_KEY] == "/tmp/omp-fork-wt"


class TestQwenPawAgentDenyAll:
    def test_final_whitelist_strips_memory_like_tools(self):
        from qwenpaw.agents.react_agent import QwenPawAgent

        agent = object.__new__(QwenPawAgent)
        agent._request_context = {"subagent_allowed_tools": []}
        toolkit = SimpleNamespace(
            tool_groups=[
                SimpleNamespace(
                    tools=[
                        SimpleNamespace(name="read_file"),
                        SimpleNamespace(name="memory_search"),
                        SimpleNamespace(name="remember"),
                    ],
                ),
            ],
        )
        agent._apply_subagent_tool_whitelist(toolkit)
        assert toolkit.tool_groups[0].tools == []


class TestRalphNoFork:
    def test_ralph_executor_spawn_is_not_forked(self):
        from plugins.bundle.omp_workflows.ralph.prompts import (
            build_continuation,
        )

        text = build_continuation(
            1,
            20,
            "architect",
            True,
            Path("/tmp/ralph"),
            "PRD: 0/1",
        )
        assert "fork=True" not in text
        assert "fork=true" not in text.lower()
