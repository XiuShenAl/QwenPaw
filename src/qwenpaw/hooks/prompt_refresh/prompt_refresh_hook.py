# -*- coding: utf-8 -*-
"""Prompt refresh hook.

Migrates ``stream_query.py:L369-372`` — refreshes the agent's system
prompt on each turn so edits to AGENTS.md / SOUL.md / PROFILE.md
take effect immediately.
"""

from __future__ import annotations

import logging

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class PromptRefreshHook(LifecycleHook):
    """Refresh system prompt before each agent execution."""

    phase = Phase.PRE_EXECUTE
    name = "prompt_refresh"
    priority = 30

    async def run(self, ctx: HookContext) -> HookResult:
        if ctx.agent is None:
            return HookResult()
        rebuild = getattr(ctx.agent, "rebuild_sys_prompt", None)
        if rebuild is not None:
            try:
                rebuild()
            except Exception:
                logger.debug("prompt_refresh: failed", exc_info=True)
        return HookResult()


__all__ = ["PromptRefreshHook"]
