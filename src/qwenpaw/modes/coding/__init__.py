# -*- coding: utf-8 -*-
"""Coding mode — wraps ``agents/coding_mode_mixin.py`` as an ``AgentMode``.

Contributions:
- ``ProjectDirInjectionHook(PRE_AGENT_BUILD)`` — stashes ``project_dir``
  into ``ctx.mode_state["coding"]`` for downstream consumers.
- ``CodingModeContributor`` — system prompt injection (Phase 3,
  already registered in ``prompt_contributors.py``).
"""

from __future__ import annotations

from ..base import AgentMode
from ...runtime.hooks import HookBase, HookContext


class CodingMode(AgentMode):
    """Bundle for coding-mode behaviour."""

    name = "coding"

    def hooks(self) -> list[HookBase]:
        from .hooks import ProjectDirInjectionHook

        return [ProjectDirInjectionHook(owner_mode=self)]

    def is_active(self, ctx: HookContext) -> bool:
        cfg = ctx.agent_config
        if cfg is None:
            try:
                from ...config.config import load_agent_config

                cfg = load_agent_config(ctx.agent_id)
            except Exception:
                return False
        cm = getattr(cfg, "coding_mode", None)
        return bool(cm and getattr(cm, "enabled", False))


__all__ = ["CodingMode"]
