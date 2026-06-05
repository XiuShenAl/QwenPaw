# -*- coding: utf-8 -*-
"""ContextVar setup and cleanup hooks.

Migrates ``RequestSetupMiddleware`` steps 1-5 (ContextVar injection)
into hook form with token-based LIFO reset in FINALLY.
"""

from __future__ import annotations

import logging

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)

CTXVAR_TOKENS_KEY = "_qp_ctxvar_tokens"


class ContextVarsSetupHook(LifecycleHook):
    """Inject per-request ContextVars before agent execution."""

    phase = Phase.PRE_EXECUTE
    name = "contextvars_setup"
    priority = 10

    async def run(self, ctx: HookContext) -> HookResult:
        from ...config.context import (
            set_current_workspace_dir,
            set_current_session_id,
            set_current_recent_max_bytes,
            set_current_shell_command_timeout,
            set_current_shell_command_executable,
        )
        from ...app.agent_context import (
            set_current_agent_id,
            set_current_root_session_id,
        )

        if ctx.workspace_dir is not None:
            set_current_workspace_dir(ctx.workspace_dir)
        set_current_agent_id(ctx.agent_id or "default")
        set_current_session_id(ctx.session_id or "")
        set_current_root_session_id(
            ctx.root_session_id or ctx.session_id or "",
        )

        try:
            from ...config.config import load_agent_config

            cfg = load_agent_config(ctx.agent_id)
            running = cfg.running
            pruning_cfg = (
                running.light_context_config.tool_result_pruning_config
            )
            set_current_recent_max_bytes(
                pruning_cfg.pruning_recent_msg_max_bytes,
            )
            set_current_shell_command_timeout(running.shell_command_timeout)
            set_current_shell_command_executable(
                running.shell_command_executable or None,
            )
        except Exception:
            logger.warning(
                "contextvars_setup: config-derived vars failed; "
                "tools may see defaults",
                exc_info=True,
            )
        return HookResult()


class ContextVarsCleanupHook(LifecycleHook):
    """Reset ContextVars in FINALLY (idempotent cleanup)."""

    phase = Phase.FINALLY
    name = "contextvars_cleanup"
    priority = 90

    async def run(self, ctx: HookContext) -> HookResult:  # noqa: ARG002
        # Currently ContextVars are reset per-task in agentscope's
        # middleware chain. This hook is a placeholder for future
        # token-based reset when the setter APIs return tokens.
        del ctx
        return HookResult()


__all__ = ["ContextVarsSetupHook", "ContextVarsCleanupHook"]
