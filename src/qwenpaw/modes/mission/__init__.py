# -*- coding: utf-8 -*-
"""Mission mode — ``AgentMode`` for autonomous iterative tasks.

Exposes hooks and a prompt contributor so the Runtime lifecycle drives
mission state load/save.  Domain logic (state machine, PRD generation,
iteration loop) lives in ``agents.mission``.
"""

from __future__ import annotations

from ..base import AgentMode
from ...runtime.hooks import HookBase, HookContext


class MissionMode(AgentMode):
    """Bundle for mission-mode behaviour."""

    name = "mission"

    def hooks(self) -> list[HookBase]:
        from .hooks import (
            MissionExecutionHook,
            MissionStateLoadHook,
            MissionStateSaveHook,
        )

        return [
            MissionStateLoadHook(owner_mode=self),
            MissionStateSaveHook(owner_mode=self),
            MissionExecutionHook(owner_mode=self),
        ]

    def prompt_contributors(self) -> list:
        from .contributor import MissionPromptContributor

        return [MissionPromptContributor(owner_mode=self)]

    def is_active(self, ctx: HookContext) -> bool:
        # Check session state (subsequent requests)
        if (ctx.session_state or {}).get("mission_active"):
            return True
        # Check extras from slash command adapter (first request only).
        # This is safe because extras is per-request — a new HookContext
        # is created for every Runtime.run() invocation, so stale extras
        # from a previous request cannot leak.
        extras = getattr(ctx, "extras", None) or {}
        mission_start = extras.get("_mission_start")
        if mission_start and mission_start.get("mission_active"):
            return True
        return False


__all__ = ["MissionMode"]
