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
        language = extras.get("language", "en")

        # _mission_start is set by the slash command adapter (first request);
        # mission_state is injected by AgentBuilder (subsequent requests).
        state = extras.get("_mission_start") or extras.get("mission_state")
        if not state or not state.get("mission_active"):
            return None

        try:
            from ...agents.mission.prompts import (
                build_mission_system_prompt,
            )

            return build_mission_system_prompt(
                state,
                workspace_dir=workspace_dir,
                agent_id=agent_id,
                language=language,
            )
        except Exception:
            logger.debug(
                "mission_prompt: contribute failed",
                exc_info=True,
            )
            return None


__all__ = ["MissionPromptContributor"]
