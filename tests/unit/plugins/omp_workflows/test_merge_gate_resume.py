# -*- coding: utf-8 -*-
"""Merge-gate resume: keep target phase, do not replay execution."""

# pylint: disable=wrong-import-position,protected-access

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[4]
_BUNDLE = _REPO / "plugins" / "bundle"
if str(_BUNDLE) not in sys.path:
    sys.path.insert(0, str(_BUNDLE))

from omp_workflows.autopilot.gate import AutopilotGate  # noqa: E402
from omp_workflows.shared.state import WorkflowState  # noqa: E402
from omp_workflows.team.gate import TeamPipelineGate  # noqa: E402
from omp_workflows.ultrawork.gate import UltraworkGate  # noqa: E402


@pytest.mark.asyncio
async def test_autopilot_preserves_qa_and_skips_exec_replay(
    tmp_path: Path,
) -> None:
    gate = AutopilotGate()
    loop_dir = gate.activate_for_autopilot(tmp_path)
    wf = WorkflowState.from_existing(tmp_path, "autopilot", loop_dir)
    wf.write_state({"phase": "qa", "forks_integrated": False})

    await gate.check({})
    st = gate._state()
    assert st is not None
    assert st.blocked_on_merge is True
    assert st.phase == "qa"
    assert wf.read_state().get("phase") == "qa"
    assert wf.read_state().get("resume_phase") == "qa"
    cont = gate.build_continuation()
    assert "spawn_subagent" not in cont
    assert "forks_integrated" in cont

    wf.update_state({"forks_integrated": True})
    await gate.check({})
    st = gate._state()
    assert st is not None
    assert st.blocked_on_merge is False
    assert st.phase == "qa"
    cont2 = gate.build_continuation()
    # Resumes QA — must not rebuild the parallel executor dispatch prompt.
    assert "phase: qa" in cont2 or "phase: qa" in cont2.lower()
    assert '"fork": true' not in cont2
    assert "batch=[" not in cont2


@pytest.mark.asyncio
async def test_team_preserves_verify_phase(tmp_path: Path) -> None:
    gate = TeamPipelineGate()
    loop_dir = gate.activate_for_team(tmp_path)
    wf = WorkflowState.from_existing(tmp_path, "team", loop_dir)
    wf.write_state(
        {
            "current_phase": "verify",
            "forks_integrated": False,
        },
    )
    await gate.check({})
    st = gate._state()
    assert st is not None
    assert st.phase == "verify"
    assert wf.read_state().get("current_phase") == "verify"
    assert "spawn_subagent" not in gate.build_continuation()


@pytest.mark.asyncio
async def test_ultrawork_keeps_done_phase(tmp_path: Path) -> None:
    gate = UltraworkGate()
    loop_dir = gate.activate_for_work(tmp_path)
    wf = WorkflowState.from_existing(tmp_path, "ultrawork", loop_dir)
    wf.write_state({"phase": "done", "forks_integrated": False})
    await gate.check({})
    st = gate._state()
    assert st is not None
    assert st.phase == "done"
    assert wf.read_state().get("phase") == "done"
    assert "spawn_subagent" not in gate.build_continuation()
