# -*- coding: utf-8 -*-
"""Ralph gate — PRD-driven continuous loop with reviewer + deslop."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from qwenpaw.loop.gates.base import StopAction, StopHandlerResult
from qwenpaw.loop.gates.loop_gate import LoopGate

from ..shared.constants import RALPH_MAX_ITERATIONS
from ..shared.state import WorkflowState
from .prompts import build_continuation as _build_prompt

logger = logging.getLogger(__name__)


@dataclass
class _RalphState:
    loop_dir: Path
    workspace_dir: Path
    active: bool = True
    iteration: int = 0
    max_iterations: int = RALPH_MAX_ITERATIONS
    no_deslop: bool = False
    critic_type: str = "architect"
    prd_summary: str = ""


class RalphGate(LoopGate):
    """Stop gate for the Ralph PRD-driven loop."""

    @property
    def name(self) -> str:
        return "ralph"

    @property
    def priority(self) -> int:
        return 50

    def activate_for_ralph(
        self,
        workspace_dir: Path,
        no_deslop: bool = False,
        critic_type: str = "architect",
        max_iterations: int = RALPH_MAX_ITERATIONS,
    ) -> Path:
        wf = WorkflowState(workspace_dir, "ralph")
        loop_dir = wf.create_instance()
        state = _RalphState(
            loop_dir=loop_dir,
            workspace_dir=workspace_dir,
            max_iterations=max_iterations,
            no_deslop=no_deslop,
            critic_type=critic_type,
        )
        wf.write_state(
            {
                "iteration": 0,
                "completed": False,
            },
        )
        self.activate(state)
        return loop_dir

    async def check(self, ctx: Any) -> Optional[StopHandlerResult]:
        if isinstance(ctx, dict) and ctx.get("has_tool_calls"):
            return StopHandlerResult(action=StopAction.BYPASS)

        st: _RalphState | None = self._state()
        if st is None:
            return StopHandlerResult(
                action=StopAction.BYPASS,
            )

        wf = WorkflowState.from_existing(
            st.workspace_dir,
            "ralph",
            st.loop_dir,
        )
        data = await asyncio.to_thread(wf.read_state)

        st.iteration = data.get("iteration", st.iteration) + 1

        if st.iteration > st.max_iterations:
            await asyncio.to_thread(wf.cleanup)
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=f"Reached max iterations ({st.max_iterations})",
            )

        if data.get("completed", False):
            await asyncio.to_thread(wf.cleanup)
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason="All stories completed and verified",
            )

        await asyncio.to_thread(
            wf.write_state,
            {**data, "iteration": st.iteration},
        )

        prd = await asyncio.to_thread(wf.read_prd)
        st.prd_summary = _summarize_prd(prd)

        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason="Ralph iteration in progress",
        )

    def build_continuation(self) -> str:
        """Build Ralph continuation from gate state."""
        st: _RalphState | None = self._state()
        if st is None:
            return ""
        return _build_prompt(
            iteration=st.iteration,
            max_iterations=st.max_iterations,
            critic_type=st.critic_type,
            no_deslop=st.no_deslop,
            loop_dir=st.loop_dir,
            prd_summary=st.prd_summary,
        )


def _summarize_prd(prd: dict) -> str:
    """Build a one-line PRD progress summary."""
    stories = prd.get("stories", [])
    if not stories:
        return "PRD: not yet created."
    done = sum(1 for s in stories if s.get("passes"))
    return f"PRD progress: {done}/{len(stories)} stories completed."
