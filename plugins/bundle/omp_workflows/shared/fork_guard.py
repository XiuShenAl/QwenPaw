# -*- coding: utf-8 -*-
"""Hard checks for forked-worker integration before phase advance."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def forks_integrated(
    state: dict[str, Any] | None,
    workspace_dir: Path | str | None = None,
) -> bool:
    """Return True only when integration is explicitly and verifiably done.

    - ``forks_integrated`` must be the JSON/Python boolean ``True``.
    - Verification uses the coding-project registry (via workspace pointer)
      and the active fork *scope* started at mode activation.
    - Import / resolution failures fail closed.
    - Only active (pending/finalized) forks in the current scope are checked;
      failed/superseded/merged leftovers cannot block later runs.
    """
    if not isinstance(state, dict):
        return False
    if state.get("forks_integrated") is not True:
        return False
    if workspace_dir is None:
        return False
    try:
        from qwenpaw.agents.fork_project import (
            forks_merged_into_head,
            get_active_fork_scope,
            resolve_integration_project_dir,
        )
    except ImportError:
        return False

    project_dir = resolve_integration_project_dir(workspace_dir)
    if project_dir is None:
        return False
    scope_id = get_active_fork_scope(workspace_dir) or None
    return forks_merged_into_head(project_dir, scope_id=scope_id)


FORKS_INTEGRATED_REMINDER = """\
BLOCKED: forked worker results are not integrated yet.

{protocol}

Keep the current workflow phase unchanged (resume_phase / target phase
must stay as written — do NOT rewrite it to execution/exec/working).
After merges succeed, update state.json with the JSON boolean
forks_integrated=true (not a string). Then the gate resumes the
original target phase — do not re-dispatch executor workers.
"""


def merge_blocked_continuation(protocol: str) -> str:
    """Controller prompt when the gate rejects a premature phase advance."""
    return FORKS_INTEGRATED_REMINDER.format(protocol=protocol)
