# -*- coding: utf-8 -*-
"""Autopilot continuation prompt templates — one per phase."""

from __future__ import annotations

from pathlib import Path

PHASES = ("expansion", "planning", "execution", "qa", "validation", "cleanup")


def build_continuation(
    phase: str,
    iteration: int,
    max_iterations: int,
    loop_dir: Path,
    skip_qa: bool = False,
    skip_validation: bool = False,
    validation_round: int = 0,
    max_validation_rounds: int = 3,
) -> str:
    """Return the controller prompt for the current phase."""
    builders = {
        "expansion": _expansion,
        "planning": _planning,
        "execution": _execution,
        "qa": _qa,
        "validation": _validation,
    }
    fn = builders.get(phase)
    if fn is None:
        return (
            f"Unknown phase: {phase}. " f"Valid phases: {', '.join(PHASES)}."
        )
    return fn(
        loop_dir=loop_dir,
        iteration=iteration,
        max_iterations=max_iterations,
        skip_qa=skip_qa,
        skip_validation=skip_validation,
        validation_round=validation_round,
        max_validation_rounds=max_validation_rounds,
    )


def _expansion(loop_dir: Path, **_kw) -> str:
    return f"""\
Autopilot Controller — phase: expansion.

Execute:
1. Analyze the task requirements.
2. Dispatch an analyst subagent to extract requirements:
   spawn_subagent(
       task="Analyze requirements and produce spec.md...",
       allowed_tools=["read_file", "grep_search", "glob_search",
                      "write_file", "execute_shell_command"],
       skills=[], background=true
   )
3. Dispatch an architect subagent to validate and expand the spec.
4. Write the final spec to {loop_dir}/spec.md.
5. Update {loop_dir}/state.json: set phase="planning"."""


def _planning(loop_dir: Path, **_kw) -> str:
    return f"""\
Autopilot Controller — phase: planning.

Execute:
1. Read {loop_dir}/spec.md.
2. Dispatch an architect subagent to create an implementation plan:
   spawn_subagent(
       task="Create implementation plan from spec...",
       allowed_tools=["read_file", "grep_search", "glob_search",
                      "write_file", "ast_search", "execute_shell_command"],
       skills=[], background=true
   )
3. Dispatch a critic subagent to review the plan.
4. Write the final plan to {loop_dir}/plan.md.
5. Update {loop_dir}/state.json: set phase="execution"."""


def _execution(loop_dir: Path, **_kw) -> str:
    return f"""\
Autopilot Controller — phase: execution.

Execute:
1. Read {loop_dir}/plan.md for the task list.
2. Identify independent tasks that can run in parallel.
3. Dispatch executor workers via batch mode:
   spawn_subagent(task="", batch=[
     {{"task": "<task 1 from plan>", "fork": true}},
     {{"task": "<task 2 from plan>", "fork": true}},
     ...
   ])
4. Poll each worker with check_agent_task (wait >= 30s between polls).
5. After all workers complete, verify outputs.
6. Update {loop_dir}/state.json: set phase="qa"."""


def _qa(loop_dir: Path, skip_qa: bool = False, **_kw) -> str:
    if skip_qa:
        return f"""\
Autopilot Controller — phase: qa (SKIPPED via --skip-qa).
Update {loop_dir}/state.json: set phase="validation"."""

    return f"""\
Autopilot Controller — phase: qa.

Execute the UltraQA-style 3-agent cycle:
1. Run the project test suite.
2. If all tests pass, update {loop_dir}/state.json: set phase="validation".
3. If tests fail:
   a. Dispatch architect subagent to diagnose root cause.
   b. Dispatch executor subagent to apply fixes.
   c. Re-run tests. Repeat up to 5 cycles."""


def _validation(
    loop_dir: Path,
    skip_validation: bool = False,
    validation_round: int = 0,
    max_validation_rounds: int = 3,
    **_kw,
) -> str:
    if skip_validation:
        return f"""\
Autopilot Controller — phase: validation (SKIPPED via --skip-validation).
Update {loop_dir}/state.json: set phase="cleanup"."""

    return f"""\
Autopilot Controller — phase: validation.
Validation round: {validation_round}/{max_validation_rounds}

WARNING: You are the Controller — do NOT review
code yourself. Dispatch subagents.

Execute parallel validation:
1. Use spawn_subagent batch mode for three reviewers:
   spawn_subagent(task="", batch=[
     {{
       "task": "REVIEW - Functional Completeness: "
               "Verify all spec requirements...",
       "allowed_tools": ["read_file", "grep_search",
                         "glob_search",
                         "execute_shell_command",
                         "ast_search"],
       "skills": []
     }},
     {{
       "task": "REVIEW - Security: Check for "
               "vulnerabilities, injection vectors...",
       "allowed_tools": ["read_file", "grep_search",
                         "glob_search",
                         "execute_shell_command",
                         "ast_search"],
       "skills": []
     }},
     {{
       "task": "REVIEW - Code Quality: Review code "
               "quality, maintainability...",
       "allowed_tools": ["read_file", "grep_search",
                         "glob_search",
                         "execute_shell_command",
                         "ast_search"],
       "skills": []
     }}
   ])
2. Wait for all reviewers to complete.
3. If ALL approve -> update {loop_dir}/state.json: set phase="cleanup".
4. If any reject -> fix issues -> increment validation_round -> re-validate.
5. If validation_round > {max_validation_rounds} -> STOP and report."""
