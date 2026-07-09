# -*- coding: utf-8 -*-
"""Ralph gate — PRD-driven continuous loop with reviewer + deslop."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from qwenpaw.loop.gates.base import StopAction, StopHandlerResult
from qwenpaw.loop.gates.loop_gate import LoopGate

from ..shared.constants import RALPH_MAX_ITERATIONS
from ..shared.state import WorkflowState
from .prompts import build_continuation

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
        wf.write_state({
            "iteration": 0,
            "completed": False,
        })
        self.activate(state)
        return loop_dir

    async def check(self, ctx: Any) -> Optional[StopHandlerResult]:
        st: _RalphState | None = self._state()
        if st is None:
            return None

        wf = WorkflowState.from_existing(
            st.workspace_dir, "ralph", st.loop_dir,
        )
        data = wf.read_state()

        st.iteration = data.get("iteration", st.iteration) + 1

        if st.iteration > st.max_iterations:
            wf.cleanup()
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=f"Reached max iterations ({st.max_iterations})",
            )

        if data.get("completed", False):
            wf.cleanup()
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="All stories completed and verified",
            )

        wf.write_state({**data, "iteration": st.iteration})

        prd = wf.read_prd()
        prd_summary = _summarize_prd(prd)

        msg = build_continuation(
            iteration=st.iteration,
            max_iterations=st.max_iterations,
            critic_type=st.critic_type,
            no_deslop=st.no_deslop,
            loop_dir=st.loop_dir,
            prd_summary=prd_summary,
        )
        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=msg,
        )


def _summarize_prd(prd: dict) -> str:
    """Build a one-line PRD progress summary."""
    stories = prd.get("stories", [])
    if not stories:
        return "PRD: not yet created."
    done = sum(1 for s in stories if s.get("passes"))
    return f"PRD progress: {done}/{len(stories)} stories completed."
