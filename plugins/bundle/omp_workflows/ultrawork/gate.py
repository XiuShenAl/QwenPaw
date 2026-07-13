# -*- coding: utf-8 -*-
"""Ultrawork gate — two-phase working/done gate."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from qwenpaw.loop.gates.base import StopAction, StopHandlerResult
from qwenpaw.loop.gates.loop_gate import LoopGate

from ..shared.state import WorkflowState
from .prompts import build_continuation as _build_prompt

logger = logging.getLogger(__name__)


@dataclass
class _UltraworkState:
    loop_dir: Path
    workspace_dir: Path
    active: bool = True
    phase: str = "working"


class UltraworkGate(LoopGate):
    """Stop gate for Ultrawork parallel execution."""

    @property
    def name(self) -> str:
        return "ultrawork"

    @property
    def priority(self) -> int:
        return 50

    def activate_for_work(self, workspace_dir: Path) -> Path:
        """Create state directory and activate."""
        wf = WorkflowState(workspace_dir, "ultrawork")
        loop_dir = wf.create_instance()
        state = _UltraworkState(
            loop_dir=loop_dir,
            workspace_dir=workspace_dir,
        )
        wf.write_state({"phase": "working"})
        self.activate(state)
        return loop_dir

    async def check(self, _ctx: Any) -> Optional[StopHandlerResult]:
        st: _UltraworkState | None = self._state()
        if st is None:
            return StopHandlerResult(
                action=StopAction.BYPASS,
            )

        wf = WorkflowState.from_existing(
            st.workspace_dir,
            "ultrawork",
            st.loop_dir,
        )
        data = wf.read_state()

        phase = data.get("phase", st.phase)
        st.phase = phase

        if phase == "done":
            wf.cleanup()
            self.deactivate()
            return StopHandlerResult(
                action=StopAction.TERMINATE,
                reason="Ultrawork completed",
            )

        return StopHandlerResult(
            action=StopAction.INTERRUPT_AND_CONTINUE,
            reason="Ultrawork in progress",
        )

    def build_continuation(self) -> str:
        """Build Ultrawork continuation from gate state."""
        st: _UltraworkState | None = self._state()
        if st is None:
            return ""
        return _build_prompt(st.loop_dir)
