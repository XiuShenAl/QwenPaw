# -*- coding: utf-8 -*-
"""Mission mode hooks — state load/save around the agent lifecycle."""

from __future__ import annotations

import logging
from pathlib import Path

from ..base import ModeGatedHook
from ...runtime.hooks import HookContext, HookResult
from ...runtime.phases import Phase
from ...agents.mission.constants import DEFAULT_MAX_ITERATIONS

logger = logging.getLogger(__name__)

_TERMINAL_PHASES = frozenset(
    (
        "completed",
        "max_iterations_reached",
        "aborted",
    ),
)


class MissionStateLoadHook(ModeGatedHook):
    """Load mission state from session into ``ctx.mode_state["mission"]``."""

    phase = Phase.PRE_AGENT_BUILD
    name = "mission_state_load"
    priority = 30
    after = ("session_load",)

    async def _run(self, ctx: HookContext) -> HookResult:
        state = ctx.session_state or {}
        payload = state.get("mission_payload")
        if not payload:
            return HookResult()
        ctx.mode_state.setdefault("mission", {})["state"] = payload
        return HookResult()


class MissionStateSaveHook(ModeGatedHook):
    """Persist mission state back to session after response.

    Also merges any ``_mission_start`` metadata set by the /mission
    slash command adapter into session state.
    """

    phase = Phase.POST_RESPONSE
    name = "mission_state_save"
    priority = 30

    async def _run(self, ctx: HookContext) -> HookResult:
        if ctx.session_state is None:
            ctx.session_state = {}

        # Merge mission start metadata from slash command adapter
        extras = getattr(ctx, "extras", None) or {}
        mission_start = extras.get("_mission_start")
        if mission_start:
            ctx.session_state.update(mission_start)

        # Persist mode_state mission payload
        ms = (ctx.mode_state.get("mission") or {}).get("state")
        if ms is not None:
            try:
                ctx.session_state["mission_payload"] = ms
            except Exception:
                logger.debug("mission_state_save: failed", exc_info=True)

        # Detect Phase 1→2 transition by reading loop_config.json from disk.
        # Only needed when current phase is prd_generation (waiting for user
        # confirmation). Phase 2 updates are handled by _run_mission_phase2.
        current_phase = ctx.session_state.get("mission_current_phase", "")
        if current_phase == "prd_generation":
            loop_dir = ctx.session_state.get("mission_loop_dir", "")
            if loop_dir:
                try:
                    from ...agents.mission.state import read_loop_config

                    cfg = read_loop_config(Path(loop_dir))
                    if cfg:
                        disk_phase = cfg.get("current_phase", "")
                        if disk_phase:
                            ctx.session_state[
                                "mission_current_phase"
                            ] = disk_phase
                        if disk_phase in _TERMINAL_PHASES:
                            ctx.session_state["mission_active"] = False
                except Exception:
                    logger.debug(
                        "mission_state_save: phase detection failed",
                        exc_info=True,
                    )

        return HookResult()


class MissionExecutionHook(ModeGatedHook):
    """Detect mission Phase 2 and signal the Runtime to use mission executor.

    Runs at PRE_EXECUTE. When the session indicates phase is
    ``execution_confirmed`` or ``execution``, stores the loop metadata
    in ``ctx.extras["_mission_phase2"]`` so Runtime replaces the standard
    AgentExecutor with the mission iteration engine.

    Also handles cleanup for completed/aborted missions.
    """

    phase = Phase.PRE_EXECUTE
    name = "mission_execution"
    priority = 50

    async def _run(self, ctx: HookContext) -> HookResult:
        session_state = ctx.session_state or {}
        extras = getattr(ctx, "extras", None) or {}

        # Determine current phase
        current_phase = session_state.get("mission_current_phase", "")

        # Also check if the agent just set execution_confirmed in this turn
        # (happens when Phase 1 agent writes loop_config with that phase)
        if not current_phase:
            mission_start = extras.get("_mission_start")
            if mission_start:
                current_phase = mission_start.get(
                    "mission_current_phase",
                    "prd_generation",
                )

        # Phase 1: let standard executor handle it
        if current_phase == "prd_generation" or not current_phase:
            return HookResult()

        # Terminal states: clear flag, run normally
        if current_phase in _TERMINAL_PHASES:
            session_state["mission_active"] = False
            ctx.session_state = session_state
            return HookResult()

        # Phase 2: signal Runtime to use mission executor
        if current_phase in ("execution_confirmed", "execution"):
            loop_dir = session_state.get("mission_loop_dir", "")
            max_iterations = session_state.get(
                "mission_max_iterations",
                DEFAULT_MAX_ITERATIONS,
            )
            if loop_dir:
                if ctx.extras is None:
                    ctx.extras = {}
                ctx.extras["_mission_phase2"] = {
                    "loop_dir": loop_dir,
                    "max_iterations": max_iterations,
                }
                logger.info(
                    "Mission Phase 2: signalling executor override, "
                    "loop_dir=%s",
                    loop_dir,
                )

        return HookResult()


__all__ = [
    "MissionStateLoadHook",
    "MissionStateSaveHook",
    "MissionExecutionHook",
]
