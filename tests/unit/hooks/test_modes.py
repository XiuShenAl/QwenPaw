# -*- coding: utf-8 -*-
"""Unit tests for Phase 5 mode implementations."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.runtime.hooks import HookContext


def _make_ctx(**overrides) -> HookContext:
    defaults = {
        "request": SimpleNamespace(channel="console"),
        "session_id": "s1",
        "agent_id": "default",
        "root_session_id": "s1",
        "root_agent_id": "default",
        "workspace_dir": None,
        "workspace": None,
        "app_services": None,
    }
    defaults.update(overrides)
    return HookContext(**defaults)


# ------------------------------------------------------------------ CodingMode


class TestCodingMode:
    def test_name(self):
        from qwenpaw.modes.coding import CodingMode

        assert CodingMode().name == "coding"

    def test_is_active_false_when_no_config(self):
        from qwenpaw.modes.coding import CodingMode

        ctx = _make_ctx()
        ctx.agent_config = None
        mode = CodingMode()
        assert mode.is_active(ctx) is False

    def test_is_active_true_when_enabled(self):
        from qwenpaw.modes.coding import CodingMode

        ctx = _make_ctx()
        ctx.agent_config = SimpleNamespace(
            coding_mode=SimpleNamespace(enabled=True),
        )
        assert CodingMode().is_active(ctx) is True

    def test_is_active_false_when_disabled(self):
        from qwenpaw.modes.coding import CodingMode

        ctx = _make_ctx()
        ctx.agent_config = SimpleNamespace(
            coding_mode=SimpleNamespace(enabled=False),
        )
        assert CodingMode().is_active(ctx) is False

    def test_hooks_returns_project_dir_injection(self):
        from qwenpaw.modes.coding import CodingMode

        mode = CodingMode()
        hooks = mode.hooks()
        assert len(hooks) == 1
        assert hooks[0].name == "coding_mode_project_dir"


class TestProjectDirInjectionHook:
    @pytest.mark.asyncio
    async def test_injects_project_dir(self):
        from qwenpaw.modes.coding import CodingMode
        from qwenpaw.modes.coding.hooks import ProjectDirInjectionHook

        mode = CodingMode()
        hook = ProjectDirInjectionHook(owner_mode=mode)
        ctx = _make_ctx()
        ctx.agent_config = SimpleNamespace(
            coding_mode=SimpleNamespace(enabled=True, project_dir="/tmp/proj"),
        )
        await hook.run(ctx)
        assert ctx.mode_state["coding"]["project_dir"] == "/tmp/proj"

    @pytest.mark.asyncio
    async def test_skips_when_mode_inactive(self):
        from qwenpaw.modes.coding import CodingMode
        from qwenpaw.modes.coding.hooks import ProjectDirInjectionHook

        mode = CodingMode()
        hook = ProjectDirInjectionHook(owner_mode=mode)
        ctx = _make_ctx()
        ctx.agent_config = SimpleNamespace(
            coding_mode=SimpleNamespace(enabled=False),
        )
        await hook.run(ctx)
        assert "coding" not in ctx.mode_state


# -------------------------------------------------------- MissionMode


class TestMissionMode:
    def test_name(self):
        from qwenpaw.modes.mission import MissionMode

        assert MissionMode().name == "mission"

    def test_is_active_false_by_default(self):
        from qwenpaw.modes.mission import MissionMode

        ctx = _make_ctx()
        ctx.session_state = {}
        assert MissionMode().is_active(ctx) is False

    def test_is_active_true_when_marked(self):
        from qwenpaw.modes.mission import MissionMode

        ctx = _make_ctx()
        ctx.session_state = {"mission_active": True}
        assert MissionMode().is_active(ctx) is True

    def test_hooks_returns_load_and_save(self):
        from qwenpaw.modes.mission import MissionMode

        mode = MissionMode()
        hooks = mode.hooks()
        names = {h.name for h in hooks}
        assert "mission_state_load" in names
        assert "mission_state_save" in names


class TestMissionStateLoadHook:
    @pytest.mark.asyncio
    async def test_skips_when_inactive(self):
        from qwenpaw.modes.mission import MissionMode
        from qwenpaw.modes.mission.hooks import MissionStateLoadHook

        mode = MissionMode()
        hook = MissionStateLoadHook(owner_mode=mode)
        ctx = _make_ctx()
        ctx.session_state = {}
        await hook.run(ctx)
        assert "mission" not in ctx.mode_state

    @pytest.mark.asyncio
    async def test_skips_when_no_payload(self):
        from qwenpaw.modes.mission import MissionMode
        from qwenpaw.modes.mission.hooks import MissionStateLoadHook

        mode = MissionMode()
        hook = MissionStateLoadHook(owner_mode=mode)
        ctx = _make_ctx()
        ctx.session_state = {"mission_active": True}
        await hook.run(ctx)
        assert ctx.mode_state.get("mission", {}).get("state") is None


class TestMissionStateSaveHook:
    @pytest.mark.asyncio
    async def test_skips_when_inactive(self):
        from qwenpaw.modes.mission import MissionMode
        from qwenpaw.modes.mission.hooks import MissionStateSaveHook

        mode = MissionMode()
        hook = MissionStateSaveHook(owner_mode=mode)
        ctx = _make_ctx()
        ctx.session_state = {}
        result = await hook.run(ctx)
        assert result.action.value == "continue"
