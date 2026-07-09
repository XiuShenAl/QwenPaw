# -*- coding: utf-8 -*-
"""Ultrawork continuation prompt templates."""

from __future__ import annotations

from pathlib import Path


def build_continuation(loop_dir: Path) -> str:
    """Build the controller prompt for the working phase."""
    return f"""\
You are the Ultrawork parallel execution controller.

Current phase: working

Execute:
1. Analyze the task and decompose it into independent sub-tasks.
2. For each sub-task, determine whether it depends on other sub-tasks.
3. Use spawn_subagent batch mode to dispatch all
   independent sub-tasks at once:
   spawn_subagent(batch=[
     {{"task": "<sub-task 1>", "fork": true,
       "allowed_tools": <per role config>}},
     {{"task": "<sub-task 2>", "fork": true,
       "allowed_tools": <per role config>}},
     ...
   ])
4. Use check_agent_task to poll each sub-task status
   (wait >= 30s between polls).
5. After all sub-tasks complete, summarize results.
6. Update {loop_dir}/state.json: set phase="done"."""
