# -*- coding: utf-8 -*-
"""Unit tests for Phase 5 lifecycle hooks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.runtime.hooks import HookContext


def _make_ctx(**overrides) -> HookContext:
    defaults = {
        "request": SimpleNamespace(
            channel="console",
            user_id="u1",
        ),
        "session_id": "s1",
        "agent_id": "default",
        "root_session_id": "s1",
        "root_agent_id": "default",
        "workspace_dir": None,
        "kernel": None,
        "app_services": None,
    }
    defaults.update(overrides)
    return HookContext(**defaults)


# -------------------------------------------------------- SessionHooks


class TestSessionLoadHook:
    @pytest.mark.asyncio
    async def test_skips_when_no_kernel(self):
        from qwenpaw.hooks.session.session_hook import SessionLoadHook

        hook = SessionLoadHook()
        ctx = _make_ctx(kernel=None)
        r = await hook.run(ctx)
        assert r.action.value == "continue"

    @pytest.mark.asyncio
    async def test_skips_when_no_session(self):
        from qwenpaw.hooks.session.session_hook import SessionLoadHook

        hook = SessionLoadHook()
        kernel = SimpleNamespace(runner=SimpleNamespace(session=None))
        ctx = _make_ctx(kernel=kernel)
        r = await hook.run(ctx)
        assert r.action.value == "continue"


class TestSessionSaveHook:
    @pytest.mark.asyncio
    async def test_skips_when_no_agent(self):
        from qwenpaw.hooks.session.session_hook import SessionSaveHook

        hook = SessionSaveHook()
        kernel = SimpleNamespace(runner=SimpleNamespace(session=MagicMock()))
        ctx = _make_ctx(kernel=kernel)
        ctx.agent = None
        r = await hook.run(ctx)
        assert r.action.value == "continue"


# ------------------------------------------------------ ContextVarsHooks


class TestContextVarsSetupHook:
    @pytest.mark.asyncio
    async def test_sets_workspace_dir(self):
        from qwenpaw.hooks.request_setup.contextvars_hook import (
            ContextVarsSetupHook,
        )

        hook = ContextVarsSetupHook()
        ctx = _make_ctx(workspace_dir="/tmp/test")
        r = await hook.run(ctx)
        assert r.action.value == "continue"

    @pytest.mark.asyncio
    async def test_no_workspace_dir_still_works(self):
        from qwenpaw.hooks.request_setup.contextvars_hook import (
            ContextVarsSetupHook,
        )

        hook = ContextVarsSetupHook()
        ctx = _make_ctx(workspace_dir=None)
        r = await hook.run(ctx)
        assert r.action.value == "continue"


class TestContextVarsCleanupHook:
    @pytest.mark.asyncio
    async def test_cleanup_is_noop_without_prior_setup(self):
        from qwenpaw.hooks.request_setup.contextvars_hook import (
            ContextVarsCleanupHook,
        )

        hook = ContextVarsCleanupHook()
        ctx = _make_ctx()
        r = await hook.run(ctx)
        assert r.action.value == "continue"


# ---------------------------------------------------- PromptRefreshHook


class TestPromptRefreshHook:
    @pytest.mark.asyncio
    async def test_calls_rebuild_sys_prompt(self):
        from qwenpaw.hooks.prompt_refresh.prompt_refresh_hook import (
            PromptRefreshHook,
        )

        rebuild = MagicMock()
        agent = SimpleNamespace(rebuild_sys_prompt=rebuild)
        hook = PromptRefreshHook()
        ctx = _make_ctx()
        ctx.agent = agent
        await hook.run(ctx)
        rebuild.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_when_no_agent(self):
        from qwenpaw.hooks.prompt_refresh.prompt_refresh_hook import (
            PromptRefreshHook,
        )

        hook = PromptRefreshHook()
        ctx = _make_ctx()
        ctx.agent = None
        r = await hook.run(ctx)
        assert r.action.value == "continue"


# -------------------------------------------------------- SkillEnvHooks


class TestSkillEnvHook:
    @pytest.mark.asyncio
    async def test_stores_cm_in_extras(self):
        from qwenpaw.hooks.skill_env.skill_env_hook import (
            SkillEnvHook,
            _SKILL_ENV_CM_KEY,
        )

        mock_cm = MagicMock()
        with patch(
            "qwenpaw.agents.skill_system.apply_skill_config_env_overrides",
            return_value=mock_cm,
        ):
            hook = SkillEnvHook()
            ctx = _make_ctx()
            await hook.run(ctx)
            assert _SKILL_ENV_CM_KEY in ctx.extras
            mock_cm.__enter__.assert_called_once()


class TestSkillEnvCleanupHook:
    @pytest.mark.asyncio
    async def test_exits_cm_if_present(self):
        from qwenpaw.hooks.skill_env.skill_env_hook import (
            SkillEnvCleanupHook,
            _SKILL_ENV_CM_KEY,
        )

        mock_cm = MagicMock()
        hook = SkillEnvCleanupHook()
        ctx = _make_ctx()
        ctx.extras[_SKILL_ENV_CM_KEY] = mock_cm
        await hook.run(ctx)
        mock_cm.__exit__.assert_called_once_with(None, None, None)
        assert _SKILL_ENV_CM_KEY not in ctx.extras


# ---------------------------------------------------------- ErrorHooks


class TestErrorNormalizeHook:
    @pytest.mark.asyncio
    async def test_skips_when_no_error(self):
        from qwenpaw.hooks.error.error_hook import ErrorNormalizeHook

        hook = ErrorNormalizeHook()
        ctx = _make_ctx()
        ctx.error = None
        await hook.run(ctx)
        assert "_error_text" not in ctx.extras

    @pytest.mark.asyncio
    async def test_normalizes_error(self):
        from qwenpaw.hooks.error.error_hook import ErrorNormalizeHook

        hook = ErrorNormalizeHook()
        ctx = _make_ctx()
        ctx.error = RuntimeError("test error")
        ctx.agent = None
        with patch(
            "qwenpaw.exceptions.convert_model_exception",
        ) as mock_convert:
            mock_convert.return_value = SimpleNamespace(message="normalized")
            with patch(
                "qwenpaw.app.runner.query_error_dump.write_query_error_dump",
                side_effect=Exception("dump failed"),
            ):
                await hook.run(ctx)
        assert ctx.extras["_error_text"] == "normalized"


class TestCancelCleanupHook:
    @pytest.mark.asyncio
    async def test_skips_non_cancel_errors(self):
        from qwenpaw.hooks.error.error_hook import CancelCleanupHook

        hook = CancelCleanupHook()
        ctx = _make_ctx()
        ctx.error = ValueError("not a cancel")
        r = await hook.run(ctx)
        assert r.action.value == "continue"

    @pytest.mark.asyncio
    async def test_handles_keyboard_interrupt(self):
        from qwenpaw.hooks.error.error_hook import CancelCleanupHook

        hook = CancelCleanupHook()
        ctx = _make_ctx()
        ctx.error = KeyboardInterrupt()
        ctx.agent = None
        r = await hook.run(ctx)
        assert r.action.value == "continue"
