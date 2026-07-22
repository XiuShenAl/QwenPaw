# -*- coding: utf-8 -*-
"""Unit tests for fork worktree path + integration helpers."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

from qwenpaw.agents.fork_project import (
    begin_fork_scope,
    bind_workspace_integration_project,
    finalize_fork_worktree,
    forks_merged_into_head,
    mark_fork_failed,
    register_fork,
    resolve_allowed_fork_project_dir,
    resolve_integration_project_dir,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_FORK_GUARD = (
    _REPO_ROOT
    / "plugins"
    / "bundle"
    / "omp_workflows"
    / "shared"
    / "fork_guard.py"
)


def _load_fork_guard():
    spec = importlib.util.spec_from_file_location(
        "omp_fork_guard",
        _FORK_GUARD,
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")
    _git(path, "config", "user.email", "t@example.com")
    _git(path, "config", "user.name", "t")
    (path / "README").write_text("base\n", encoding="utf-8")
    _git(path, "add", "README")
    _git(path, "commit", "-m", "init")


def test_forks_integrated_rejects_truthy_strings() -> None:
    forks_integrated = _load_fork_guard().forks_integrated
    assert forks_integrated({"forks_integrated": "false"}) is False
    assert forks_integrated({"forks_integrated": "true"}) is False
    assert forks_integrated({"forks_integrated": True}) is False


def test_resolve_allowed_fork_project_dir(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    wt = project / ".qwenpaw" / "worktrees" / "abc"
    wt.mkdir(parents=True)
    outside = tmp_path / "other"
    outside.mkdir()

    assert (
        resolve_allowed_fork_project_dir(
            str(wt),
            workspace_dir=project,
        )
        == wt.resolve()
    )
    assert (
        resolve_allowed_fork_project_dir(
            str(outside),
            workspace_dir=project,
        )
        is None
    )


def test_failed_fork_blocks_current_scope_not_next(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ws"
    project = tmp_path / "proj"
    workspace.mkdir()
    _init_repo(project)
    bind_workspace_integration_project(workspace, project)

    scope1 = begin_fork_scope(workspace)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=workspace,
        scope_id=scope1,
    )
    mark_fork_failed(str(wt), branch, reason="cancelled")

    forks_integrated = _load_fork_guard().forks_integrated
    # Failed forks must not yield an empty-active pass in the same scope.
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is False
    )

    # New workflow scope — prior failed entries are pruned.
    scope2 = begin_fork_scope(workspace)
    assert scope2 != scope1
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is True
    )


def test_finalize_does_not_resurrect_pruned_fork(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _init_repo(project)
    scope1 = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope1,
    )
    (wt / "feat.txt").write_text("x\n", encoding="utf-8")

    # New scope supersedes + prunes the old pending entry.
    begin_fork_scope(project)
    assert finalize_fork_worktree(str(wt), branch, message="late") is False
    # No ghost finalized entry without scope should appear.
    assert forks_merged_into_head(project) is True


def test_gate_uses_integration_project_not_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "agent_ws"
    project = tmp_path / "code_proj"
    workspace.mkdir()
    _init_repo(project)

    scope = begin_fork_scope(workspace)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        session_id="s1",
        workspace_dir=workspace,
        scope_id=scope,
    )
    assert resolve_integration_project_dir(workspace) == project.resolve()

    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert finalize_fork_worktree(str(wt), branch, message="feat") is True

    forks_integrated = _load_fork_guard().forks_integrated
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is False
    )

    _git(project, "merge", "--no-ff", branch, "-m", "integrate")
    assert forks_merged_into_head(project, scope_id=scope) is True
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is True
    )


def test_unfinalized_tip_equals_base_does_not_pass(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)

    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        session_id="s1",
        workspace_dir=project,
        scope_id=scope,
    )

    assert forks_merged_into_head(project, scope_id=scope) is False

    # Explicit empty finalize (no_changes) is allowed.
    assert finalize_fork_worktree(str(wt), branch) is True
    assert forks_merged_into_head(project, scope_id=scope) is True


def test_commit_and_merge_verification(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)

    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        session_id="s1",
        workspace_dir=project,
        scope_id=scope,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert finalize_fork_worktree(str(wt), branch, message="worker feat")

    forks_integrated = _load_fork_guard().forks_integrated
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=project,
        )
        is False
    )

    _git(project, "merge", "--no-ff", branch, "-m", "integrate")
    assert forks_merged_into_head(project, scope_id=scope) is True
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=project,
        )
        is True
    )
