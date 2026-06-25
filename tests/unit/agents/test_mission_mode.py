# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for Mission Mode integration with Runtime v2."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_hook_context(
    *,
    session_state: dict | None = None,
    extras: dict | None = None,
    mode_state: dict | None = None,
    workspace_dir: str = "/tmp/ws",
    agent_id: str = "default",
) -> MagicMock:
    """Build a minimal HookContext mock."""
    ctx = MagicMock()
    ctx.session_state = session_state or {}
    ctx.extras = extras or {}
    ctx.mode_state = mode_state if mode_state is not None else {}
    ctx.workspace_dir = workspace_dir
    ctx.agent_id = agent_id
    ctx.input_msgs = []
    ctx.request = MagicMock(user_id="u1", channel="")
    ctx.session_id = "sess-1"
    ctx.workspace = MagicMock()
    ctx.workspace.workspace_dir = workspace_dir
    ctx.agent = MagicMock()
    return ctx


# ---------------------------------------------------------------------------
# MissionExecutionHook — phase state machine
# ---------------------------------------------------------------------------


class TestMissionExecutionHook:
    """Test phase routing logic in MissionExecutionHook."""

    @pytest.fixture
    def hook(self):
        from qwenpaw.modes.mission.hooks import MissionExecutionHook
        from qwenpaw.modes.mission import MissionMode

        mode = MissionMode()
        return MissionExecutionHook(owner_mode=mode)

    @pytest.mark.asyncio
    async def test_phase1_continues_normally(self, hook):
        """Phase prd_generation should let the standard executor handle it."""
        ctx = _make_hook_context(
            session_state={
                "mission_active": True,
                "mission_current_phase": "prd_generation",
            },
        )
        result = await hook._run(ctx)  # pylint: disable=protected-access
        assert (
            result.action is None
            or str(result.action) == "HookAction.CONTINUE"
        )
        assert "_mission_phase2" not in (ctx.extras or {})

    @pytest.mark.asyncio
    async def test_empty_phase_continues_normally(self, hook):
        """No phase set should behave like Phase 1."""
        ctx = _make_hook_context(
            session_state={
                "mission_active": True,
                "mission_current_phase": "",
            },
        )
        await hook._run(ctx)
        assert "_mission_phase2" not in (ctx.extras or {})

    @pytest.mark.asyncio
    async def test_execution_confirmed_signals_phase2(self, hook):
        """execution_confirmed should set _mission_phase2 in extras."""
        ctx = _make_hook_context(
            session_state={
                "mission_active": True,
                "mission_current_phase": "execution_confirmed",
                "mission_loop_dir": "/tmp/loop-001",
                "mission_max_iterations": 15,
            },
        )
        await hook._run(ctx)
        assert ctx.extras["_mission_phase2"]["loop_dir"] == "/tmp/loop-001"
        assert ctx.extras["_mission_phase2"]["max_iterations"] == 15

    @pytest.mark.asyncio
    async def test_execution_phase_signals_phase2(self, hook):
        """execution should also signal Phase 2."""
        ctx = _make_hook_context(
            session_state={
                "mission_active": True,
                "mission_current_phase": "execution",
                "mission_loop_dir": "/tmp/loop-002",
            },
        )
        await hook._run(ctx)
        assert "_mission_phase2" in ctx.extras

    @pytest.mark.asyncio
    async def test_completed_clears_active_flag(self, hook):
        """completed phase should deactivate mission."""
        ctx = _make_hook_context(
            session_state={
                "mission_active": True,
                "mission_current_phase": "completed",
            },
        )
        await hook._run(ctx)
        assert ctx.session_state["mission_active"] is False

    @pytest.mark.asyncio
    async def test_max_iterations_reached_clears_flag(self, hook):
        """max_iterations_reached should deactivate mission."""
        ctx = _make_hook_context(
            session_state={
                "mission_active": True,
                "mission_current_phase": "max_iterations_reached",
            },
        )
        await hook._run(ctx)
        assert ctx.session_state["mission_active"] is False

    @pytest.mark.asyncio
    async def test_aborted_clears_flag(self, hook):
        """aborted should deactivate mission."""
        ctx = _make_hook_context(
            session_state={
                "mission_active": True,
                "mission_current_phase": "aborted",
            },
        )
        await hook._run(ctx)
        assert ctx.session_state["mission_active"] is False


# ---------------------------------------------------------------------------
# _make_mission_adapter — str vs dict branches
# ---------------------------------------------------------------------------


class TestMissionAdapter:
    """Test the /mission slash command adapter."""

    @pytest.mark.asyncio
    async def test_info_subcommand_returns_msg(self):
        """status/list/help return a Msg (short-circuit)."""
        from qwenpaw.runtime.builtin_commands import _make_mission_adapter

        spec = _make_mission_adapter()
        ctx = _make_hook_context()
        ctx.input_msgs = []

        with patch(
            "qwenpaw.agents.mission.handler.handle_mission_command",
            new_callable=AsyncMock,
            return_value="**Mission Status**: No active mission",
        ):
            result = await spec.handler(ctx, "status")

        assert result is not None
        assert result.role == "assistant"

    @pytest.mark.asyncio
    async def test_new_mission_returns_none_and_sets_extras(self):
        """A new mission start should return None and populate extras."""
        from qwenpaw.runtime.builtin_commands import _make_mission_adapter

        spec = _make_mission_adapter()
        ctx = _make_hook_context()
        ctx.input_msgs = []

        with patch(
            "qwenpaw.agents.mission.handler.handle_mission_command",
            new_callable=AsyncMock,
            return_value={
                "mission_phase": 1,
                "loop_dir": "/tmp/loop-abc",
                "max_iterations": 10,
            },
        ):
            result = await spec.handler(ctx, "implement auth system")

        assert result is None
        mission_start = ctx.extras["_mission_start"]
        assert mission_start["mission_active"] is True
        assert mission_start["mission_loop_dir"] == "/tmp/loop-abc"
        assert mission_start["mission_max_iterations"] == 10
        assert mission_start["mission_current_phase"] == "prd_generation"

    @pytest.mark.asyncio
    async def test_no_workspace_returns_error_msg(self):
        """Missing workspace_dir should produce an error Msg."""
        from qwenpaw.runtime.builtin_commands import _make_mission_adapter

        spec = _make_mission_adapter()
        ctx = _make_hook_context()
        ctx.workspace = None
        ctx.workspace_dir = None

        result = await spec.handler(ctx, "do something")
        assert result is not None
        assert "requires a workspace" in str(result.content).lower()


# ---------------------------------------------------------------------------
# build_mission_system_prompt
# ---------------------------------------------------------------------------


class TestBuildMissionSystemPrompt:
    """Test the prompt generation for different phases."""

    def test_returns_none_when_no_loop_dir(self):
        from qwenpaw.agents.mission.prompts import build_mission_system_prompt

        result = build_mission_system_prompt(
            {"mission_active": True, "mission_loop_dir": ""},
        )
        assert result is None

    def test_phase1_english(self):
        from qwenpaw.agents.mission.prompts import build_mission_system_prompt

        result = build_mission_system_prompt(
            {
                "mission_active": True,
                "mission_loop_dir": "/tmp/loop",
                "mission_current_phase": "prd_generation",
                "mission_max_iterations": 20,
            },
            language="en",
        )
        assert result is not None
        assert "Phase 1" in result
        assert "prd.json" in result
        assert "/tmp/loop" in result

    def test_phase1_chinese(self):
        from qwenpaw.agents.mission.prompts import build_mission_system_prompt

        result = build_mission_system_prompt(
            {
                "mission_active": True,
                "mission_loop_dir": "/tmp/loop",
                "mission_current_phase": "prd_generation",
            },
            language="zh-CN",
        )
        assert result is not None
        assert "任务分解" in result
        assert "prd.json" in result

    def test_phase2_calls_build_master_prompt(self):
        from qwenpaw.agents.mission.prompts import build_mission_system_prompt

        with patch(
            "qwenpaw.agents.mission.prompts.build_master_prompt",
            return_value="<master prompt>",
        ) as mock_bmp, patch(
            "qwenpaw.agents.mission.state.read_loop_config",
            return_value={
                "verify_commands": "pytest",
                "git_installed": True,
                "is_git_repo": True,
                "default_branch": "main",
                "repo_root": "/repo",
                "workspace_dir": "/ws",
            },
        ):
            result = build_mission_system_prompt(
                {
                    "mission_active": True,
                    "mission_loop_dir": "/tmp/loop",
                    "mission_current_phase": "execution",
                    "mission_max_iterations": 10,
                },
                workspace_dir="/ws",
                agent_id="test-agent",
            )

        assert result == "<master prompt>"
        mock_bmp.assert_called_once_with(
            loop_dir="/tmp/loop",
            agent_id="test-agent",
            max_iterations=10,
            verify_commands="pytest",
            git_context={
                "git_installed": True,
                "is_git_repo": True,
                "default_branch": "main",
                "repo_root": "/repo",
            },
            workspace_dir="/ws",
        )


# ---------------------------------------------------------------------------
# MissionPromptContributor
# ---------------------------------------------------------------------------


class TestMissionPromptContributor:
    """Test that the contributor reads from ctx.extras correctly."""

    @pytest.fixture
    def contributor(self):
        from qwenpaw.modes.mission.contributor import MissionPromptContributor
        from qwenpaw.modes.mission import MissionMode

        return MissionPromptContributor(owner_mode=MissionMode())

    def test_returns_none_when_no_mission_state(self, contributor):
        ctx = SimpleNamespace(
            extras={},
            workspace_dir="/ws",
            agent_id="default",
        )
        assert contributor.contribute_sync(ctx) is None

    def test_returns_prompt_from_mission_start(self, contributor):
        ctx = SimpleNamespace(
            extras={
                "_mission_start": {
                    "mission_active": True,
                    "mission_loop_dir": "/tmp/loop",
                    "mission_current_phase": "prd_generation",
                    "mission_max_iterations": 20,
                },
                "language": "en",
            },
            workspace_dir="/ws",
            agent_id="default",
        )
        result = contributor.contribute_sync(ctx)
        assert result is not None
        assert "Mission Mode" in result

    def test_returns_prompt_from_session_state(self, contributor):
        ctx = SimpleNamespace(
            extras={
                "mission_state": {
                    "mission_active": True,
                    "mission_loop_dir": "/tmp/loop",
                    "mission_current_phase": "prd_generation",
                    "mission_max_iterations": 20,
                },
                "language": "zh",
            },
            workspace_dir="/ws",
            agent_id="default",
        )
        result = contributor.contribute_sync(ctx)
        assert result is not None
        assert "任务分解" in result

    def test_mission_start_takes_precedence(self, contributor):
        ctx = SimpleNamespace(
            extras={
                "_mission_start": {
                    "mission_active": True,
                    "mission_loop_dir": "/tmp/start-loop",
                    "mission_current_phase": "prd_generation",
                    "mission_max_iterations": 20,
                },
                "mission_state": {
                    "mission_active": True,
                    "mission_loop_dir": "/tmp/state-loop",
                    "mission_current_phase": "prd_generation",
                    "mission_max_iterations": 20,
                },
                "language": "en",
            },
            workspace_dir="/ws",
            agent_id="default",
        )
        result = contributor.contribute_sync(ctx)
        assert "/tmp/start-loop" in result


# ---------------------------------------------------------------------------
# MissionMode.is_active
# ---------------------------------------------------------------------------


class TestMissionModeIsActive:
    """Test activation logic."""

    @pytest.fixture
    def mode(self):
        from qwenpaw.modes.mission import MissionMode

        return MissionMode()

    def test_active_from_session_state(self, mode):
        ctx = _make_hook_context(session_state={"mission_active": True})
        assert mode.is_active(ctx) is True

    def test_active_from_extras(self, mode):
        ctx = _make_hook_context(
            extras={"_mission_start": {"mission_active": True}},
        )
        assert mode.is_active(ctx) is True

    def test_inactive_when_nothing_set(self, mode):
        ctx = _make_hook_context()
        assert mode.is_active(ctx) is False

    def test_inactive_when_flag_false(self, mode):
        ctx = _make_hook_context(session_state={"mission_active": False})
        assert mode.is_active(ctx) is False
