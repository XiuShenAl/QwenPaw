# -*- coding: utf-8 -*-
"""Autopilot gate — 6-phase pipeline with anti-stall detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from qwenpaw.loop.gates.base import StopAction, StopHandlerResult
from qwenpaw.loop.gates.loop_gate import LoopGate

from ..shared.constants import (
    AUTOPILOT_MAX_PHASE_ITERATIONS,
    AUTOPILOT_MAX_VALIDATION_ROUNDS,
    DEFAULT_MAX_ITERATIONS,
)
from ..shared.state import WorkflowState
from .prompts import build_continuation as _build_prompt

logger = logging.getLogger(__name__)


@dataclass
class _AutopilotState:
    loop_dir: Path
    workspace_dir: Path
    active: bool = True
    iteration: int = 0
    max_iterations: int = DEFAULT_MAX_ITERATIONS * 2
    phase_entry_iteration: dict[str, int] = field(
        default_factory=dict,
    )
    skip_qa: bool = False
    skip_validation: bool = False
    validation_round: int = 0
    max_validation_rounds: int = AUTOPILOT_MAX_VALIDATION_ROUNDS
    phase: str = "expansion"


class AutopilotGate(LoopGate):
    """Stop gate for the 6-phase Autopilot pipeline."""

    @property
    def name(self) -> str:
        return "autopilot"

    @property
    def priority(self) -> int:
        return 50

    def activate_for_autopilot(
        self,
        workspace_dir: Path,
        skip_qa: bool = False,
        skip_validation: bool = False,
    ) -> Path:
        wf = WorkflowState(workspace_dir, "autopilot")
        loop_dir = wf.create_instance()
        state = _AutopilotState(
            loop_dir=loop_dir,
            workspace_dir=workspace_dir,
            skip_qa=skip_qa,
            skip_validation=skip_validation,
        )
        wf.write_state(
            {
                "phase": "expansion",
                "validation_round": 0,
            },
        )
        self.activate(state)
        return loop_dir

    async def check(self, _ctx: Any) -> Optional[StopHandlerResult]:
        st: _AutopilotState | None = self._state()
        if st is None:
            return StopHandlerResult(
                action=StopAction.BYPASS,
            )

        wf = WorkflowState.from_existing(
            st.workspace_dir,
            "autopilot",
            st.loop_dir,
        )
        data = wf.read_state()

        st.iteration += 1

        if st.iteration > st.max_iterations:
            wf.cleanup()
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=f"Total iteration limit ({st.max_iterations})",
            )

        phase = data.get("phase", "expansion")
        st.phase = phase
        st.validation_round = data.get(
            "validation_round",
            st.validation_round,
        )

        if phase == "cleanup":
            wf.cleanup()
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason="Autopilot completed",
            )

        if phase not in st.phase_entry_iteration:
            st.phase_entry_iteration[phase] = st.iteration
        elif (
            st.iteration - st.phase_entry_iteration[phase]
            > AUTOPILOT_MAX_PHASE_ITERATIONS
        ):
            wf.cleanup()
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason=f"Phase '{phase}' stalled",
            )

        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason="Autopilot in progress",
        )

    def build_continuation(self) -> str:
        """Build Autopilot continuation from gate state."""
        st: _AutopilotState | None = self._state()
        if st is None:
            return ""
        return _build_prompt(
            phase=st.phase,
            iteration=st.iteration,
            max_iterations=st.max_iterations,
            loop_dir=st.loop_dir,
            skip_qa=st.skip_qa,
            skip_validation=st.skip_validation,
            validation_round=st.validation_round,
            max_validation_rounds=st.max_validation_rounds,
        )
