# -*- coding: utf-8 -*-
"""Team pipeline continuation prompt templates."""

from __future__ import annotations

from pathlib import Path


def build_continuation(
    phase: str,
    iteration: int,
    max_iterations: int,
    agent_count: int,
    agent_role: str,
    loop_dir: Path,
    fix_attempts: int = 0,
    max_fix_attempts: int = 3,
) -> str:
    """Return the controller prompt for the current pipeline phase."""
    builders = {
        "plan": _plan,
        "prd": _prd,
        "exec": _exec,
        "verify": _verify,
        "fix": _fix,
    }
    fn = builders.get(phase)
    if fn is None:
        return f"Unknown phase: {phase}. Update state.json."
    return fn(
        loop_dir=loop_dir,
        agent_count=agent_count,
        agent_role=agent_role,
        fix_attempts=fix_attempts,
        max_fix_attempts=max_fix_attempts,
    )


def _plan(loop_dir: Path, **_kw) -> str:
    return f"""\
Team Pipeline Controller — phase: plan.

Execute:
1. Dispatch an explore subagent to map the codebase:
   spawn_subagent(
       task="Explore the codebase and map relevant "
            "files, modules, and dependencies.",
       allowed_tools=["read_file", "grep_search",
                      "glob_search", "ast_search"],
       skills=[], background=true
   )
2. After exploration, dispatch a planner subagent:
   spawn_subagent(
       task="Create an implementation plan with "
            "task breakdown and dependencies...",
       allowed_tools=["read_file", "grep_search", "glob_search",
                      "write_file", "ast_search"],
       skills=[], background=true
   )
3. Write the plan to {loop_dir}/handoffs/plan.md.
4. Update {loop_dir}/state.json: set current_phase="prd"."""


def _prd(loop_dir: Path, **_kw) -> str:
    return f"""\
Team Pipeline Controller — phase: prd.

Execute:
1. Read {loop_dir}/handoffs/plan.md for the task breakdown.
2. Dispatch an analyst subagent:
   spawn_subagent(
       task="Read the plan and define acceptance "
            "criteria for each sub-task...",
       allowed_tools=["read_file", "grep_search", "glob_search",
                      "write_file", "execute_shell_command"],
       skills=[], background=true
   )
3. Write the PRD to {loop_dir}/handoffs/prd.md.
4. Update {loop_dir}/state.json: set current_phase="exec"."""


def _exec(
    loop_dir: Path,
    agent_count: int = 3,
    agent_role: str = "executor",
    **_kw,
) -> str:
    return f"""\
Team Pipeline Controller — phase: exec.
Workers: {agent_count}, Role: {agent_role}

Execute:
1. Read {loop_dir}/handoffs/prd.md for sub-tasks and acceptance criteria.
2. Dispatch {agent_count} workers via batch mode:
   spawn_subagent(batch=[
     {{
       "task": "You are Team Worker agent-001.\\n\\nTask: <sub-task 1>\\n\\
Write your result to {loop_dir}/results/agent-001.json",
       "fork": true,
       "allowed_tools": <per {agent_role} role config>
     }},
     ...repeat for each worker...
   ])
3. Poll each worker with check_agent_task (wait >= 30s between polls).
4. After all complete, read {loop_dir}/results/ files and summarize.
5. Write the summary to {loop_dir}/handoffs/exec-summary.md.
6. Update {loop_dir}/state.json: set current_phase="verify"."""


def _verify(loop_dir: Path, **_kw) -> str:
    return f"""\
Team Pipeline Controller — phase: verify.

Execute:
1. Read {loop_dir}/handoffs/exec-summary.md.
2. Dispatch three reviewers via batch mode:
   spawn_subagent(batch=[
     {{
       "task": "VERIFY: Check code changes for "
               "correctness and completeness...",
       "allowed_tools": ["read_file", "grep_search", "glob_search",
                         "execute_shell_command", "ast_search"],
       "skills": []
     }},
     {{
       "task": "SECURITY REVIEW: Check for security vulnerabilities...",
       "allowed_tools": ["read_file", "grep_search", "glob_search",
                         "execute_shell_command", "ast_search"],
       "skills": []
     }},
     {{
       "task": "CODE REVIEW: Review code quality and conventions...",
       "allowed_tools": ["read_file", "grep_search", "glob_search",
                         "execute_shell_command", "ast_search"],
       "skills": []
     }}
   ])
3. If ALL pass -> update {loop_dir}/state.json: set current_phase="completed".
4. If any fail -> write report to {loop_dir}/handoffs/verify-report.md
   -> update state.json: set current_phase="fix"."""


def _fix(
    loop_dir: Path,
    fix_attempts: int = 0,
    max_fix_attempts: int = 3,
    **_kw,
) -> str:
    return f"""\
Team Pipeline Controller — phase: fix.
Fix attempt: {fix_attempts}/{max_fix_attempts}

Execute:
1. Read {loop_dir}/handoffs/verify-report.md for failure details.
2. Dispatch a debugger subagent to fix the issues:
   spawn_subagent(
       task="Fix the following issues from verification:\\n<issues>",
       background=true
   )
3. After fix, update {loop_dir}/state.json: set current_phase="verify"."""
