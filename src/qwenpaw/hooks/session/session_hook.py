# -*- coding: utf-8 -*-
"""Session load/save lifecycle hooks.

Migrates ``stream_query.py:L282-304`` (session load) and
``stream_query.py:L803-837`` (session save) into hook form.
"""

from __future__ import annotations

import logging

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class SessionLoadHook(LifecycleHook):
    """Load persisted session state before agent construction."""

    phase = Phase.PRE_AGENT_BUILD
    name = "session_load"
    priority = 10

    async def run(self, ctx: HookContext) -> HookResult:
        runner = getattr(ctx.kernel, "runner", None) if ctx.kernel else None
        if runner is None:
            return HookResult()
        session = getattr(runner, "session", None)
        if session is None:
            return HookResult()
        try:
            request = ctx.request
            user_id = getattr(request, "user_id", "") or ctx.session_id
            channel = getattr(request, "channel", "") or ""
            await session.load_session_state(
                session_id=ctx.session_id,
                user_id=user_id,
                channel=channel,
                agent=ctx.agent,
            )
        except KeyError as e:
            logger.debug(
                "session_load: skipped (schema mismatch): %s",
                e,
            )
        except Exception:
            logger.debug("session_load: failed", exc_info=True)
        return HookResult()


class SessionSaveHook(LifecycleHook):
    """Persist agent state after response completion."""

    phase = Phase.POST_RESPONSE
    name = "session_save"
    priority = 90

    async def run(self, ctx: HookContext) -> HookResult:
        runner = getattr(ctx.kernel, "runner", None) if ctx.kernel else None
        if runner is None:
            return HookResult()
        session = getattr(runner, "session", None)
        if session is None or ctx.agent is None:
            return HookResult()
        try:
            request = ctx.request
            user_id = getattr(request, "user_id", "") or ctx.session_id
            channel = getattr(request, "channel", "") or ""
            await session.save_session_state(
                session_id=ctx.session_id,
                user_id=user_id,
                channel=channel,
                agent=ctx.agent,
            )
        except Exception:
            logger.debug("session_save: failed", exc_info=True)
        return HookResult()


__all__ = ["SessionLoadHook", "SessionSaveHook"]
