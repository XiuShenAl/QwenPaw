# -*- coding: utf-8 -*-
"""UltraQA gate — 3-agent QA cycle with stop conditions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from qwenpaw.loop.gates.base import StopAction, StopHandlerResult
from qwenpaw.loop.gates.loop_gate import LoopGate

from ..shared.constants import ULTRAQA_MAX_CYCLES, ULTRAQA_MAX_SAME_FAILURE
from ..shared.state import WorkflowState
from .prompts import build_continuation

logger = logging.getLogger(__name__)


@dataclass
class _UltraQAState:
    loop_dir: Path
    workspace_dir: Path
    active: bool = True
    cycle: int = 0
    max_cycles: int = ULTRAQA_MAX_CYCLES
    goal_type: str = "tests"
    custom_cmd: str = ""
    interactive: bool = False
    qa_passed: bool = False
    last_failures: list[str] = field(default_factory=list)


class UltraQAGate(LoopGate):
    """Stop gate for the UltraQA 3-agent cycle."""

    @property
    def name(self) -> str:
        return "ultraqa"

    @property
    def priority(self) -> int:
        return 50

    def activate_for_qa(
        self,
        workspace_dir: Path,
        goal_type: str = "tests",
        custom_cmd: str = "",
        interactive: bool = False,
        max_cycles: int = ULTRAQA_MAX_CYCLES,
    ) -> Path:
        """Create state directory and activate the gate."""
        wf = WorkflowState(workspace_dir, "ultraqa")
        loop_dir = wf.create_instance()
        state = _UltraQAState(
            loop_dir=loop_dir,
            workspace_dir=workspace_dir,
            max_cycles=max_cycles,
            goal_type=goal_type,
            custom_cmd=custom_cmd,
            interactive=interactive,
        )
        wf.write_state({"cycle": 0, "qa_passed": False, "last_failures": []})
        self.activate(state)
        return loop_dir

    async def check(self, ctx: Any) -> Optional[StopHandlerResult]:
        st: _UltraQAState | None = self._state()
        if st is None:
            return None

        wf = WorkflowState.from_existing(
            st.workspace_dir, "ultraqa", st.loop_dir,
        )
        data = wf.read_state()

        st.qa_passed = data.get("qa_passed", False)
        st.last_failures = data.get("last_failures", st.last_failures)
        st.cycle = data.get("cycle", st.cycle)

        if st.qa_passed:
            wf.cleanup()
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="QA goals achieved",
            )

        if st.cycle >= st.max_cycles:
            wf.cleanup()
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.STOP,
                reason=f"Reached max cycles ({st.max_cycles})",
            )

        if _repeated_failure(st.last_failures, ULTRAQA_MAX_SAME_FAILURE):
            wf.cleanup()
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.STOP,
                reason="Same failure repeated too many times",
            )

        st.cycle += 1
        wf.write_state({
            "cycle": st.cycle,
            "qa_passed": False,
            "last_failures": st.last_failures,
        })

        msg = build_continuation(
            cycle=st.cycle,
            max_cycles=st.max_cycles,
            goal_type=st.goal_type,
            custom_cmd=st.custom_cmd,
            last_failures=st.last_failures,
            loop_dir=st.loop_dir,
            interactive=st.interactive,
        )
        return StopHandlerResult(
            action=StopAction.CONTINUE,
            continuation_message=msg,
        )


def _repeated_failure(failures: list[str], threshold: int) -> bool:
    """Check if the most recent failure has repeated >= threshold times."""
    if len(failures) < threshold:
        return False
    last = failures[-1]
    return all(f == last for f in failures[-threshold:])
