# -*- coding: utf-8 -*-
"""Bootstrap guidance hook.

Migrates ``agents/middlewares.py:BootstrapMiddleware`` logic — reads
``BOOTSTRAP.md`` from the workspace and injects guidance into the
first user message.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..base import LifecycleHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase

logger = logging.getLogger(__name__)


class BootstrapHook(LifecycleHook):
    """Inject BOOTSTRAP.md guidance into the first user message."""

    phase = Phase.PRE_EXECUTE
    name = "bootstrap"
    priority = 20

    async def run(self, ctx: HookContext) -> HookResult:
        wd = ctx.workspace_dir
        if not wd:
            return HookResult()
        bootstrap_file = Path(wd) / "BOOTSTRAP.md"
        if not bootstrap_file.exists():
            return HookResult()
        try:
            from ...agents.utils.file_handling import (
                read_text_file_with_encoding_fallback,
            )

            guidance = read_text_file_with_encoding_fallback(bootstrap_file)
            if guidance and ctx.input_msgs:
                from ...agents.hooks import BootstrapHook as _LegacyHook

                _hook = _LegacyHook(
                    working_dir=wd,
                    language=getattr(
                        getattr(ctx, "agent_config", None),
                        "language",
                        "zh",
                    ),
                )
                await _hook(ctx.agent, {"inputs": ctx.input_msgs})
        except Exception:
            logger.debug("bootstrap: injection failed", exc_info=True)
        return HookResult()


__all__ = ["BootstrapHook"]
