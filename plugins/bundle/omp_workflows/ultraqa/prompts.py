# -*- coding: utf-8 -*-
"""UltraQA continuation prompt templates."""

from __future__ import annotations

from pathlib import Path


def build_continuation(
    cycle: int,
    max_cycles: int,
    goal_type: str,
    custom_cmd: str,
    last_failures: list[str],
    loop_dir: Path,
    interactive: bool = False,
) -> str:
    """Build the controller continuation message for one QA cycle."""
    failures_summary = (
        "\n".join(f"  - {f}" for f in last_failures[-5:])
        if last_failures
        else "  (none)"
    )

    qa_step = (
        _interactive_step()
        if interactive
        else _command_step(goal_type, custom_cmd)
    )

    return f"""\
UltraQA cycle {cycle}/{max_cycles}.
Goal: {goal_type}
Previous failures:
{failures_summary}

Execute this cycle:

1. {qa_step}
2. If all checks PASS, update {loop_dir}/state.json: set qa_passed=true.
3. If checks FAIL, dispatch an architect subagent to diagnose root cause:
   spawn_subagent(
       task="DIAGNOSE FAILURE:\\nGoal: {goal_type}\\n\
Output: <paste QA output>\\n\
Provide root cause analysis and fix recommendations.",
       allowed_tools=["read_file", "grep_search", "glob_search",
                      "write_file", "ast_search", "execute_shell_command"],
       skills=[],
       background=True
   )
4. After diagnosis completes, dispatch an executor subagent to apply the fix:
   spawn_subagent(
       task="FIX:\\nIssue: <architect diagnosis>\\nFiles: <affected files>\\n\\
Apply the fix precisely as recommended.",
       background=True
   )
5. After the fix, update {loop_dir}/state.json
   with the latest last_failures."""


def _command_step(goal_type: str, custom_cmd: str) -> str:
    cmd_map = {
        "tests": "Run the project test suite.",
        "build": "Run the project build.",
        "lint": "Run the linter.",
        "typecheck": "Run the type checker.",
    }
    if goal_type == "custom" and custom_cmd:
        return f"Run the QA command: `{custom_cmd}`"
    return cmd_map.get(goal_type, "Run the project test suite.")


def _interactive_step() -> str:
    return (
        "Dispatch a qa-tester subagent for interactive testing:\n"
        "   spawn_subagent(\n"
        '       task="TEST:\\nGoal: <goal>\\nService: <how to start>\\n'
        'Test cases: <scenarios>",\n'
        '       allowed_tools=["read_file",\n'
        '                      "grep_search",\n'
        '                      "glob_search",\n'
        '                      "execute_shell_command"],\n'
        "       skills=[],\n"
        "       background=True\n"
        "   )"
    )
