# -*- coding: utf-8 -*-
"""Unit tests for fork worktree path + integration helpers."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from qwenpaw.agents.fork_project import (
    REGISTRY_REL,
    begin_fork_scope,
    bind_fork_task,
    bind_workspace_integration_project,
    finalize_fork_worktree,
    finalize_fork_worktree_or_fail,
    forks_merged_into_head,
    mark_fork_failed,
    register_fork,
    resolve_allowed_fork_project_dir,
    resolve_git_project_dir,
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
    # No workspace_dir → fail closed (cannot evaluate).
    assert forks_integrated({"forks_integrated": True}) is False


def test_gate_allows_no_project_when_flag_true(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Non-git workspace with no pointer: no-fork protocol must pass."""
    workspace = tmp_path / "agent_ws"
    workspace.mkdir()
    # Unrelated active agent with a coding project must not leak in.
    other = tmp_path / "other_proj"
    _init_repo(other)
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "other-agent",
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _aid: SimpleNamespace(
            coding_mode=SimpleNamespace(
                enabled=True,
                project_dir=str(other),
            ),
            workspace_dir=str(tmp_path / "other_ws"),
        ),
    )
    forks_integrated = _load_fork_guard().forks_integrated
    assert resolve_git_project_dir(workspace) is None
    assert resolve_integration_project_dir(workspace) is None
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is True
    )


def test_register_fork_requires_workspace_dir(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "code_proj"
    _init_repo(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    # No context and no agent-config fallback → refuse.
    monkeypatch.setattr(
        "qwenpaw.agents.fork_project._fallback_agent_workspace_dir",
        lambda **_kwargs: None,
    )
    assert register_fork(str(wt), branch, workspace_dir=None) is False
    # Refused → nothing in registry.
    assert forks_merged_into_head(project) is True


def test_register_fork_falls_back_to_agent_workspace(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "agent_ws"
    project = tmp_path / "code_proj"
    workspace.mkdir()
    _init_repo(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    monkeypatch.setattr(
        "qwenpaw.agents.fork_project._fallback_agent_workspace_dir",
        lambda **_kwargs: workspace.resolve(),
    )
    assert register_fork(str(wt), branch, workspace_dir=None) is True
    assert resolve_integration_project_dir(workspace) == project.resolve()


def test_bind_fork_task_does_not_create_ghost_entry(tmp_path: Path) -> None:
    """Without register_fork, bind_fork_task must not invent registry rows."""
    project = tmp_path / "code_proj"
    _init_repo(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    assert bind_fork_task(str(wt), branch, "task-ghost") is False
    assert forks_merged_into_head(project) is True


def test_register_fork_writes_pointer_on_agent_workspace(
    tmp_path: Path,
) -> None:
    """Dual-root: register must bind agent workspace → coding project."""
    workspace = tmp_path / "agent_ws"
    project = tmp_path / "code_proj"
    workspace.mkdir()
    _init_repo(project)
    # Workspace itself is also a git root (empty registry) — without a
    # pointer, gates would wrongly inspect the workspace.
    _init_repo(workspace)

    scope = begin_fork_scope(workspace)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=workspace,
        scope_id=scope,
    )
    assert resolve_integration_project_dir(workspace) == project.resolve()
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert finalize_fork_worktree(str(wt), branch, message="feat")

    forks_integrated = _load_fork_guard().forks_integrated
    # Unmerged fork on coding project must block (not workspace empty).
    assert (
        forks_integrated(
            {"forks_integrated": True},
            workspace_dir=workspace,
        )
        is False
    )
    assert forks_merged_into_head(project, scope_id=scope) is False


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


def test_finalize_does_not_resurrect_pruned_fork(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "repo"
    _init_repo(project)
    # Active agent pointing elsewhere must not steal begin_fork_scope prune.
    other = tmp_path / "other_proj"
    _init_repo(other)
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "other-agent",
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _aid: SimpleNamespace(
            coding_mode=SimpleNamespace(
                enabled=True,
                project_dir=str(other),
            ),
            workspace_dir=str(tmp_path / "other_ws"),
        ),
    )
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


def test_matching_agent_dual_root_bind(tmp_path: Path, monkeypatch) -> None:
    """Active agent may bind coding project only when workspace matches."""
    workspace = tmp_path / "agent_ws"
    project = tmp_path / "code_proj"
    workspace.mkdir()
    _init_repo(project)
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "agent-a",
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _aid: SimpleNamespace(
            coding_mode=SimpleNamespace(
                enabled=True,
                project_dir=str(project),
            ),
            workspace_dir=str(workspace),
        ),
    )
    scope = begin_fork_scope(workspace)
    assert scope
    assert resolve_integration_project_dir(workspace) == project.resolve()


def test_mark_fork_failed_waits_for_finalize_lock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Watchdog blocks on the finalize lock and cannot overwrite success."""
    from qwenpaw.agents import fork_project as fp

    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    registry = project / REGISTRY_REL

    hold = threading.Event()
    release = threading.Event()
    failed_done = threading.Event()
    real_commit = fp.commit_dirty_worktree

    def _slow_commit(worktree_path: str, message: str = "x") -> bool:
        hold.set()
        assert release.wait(timeout=10)
        return real_commit(worktree_path, message)

    monkeypatch.setattr(fp, "commit_dirty_worktree", _slow_commit)

    results: list[bool] = []

    def _run_finalize() -> None:
        results.append(
            finalize_fork_worktree(str(wt), branch, message="feat"),
        )

    def _watchdog() -> None:
        assert hold.wait(timeout=5)
        mark_fork_failed(str(wt), branch, reason="watchdog timeout")
        failed_done.set()

    t_fin = threading.Thread(target=_run_finalize)
    t_watch = threading.Thread(target=_watchdog)
    t_fin.start()
    t_watch.start()
    assert hold.wait(timeout=5)
    # Watchdog must stay blocked while git finalize still holds the lock.
    time.sleep(0.2)
    assert not failed_done.is_set()
    release.set()
    t_fin.join(timeout=10)
    assert failed_done.wait(timeout=5)
    t_watch.join(timeout=5)
    assert results == [True]
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["status"] == "finalized"


def test_recover_crashed_finalizing_clean_worktree(tmp_path: Path) -> None:
    """Crash leftover + clean worktree is healed to finalized."""
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    registry = project / REGISTRY_REL
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["forks"][branch]["status"] = "finalizing"
    registry.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    assert finalize_fork_worktree(str(wt), branch) is True
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["status"] == "finalized"
    assert after["forks"][branch]["no_changes"] is True


def test_recover_crashed_finalizing_dirty_worktree(tmp_path: Path) -> None:
    """Crash leftover + dirty worktree re-runs commit and finalizes."""
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    registry = project / REGISTRY_REL
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["forks"][branch]["status"] = "finalizing"
    registry.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")

    assert finalize_fork_worktree(str(wt), branch, message="feat") is True
    after = json.loads(registry.read_text(encoding="utf-8"))
    assert after["forks"][branch]["status"] == "finalized"
    assert after["forks"][branch]["no_changes"] is False


def test_finalize_idempotent_and_mark_failed_skips_finalized(
    tmp_path: Path,
) -> None:
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert finalize_fork_worktree(str(wt), branch, message="feat") is True
    # Second finalize path (console hook / watcher / check_agent_task).
    assert finalize_fork_worktree_or_fail(str(wt), branch) is True
    mark_fork_failed(str(wt), branch, reason="losing race")
    assert forks_merged_into_head(project, scope_id=scope) is False
    _git(project, "merge", "--no-ff", branch, "-m", "integrate")
    assert forks_merged_into_head(project, scope_id=scope) is True


def test_fork_registry_with_space_in_project_path(tmp_path: Path) -> None:
    """Paths with spaces must round-trip through register/finalize/merge."""
    project = tmp_path / "code project"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    assert register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")
    assert finalize_fork_worktree(str(wt), branch, message="feat")
    _git(project, "merge", "--no-ff", branch, "-m", "integrate")
    assert forks_merged_into_head(project, scope_id=scope) is True


def test_concurrent_finalize_is_serialized(tmp_path: Path) -> None:
    project = tmp_path / "repo"
    _init_repo(project)
    scope = begin_fork_scope(project)
    wt = project / ".qwenpaw" / "worktrees" / "w1"
    branch = "fork/w1"
    _git(project, "worktree", "add", str(wt), "-b", branch)
    register_fork(
        str(wt),
        branch,
        workspace_dir=project,
        scope_id=scope,
    )
    (wt / "feat.txt").write_text("feat\n", encoding="utf-8")

    results: list[bool] = []

    def _run() -> None:
        results.append(
            finalize_fork_worktree_or_fail(
                str(wt),
                branch,
                message="feat",
            ),
        )

    threads = [threading.Thread(target=_run) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert all(results)
    assert forks_merged_into_head(project, scope_id=scope) is False
    _git(project, "merge", "--no-ff", branch, "-m", "integrate")
    assert forks_merged_into_head(project, scope_id=scope) is True


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
