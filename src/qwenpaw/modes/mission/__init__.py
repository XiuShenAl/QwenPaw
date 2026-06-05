# -*- coding: utf-8 -*-
"""Mission mode — thin wrapper around ``agents/mission/``.

Strategy: **wrap first, rewrite later** ("先包后改").  The 2061-line
``agents/mission/`` package stays in place; this mode only exposes
hooks and a prompt contributor so the Runtime lifecycle drives
mission state load/save instead of the old middleware path.
"""

from __future__ import annotations

from ..base import AgentMode
from ...runtime.hooks import HookBase, HookContext


class MissionMode(AgentMode):
    """Bundle for mission-mode behaviour."""

    name = "mission"

    def hooks(self) -> list[HookBase]:
        from .hooks import MissionStateLoadHook, MissionStateSaveHook

        return [
            MissionStateLoadHook(owner_mode=self),
            MissionStateSaveHook(owner_mode=self),
        ]

    def prompt_contributors(self) -> list:
        from .contributor import MissionPromptContributor

        return [MissionPromptContributor(owner_mode=self)]

    def is_active(self, ctx: HookContext) -> bool:
        return bool((ctx.session_state or {}).get("mission_active"))


__all__ = ["MissionMode"]
