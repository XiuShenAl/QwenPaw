# -*- coding: utf-8 -*-
"""Mission mode prompt contributor.

Delegates to ``agents/mission/prompts.py``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...runtime.prompt_manager import SyncPromptContributor

if TYPE_CHECKING:
    from ..base import AgentMode

logger = logging.getLogger(__name__)


class MissionPromptContributor(SyncPromptContributor):
    """Inject mission guidance into the system prompt.

    Uses ``ctx.extras`` to read mission state (compatible with
    the ``SimpleNamespace`` passed by ``AgentBuilder.build_prompt``).
    """

    name = "mission_prompt"
    priority = 25

    def __init__(self, owner_mode: "AgentMode") -> None:
        self.owner_mode = owner_mode

    def contribute_sync(self, ctx: object) -> str | None:
        extras = getattr(ctx, "extras", None) or {}
        workspace_dir = str(getattr(ctx, "workspace_dir", "") or "")
        agent_id = str(getattr(ctx, "agent_id", "default") or "default")

        # Check if mission is active via agent_config session state
        # or via the _mission_start signal from slash command
        mission_start = extras.get("_mission_start")
        if mission_start and mission_start.get("mission_active"):
            try:
                from ...agents.mission.prompts import (
                    build_mission_system_prompt,
                )

                return build_mission_system_prompt(
                    mission_start,
                    workspace_dir=workspace_dir,
                    agent_id=agent_id,
                )
            except Exception:
                logger.debug(
                    "mission_prompt: contribute failed",
                    exc_info=True,
                )
                return None

        # Try reading from session state stored in extras
        mission_state = extras.get("mission_state")
        if mission_state and mission_state.get("mission_active"):
            try:
                from ...agents.mission.prompts import (
                    build_mission_system_prompt,
                )

                return build_mission_system_prompt(
                    mission_state,
                    workspace_dir=workspace_dir,
                    agent_id=agent_id,
                )
            except Exception:
                logger.debug(
                    "mission_prompt: contribute failed",
                    exc_info=True,
                )
                return None

        return None


__all__ = ["MissionPromptContributor"]
