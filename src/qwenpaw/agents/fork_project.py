# -*- coding: utf-8 -*-
"""Fork worktree path validation and integration registry."""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# Windows msvcrt.LK_LOCK only retries ~10s then raises. Use LK_NBLCK + poll
# so blocking acquire can wait for a long finalize (git add/commit).
_WINDOWS_LOCK_POLL_S = 0.05
_WINDOWS_LOCK_CONFLICT_ERRNOS = frozenset(
    {
        errno.EDEADLK,
        errno.EACCES,
        errno.EAGAIN,
        getattr(errno, "EWOULDBLOCK", errno.EAGAIN),
    },
)

WORKTREE_REL = Path(".qwenpaw") / "worktrees"
REGISTRY_REL = Path(".qwenpaw") / "fork_registry.json"
# Written in the *agent workspace* so OMP gates can find the coding-project
# registry when ``coding_mode.project_dir != workspace_dir``.
INTEGRATION_PROJECT_REL = Path(".qwenpaw") / "fork_integration_project"
ACTIVE_SCOPE_REL = Path(".qwenpaw") / "fork_active_scope"

# Terminal statuses are ignored by gate verification (won't block later runs).
_STATUS_PENDING = "pending"
_STATUS_FINALIZING = "finalizing"
_STATUS_FINALIZED = "finalized"
_STATUS_FAILED = "failed"
_STATUS_MERGED = "merged"
_STATUS_SUPERSEDED = "superseded"
# finalizing counts as active so merge gates stay blocked until commit lands.
_ACTIVE_STATUSES = frozenset(
    {_STATUS_PENDING, _STATUS_FINALIZING, _STATUS_FINALIZED},
)

FORK_WORKER_COMMIT_PROTOCOL = """\
## Fork worktree commit protocol (REQUIRED)
You are running inside an isolated git worktree. Relative file/shell
paths resolve to this worktree, not the main workspace.
Before you finish:
1. `git add -A`
2. `git commit -m \"<concise summary of your changes>\"`
   (skip the commit only when `git status` is already clean)
Uncommitted worktree changes cannot be merged into the main branch.
If the task asks you to write under an absolute path outside this
worktree (e.g. a workflow results dir), use that absolute path as given.
"""


def resolve_allowed_fork_project_dir(
    fork_project: str | None,
    *,
    workspace_dir: str | Path | None = None,
    coding_project_dir: str | Path | None = None,
) -> Path | None:
    """Return a validated fork worktree path, or None if rejected."""
    if not isinstance(fork_project, str) or not fork_project.strip():
        return None
    try:
        resolved = Path(fork_project).expanduser().resolve()
    except OSError:
        return None
    if not resolved.is_dir():
        return None

    bases: list[Path] = []
    for raw in (coding_project_dir, workspace_dir):
        if not raw:
            continue
        try:
            bases.append(Path(raw).expanduser().resolve())
        except OSError:
            continue
    seen: set[Path] = set()
    for base in bases:
        if base in seen:
            continue
        seen.add(base)
        allowed = (base / WORKTREE_REL).resolve()
        try:
            resolved.relative_to(allowed)
            return resolved
        except ValueError:
            continue
    logger.warning(
        "Rejected fork_project_dir outside allowed worktree subtree: %s",
        fork_project,
    )
    return None


def _registry_path_for_project(project_dir: Path) -> Path:
    return project_dir / REGISTRY_REL


def project_dir_from_worktree(worktree_path: Path) -> Path:
    """``<project>/.qwenpaw/worktrees/<id>`` → ``<project>``."""
    return worktree_path.expanduser().resolve().parent.parent.parent


def _lock_file_acquire(lock_file: Any, *, blocking: bool) -> bool:
    """Acquire an exclusive lock on an open file; return success.

    On Windows, ``msvcrt.LK_LOCK`` only retries for ~10 seconds then raises
    ``OSError`` — too short for a slow ``git commit``. Blocking mode instead
    polls with ``LK_NBLCK`` until the lock is acquired (or a non-conflict
    I/O error occurs). Callers already run this off the event loop.
    """
    if os.name == "nt":
        import msvcrt

        lock_file.seek(0)
        if lock_file.read(1) == "":
            lock_file.write("0")
            lock_file.flush()
        while True:
            lock_file.seek(0)
            try:
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                return True
            except OSError as exc:
                if not blocking:
                    return False
                if exc.errno in _WINDOWS_LOCK_CONFLICT_ERRNOS:
                    time.sleep(_WINDOWS_LOCK_POLL_S)
                    continue
                raise

    import fcntl

    flag = fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        fcntl.flock(lock_file.fileno(), flag)
        return True
    except (BlockingIOError, OSError):
        if blocking:
            raise
        return False


def _lock_file_release(lock_file: Any) -> None:
    """Release an exclusive lock acquired by ``_lock_file_acquire``."""
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


@contextmanager
def _exclusive_file_lock(
    lock_path: Path,
    *,
    blocking: bool = True,
) -> Iterator[bool]:
    """Acquire an exclusive file lock; yields whether the lock was acquired."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        acquired = False
        try:
            acquired = _lock_file_acquire(lock_file, blocking=blocking)
            yield acquired
        finally:
            if acquired:
                _lock_file_release(lock_file)


@contextmanager
def _registry_lock(project_dir: Path) -> Iterator[None]:
    """Exclusive lock around registry read-modify-write."""
    lock_path = _registry_path_for_project(project_dir).with_suffix(
        ".json.lock",
    )
    # Dedicated lock file so Windows can replace the JSON atomically.
    with _exclusive_file_lock(lock_path, blocking=True) as acquired:
        if not acquired:
            raise RuntimeError(f"failed to acquire registry lock: {lock_path}")
        yield


def _fork_finalize_lock_path(project_dir: Path, branch: str) -> Path:
    digest = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:24]
    return project_dir / ".qwenpaw" / "fork_locks" / f"{digest}.lock"


@contextmanager
def _fork_finalize_lock(
    project_dir: Path,
    branch: str,
    *,
    blocking: bool = True,
) -> Iterator[bool]:
    """Serialize finalize/fail (including git) for one branch.

    Held for the whole critical section so a second path cannot start
    ``git add``/``commit`` (or mark failed) while the owner is alive.
    A crashed owner releases the OS lock automatically.
    """
    with _exclusive_file_lock(
        _fork_finalize_lock_path(project_dir, branch),
        blocking=blocking,
    ) as acquired:
        yield acquired


def bind_workspace_integration_project(
    workspace_dir: str | Path | None,
    project_dir: str | Path,
) -> None:
    """Point the agent workspace at the git project that owns fork registry."""
    if workspace_dir is None:
        return
    try:
        ws = Path(workspace_dir).expanduser().resolve()
        proj = Path(project_dir).expanduser().resolve()
    except OSError:
        return
    pointer = ws / INTEGRATION_PROJECT_REL
    try:
        pointer.parent.mkdir(parents=True, exist_ok=True)
        pointer.write_text(str(proj) + "\n", encoding="utf-8")
    except OSError:
        logger.warning(
            "Failed to write fork integration project pointer %s",
            pointer,
            exc_info=True,
        )


def resolve_git_project_dir(
    workspace_dir: str | Path | None,
    *,
    agent_id: str | None = None,
) -> Path | None:
    """Resolve the git project root for fork registry binding.

    - When *workspace_dir* is provided without an explicit *agent_id*, only
      that path is considered (no implicit active-agent fallback).
    - When *agent_id* is provided, priority is:
      ``coding_mode.project_dir`` → agent ``workspace_dir`` → *workspace_dir*.
    - When *workspace_dir* is omitted, fall back to the active agent config.

    Returns None when no git repository is found.
    """
    candidates: list[Path] = []
    aid = agent_id
    # Implicit active-agent lookup only when no explicit workspace was given.
    # An explicit workspace must not be rebound to an unrelated agent project.
    if aid is None and workspace_dir is None:
        try:
            from ..app.agent_context import get_current_agent_id

            aid = get_current_agent_id() or None
        except Exception:  # noqa: BLE001
            aid = None
    if aid is not None:
        try:
            from ..config.config import load_agent_config

            cfg = load_agent_config(aid)
            cm = getattr(cfg, "coding_mode", None)
            if cm and getattr(cm, "enabled", False) and cm.project_dir:
                candidates.append(
                    Path(cm.project_dir).expanduser().resolve(),
                )
            if getattr(cfg, "workspace_dir", None):
                candidates.append(
                    Path(cfg.workspace_dir).expanduser().resolve(),
                )
        except Exception:  # noqa: BLE001
            logger.debug(
                "resolve_git_project_dir: config load failed for %s",
                aid,
                exc_info=True,
            )
    if workspace_dir is not None:
        try:
            candidates.append(Path(workspace_dir).expanduser().resolve())
        except OSError:
            pass
    seen: set[Path] = set()
    for cand in candidates:
        if cand in seen:
            continue
        seen.add(cand)
        # Require a real repository (.git directory). Linked worktrees use a
        # ``.git`` *file* and must not be treated as the project root.
        git_meta = cand / ".git"
        if cand.is_dir() and git_meta.is_dir():
            return cand
    return None


def _matching_agent_id_for_workspace(
    workspace_dir: Path,
) -> str | None:
    """Return active agent_id only when it owns *workspace_dir*."""
    try:
        from ..app.agent_context import get_current_agent_id
        from ..config.config import load_agent_config

        aid = get_current_agent_id() or None
        if not aid:
            return None
        cfg = load_agent_config(aid)
        raw = getattr(cfg, "workspace_dir", None)
        if not raw:
            return None
        if Path(raw).expanduser().resolve() == workspace_dir:
            return aid
    except Exception:  # noqa: BLE001
        return None
    return None


def bind_integration_project_for_workspace(
    workspace_dir: str | Path | None,
    *,
    agent_id: str | None = None,
) -> Path | None:
    """Bind workspace → git project pointer (fork-API rules) and return it."""
    aid = agent_id
    if aid is None and workspace_dir is not None:
        try:
            ws = Path(workspace_dir).expanduser().resolve()
        except OSError:
            ws = None
        if ws is not None:
            # Dual-root: only use active agent when it owns this workspace.
            aid = _matching_agent_id_for_workspace(ws)
    project = resolve_git_project_dir(workspace_dir, agent_id=aid)
    if project is not None and workspace_dir is not None:
        bind_workspace_integration_project(workspace_dir, project)
    return project


def resolve_integration_project_dir(
    workspace_dir: str | Path | None,
) -> Path | None:
    """Resolve the project root gates should use for fork verification.

    Prefer the workspace integration pointer; otherwise fall back to a
    resolvable git project root. Returns ``None`` when neither exists
    (e.g. non-git workspace). Callers such as ``forks_integrated`` treat
    ``None`` as "no registry forks possible" rather than as a hard block.
    """
    if workspace_dir is None:
        return None
    try:
        ws = Path(workspace_dir).expanduser().resolve()
    except OSError:
        return None
    pointer = ws / INTEGRATION_PROJECT_REL
    if pointer.is_file():
        try:
            raw = pointer.read_text(encoding="utf-8").strip()
            if raw:
                proj = Path(raw).expanduser().resolve()
                if proj.is_dir() and (proj / ".git").is_dir():
                    return proj
                # Pointer to a non-repo / missing path is not usable.
                logger.warning(
                    "Ignoring invalid fork integration project pointer: %s",
                    raw,
                )
        except OSError:
            logger.warning(
                "Failed to read fork integration project pointer %s",
                pointer,
                exc_info=True,
            )
    return resolve_git_project_dir(ws)


def _read_active_scope(workspace_dir: Path) -> str:
    path = workspace_dir / ACTIVE_SCOPE_REL
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_active_scope(workspace_dir: Path, scope_id: str) -> None:
    path = workspace_dir / ACTIVE_SCOPE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(scope_id + "\n", encoding="utf-8")


def begin_fork_scope(workspace_dir: str | Path | None) -> str:
    """Start a new fork scope for a workflow run; supersede prior open forks.

    Call from OMP mode activation so leftover pending/failed entries from
    earlier runs cannot block a fresh ``/ultrawork`` / ``/autopilot`` /
    ``/team``.
    """
    if workspace_dir is None:
        return ""
    try:
        ws = Path(workspace_dir).expanduser().resolve()
    except OSError:
        return ""
    # Bind coding-project pointer before supersede/prune so we clear the
    # same registry the fork API will write to.
    bind_integration_project_for_workspace(ws)
    scope_id = uuid.uuid4().hex[:12]
    _write_active_scope(ws, scope_id)
    project = resolve_integration_project_dir(ws)
    if project is None:
        return scope_id
    with _registry_lock(project):
        data = _read_registry_unlocked(project)
        forks = data.setdefault("forks", {})
        for meta in forks.values():
            if not isinstance(meta, dict):
                continue
            status = str(meta.get("status") or _STATUS_PENDING)
            if status in _ACTIVE_STATUSES:
                meta["status"] = _STATUS_SUPERSEDED
                meta["finalized"] = False
        # New scope: drop failed/merged/superseded leftovers from prior runs.
        _prune_statuses_unlocked(
            data,
            {
                _STATUS_FAILED,
                _STATUS_MERGED,
                _STATUS_SUPERSEDED,
            },
        )
        _write_registry_unlocked(project, data)
    return scope_id


def get_active_fork_scope(workspace_dir: str | Path | None) -> str:
    """Return the workspace's active fork scope id (may be empty)."""
    if workspace_dir is None:
        return ""
    try:
        ws = Path(workspace_dir).expanduser().resolve()
    except OSError:
        return ""
    return _read_active_scope(ws)


def _read_registry_unlocked(project_dir: Path) -> dict[str, Any]:
    path = _registry_path_for_project(project_dir)
    if not path.is_file():
        return {"forks": {}, "by_task": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Failed to read fork registry %s", path, exc_info=True)
        return {"forks": {}, "by_task": {}}
    if not isinstance(data, dict):
        return {"forks": {}, "by_task": {}}
    if not isinstance(data.get("forks"), dict):
        data["forks"] = {}
    if not isinstance(data.get("by_task"), dict):
        data["by_task"] = {}
    return data


def _write_registry_unlocked(project_dir: Path, data: dict[str, Any]) -> None:
    path = _registry_path_for_project(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _prune_statuses_unlocked(
    data: dict[str, Any],
    statuses: set[str],
) -> None:
    """Drop registry entries whose status is in *statuses*."""
    forks = data.get("forks") or {}
    if not isinstance(forks, dict):
        return
    keep: dict[str, Any] = {}
    for branch, meta in forks.items():
        if not isinstance(meta, dict):
            continue
        status = str(meta.get("status") or _STATUS_PENDING)
        if status in statuses:
            continue
        keep[branch] = meta
    data["forks"] = keep
    by_task = data.get("by_task") or {}
    if isinstance(by_task, dict):
        live_branches = set(keep)
        data["by_task"] = {
            tid: info
            for tid, info in by_task.items()
            if isinstance(info, dict)
            and str(info.get("branch") or "") in live_branches
        }


def _prune_terminal_unlocked(data: dict[str, Any]) -> None:
    """Drop superseded/merged entries (keep failed until next scope)."""
    _prune_statuses_unlocked(
        data,
        {_STATUS_MERGED, _STATUS_SUPERSEDED},
    )


def _git_stdout(args: list[str], cwd: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip()


def _ensure_git_identity(wt: Path) -> None:
    """Set local user.name/email when missing so auto-commit can succeed.

    Disabled when ``QWENPAW_FORK_AUTO_GIT_IDENTITY=0``. Prefers existing
    repo/global git config and does not overwrite a configured identity.
    """
    if os.environ.get("QWENPAW_FORK_AUTO_GIT_IDENTITY", "1") == "0":
        return
    for key, value in (
        ("user.email", "qwenpaw-fork@localhost"),
        ("user.name", "QwenPaw Fork"),
    ):
        current = _git_stdout(["config", "--get", key], wt)
        if not current:
            subprocess.run(
                ["git", "config", "--local", key, value],
                cwd=str(wt),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )


def _fallback_agent_workspace_dir(
    *,
    agent_id: str | None = None,
) -> Path | None:
    """Load ``workspace_dir`` from agent config when context is unset."""
    aid = agent_id
    if not aid:
        try:
            from ..app.agent_context import get_current_agent_id

            aid = get_current_agent_id() or None
        except Exception:  # noqa: BLE001
            aid = None
    if not aid:
        return None
    try:
        from ..config.config import load_agent_config

        cfg = load_agent_config(aid)
        raw = getattr(cfg, "workspace_dir", None)
        if not raw:
            return None
        return Path(raw).expanduser().resolve()
    except Exception:  # noqa: BLE001
        logger.debug(
            "fallback agent workspace_dir failed for %s",
            aid,
            exc_info=True,
        )
        return None


def register_fork(
    worktree_path: str,
    branch: str,
    *,
    session_id: str = "",
    workspace_dir: str | Path | None = None,
    scope_id: str | None = None,
) -> bool:
    """Record a newly created fork for later merge verification.

    Returns ``True`` only when the fork is recorded and the agent
    workspace has an integration pointer to the coding-project registry.
    Callers must abort spawn when this returns ``False``.

    When *workspace_dir* is omitted, falls back to the current agent's
    configured ``workspace_dir``.
    """
    wt = Path(worktree_path).expanduser().resolve()
    if not wt.is_dir() or not branch:
        return False
    if workspace_dir is None:
        workspace_dir = _fallback_agent_workspace_dir()
    if workspace_dir is None:
        logger.error(
            "register_fork refused: workspace_dir is required to bind "
            "the integration project pointer (branch=%s worktree=%s)",
            branch,
            wt,
        )
        return False
    project_dir = project_dir_from_worktree(wt)
    bind_workspace_integration_project(workspace_dir, project_dir)
    try:
        ws = Path(workspace_dir).expanduser().resolve()
        pointer = ws / INTEGRATION_PROJECT_REL
        if not pointer.is_file():
            logger.error(
                "register_fork refused: failed to write integration "
                "project pointer at %s (branch=%s)",
                pointer,
                branch,
            )
            return False
    except OSError:
        logger.error(
            "register_fork refused: cannot verify integration pointer "
            "(branch=%s workspace=%s)",
            branch,
            workspace_dir,
            exc_info=True,
        )
        return False
    if not scope_id:
        scope_id = get_active_fork_scope(workspace_dir)
    base = _git_stdout(["rev-parse", "HEAD"], wt) or ""
    with _registry_lock(project_dir):
        data = _read_registry_unlocked(project_dir)
        forks = data.setdefault("forks", {})
        # Drop leftovers from prior scopes so they cannot linger as active.
        if scope_id:
            for meta in forks.values():
                if not isinstance(meta, dict):
                    continue
                status = str(meta.get("status") or _STATUS_PENDING)
                if (
                    status in _ACTIVE_STATUSES
                    and str(meta.get("scope_id") or "") != scope_id
                ):
                    meta["status"] = _STATUS_SUPERSEDED
                    meta["finalized"] = False
        _prune_terminal_unlocked(data)
        forks = data.setdefault("forks", {})
        forks[branch] = {
            "worktree": str(wt),
            "branch": branch,
            "project_dir": str(project_dir),
            "base": base,
            "head": base,
            "session_id": session_id,
            "task_id": "",
            "scope_id": scope_id or "",
            "status": _STATUS_PENDING,
            "finalized": False,
            "no_changes": False,
            "created_at": time.time(),
        }
        _write_registry_unlocked(project_dir, data)
    return True


def bind_fork_task(
    worktree_path: str,
    branch: str,
    task_id: str,
) -> bool:
    """Associate a background ``task_id`` with an already-registered fork.

    Refuses to create ghost registry entries when ``register_fork`` did
    not run successfully. Returns ``True`` when the binding was written.
    """
    if not task_id or not branch:
        return False
    wt = Path(worktree_path).expanduser().resolve()
    if not wt.is_dir():
        return False
    project_dir = project_dir_from_worktree(wt)
    with _registry_lock(project_dir):
        data = _read_registry_unlocked(project_dir)
        forks = data.setdefault("forks", {})
        meta = forks.get(branch)
        if not isinstance(meta, dict):
            logger.error(
                "bind_fork_task refused: no registered fork for branch=%s "
                "(worktree=%s); refusing to create a ghost registry entry",
                branch,
                wt,
            )
            return False
        meta["task_id"] = task_id
        meta["worktree"] = str(wt)
        forks[branch] = meta
        by_task = data.setdefault("by_task", {})
        if isinstance(by_task, dict):
            by_task[task_id] = {
                "branch": branch,
                "worktree": str(wt),
                "project_dir": str(project_dir),
            }
        _write_registry_unlocked(project_dir, data)
    return True


def _mark_fork_failed_unlocked(
    project_dir: Path,
    branch: str,
    *,
    reason: str = "",
) -> None:
    """Mark failed under an already-held finalize + registry lock."""
    data = _read_registry_unlocked(project_dir)
    forks = data.setdefault("forks", {})
    meta = forks.get(branch)
    if not isinstance(meta, dict):
        # Do not resurrect pruned entries as failed ghosts.
        return
    status = str(meta.get("status") or _STATUS_PENDING)
    if status in (
        _STATUS_SUPERSEDED,
        _STATUS_MERGED,
        _STATUS_FINALIZED,
    ):
        return
    meta["status"] = _STATUS_FAILED
    meta["finalized"] = False
    if reason:
        meta["fail_reason"] = reason[:500]
    forks[branch] = meta
    _write_registry_unlocked(project_dir, data)


def mark_fork_failed(
    worktree_path: str,
    branch: str,
    *,
    reason: str = "",
) -> None:
    """Mark a fork as failed (kept until the next ``begin_fork_scope``).

    Blocks on the same per-branch finalize lock as ``finalize_fork_worktree``
    so a watchdog waits for an in-flight finalize and cannot overwrite a
    successful ``finalized`` result. Also refuses ``merged`` / ``superseded``.

    A leftover ``finalizing`` row is crash-recovered first: clean worktree
    becomes ``finalized`` (not failed); dirty/unreadable may then fail.
    """
    # pylint: disable=too-many-return-statements
    if not worktree_path or not branch:
        return
    try:
        wt = Path(worktree_path).expanduser().resolve()
        project_dir = project_dir_from_worktree(wt)
    except OSError:
        return
    with _fork_finalize_lock(project_dir, branch, blocking=True) as acquired:
        if not acquired:
            return
        expected_scope = ""
        with _registry_lock(project_dir):
            status, meta = _fork_status_unlocked(project_dir, branch)
            if status in (
                _STATUS_SUPERSEDED,
                _STATUS_MERGED,
                _STATUS_FINALIZED,
            ):
                return
            if status == _STATUS_FINALIZING and meta is not None:
                expected_scope = str(meta.get("scope_id") or "")
            else:
                _mark_fork_failed_unlocked(
                    project_dir,
                    branch,
                    reason=reason,
                )
                return

        # Crash recovery under per-branch lock; Git outside registry lock.
        outcome, head = _inspect_worktree_recovery(wt)
        recovered = _apply_crash_recovery(
            project_dir,
            branch,
            wt,
            expected_scope=expected_scope,
            outcome=outcome,
            head=head,
        )
        if recovered is True:
            # Clean committed worktree healed to finalized.
            return
        if recovered is False:
            # Unreadable already marked failed, or row no longer finalizing.
            return
        # Dirty leftover — caller asked to fail; record failed now.
        with _registry_lock(project_dir):
            _mark_fork_failed_unlocked(
                project_dir,
                branch,
                reason=reason or "dirty worktree after crashed finalize",
            )


def mark_fork_failed_for_task(
    task_id: str,
    *,
    workspace_dir: str | Path | None = None,
    reason: str = "",
) -> None:
    """Mark the fork bound to *task_id* as failed, if any."""
    if not task_id:
        return
    project = resolve_integration_project_dir(workspace_dir)
    if project is None:
        return
    with _registry_lock(project):
        data = _read_registry_unlocked(project)
        by_task = data.get("by_task") or {}
        info = by_task.get(task_id) if isinstance(by_task, dict) else None
        if not isinstance(info, dict):
            return
        branch = str(info.get("branch") or "")
        wt = str(info.get("worktree") or "")
    if branch and wt:
        mark_fork_failed(wt, branch, reason=reason)


def update_fork_head(worktree_path: str, branch: str) -> str | None:
    """Refresh registry head SHA for *branch*; return the new HEAD."""
    wt = Path(worktree_path).expanduser().resolve()
    if not wt.is_dir() or not branch:
        return None
    head = _git_stdout(["rev-parse", "HEAD"], wt)
    if not head:
        return None
    project_dir = project_dir_from_worktree(wt)
    with _registry_lock(project_dir):
        data = _read_registry_unlocked(project_dir)
        forks = data.setdefault("forks", {})
        meta = forks.get(branch)
        if not isinstance(meta, dict):
            return head
        status = str(meta.get("status") or _STATUS_PENDING)
        if status not in _ACTIVE_STATUSES:
            return head
        meta["head"] = head
        meta["worktree"] = str(wt)
        forks[branch] = meta
        _write_registry_unlocked(project_dir, data)
    return head


def commit_dirty_worktree(
    worktree_path: str,
    message: str = "fork worker changes",
) -> bool:
    """Stage and commit dirty files in *worktree_path*."""
    # pylint: disable=too-many-return-statements
    wt = Path(worktree_path).expanduser().resolve()
    if not wt.is_dir():
        return False
    status = _git_stdout(["status", "--porcelain"], wt)
    if status is None:
        return False
    if not status:
        return True
    _ensure_git_identity(wt)
    add = subprocess.run(
        ["git", "add", "-A"],
        cwd=str(wt),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if add.returncode != 0:
        logger.warning(
            "git add failed in fork worktree %s: %s",
            wt,
            (add.stderr or "").strip(),
        )
        return False
    commit = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=str(wt),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if commit.returncode != 0:
        if (
            "nothing to commit"
            in (commit.stdout or "").lower() + (commit.stderr or "").lower()
        ):
            return True
        logger.warning(
            "git commit failed in fork worktree %s: %s",
            wt,
            (commit.stderr or commit.stdout or "").strip(),
        )
        return False
    return True


def _fork_status_unlocked(
    project_dir: Path,
    branch: str,
) -> tuple[str | None, dict[str, Any] | None]:
    data = _read_registry_unlocked(project_dir)
    forks = data.get("forks") or {}
    meta = forks.get(branch) if isinstance(forks, dict) else None
    if not isinstance(meta, dict):
        return None, None
    return str(meta.get("status") or _STATUS_PENDING), meta


def _write_finalized_unlocked(
    project_dir: Path,
    branch: str,
    wt: Path,
    *,
    head: str,
) -> bool:
    """Mark *branch* finalized under the registry lock."""
    data = _read_registry_unlocked(project_dir)
    forks = data.setdefault("forks", {})
    meta = forks.get(branch)
    if not isinstance(meta, dict):
        return False
    status = str(meta.get("status") or _STATUS_PENDING)
    if status in (_STATUS_FINALIZED, _STATUS_MERGED):
        return True
    if status not in (_STATUS_PENDING, _STATUS_FINALIZING):
        return False
    base = str(meta.get("base") or "")
    meta["head"] = head
    meta["worktree"] = str(wt)
    meta["finalized"] = True
    meta["no_changes"] = bool(head) and head == base
    meta["status"] = _STATUS_FINALIZED
    forks[branch] = meta
    _write_registry_unlocked(project_dir, data)
    return True


def _inspect_worktree_recovery(wt: Path) -> tuple[str, str]:
    """Inspect worktree for crash recovery (no registry lock held).

    Returns ``(outcome, head)`` where *outcome* is one of:
    ``unreadable``, ``dirty``, ``clean``.
    """
    porcelain = _git_stdout(["status", "--porcelain"], wt)
    if porcelain is None:
        return "unreadable", ""
    if porcelain:
        return "dirty", ""
    head = _git_stdout(["rev-parse", "HEAD"], wt) or ""
    return "clean", head


def _begin_finalize_unlocked(
    project_dir: Path,
    branch: str,
    wt: Path,
) -> tuple[str, str]:
    """Prepare finalize under registry lock.

    Returns ``(action, expected_scope)`` where *action* is one of:
    ``done`` (already finalized), ``skip``, ``recover``, ``run``.
    """
    status, meta = _fork_status_unlocked(project_dir, branch)
    if status in (_STATUS_FINALIZED, _STATUS_MERGED):
        return "done", ""
    if meta is None or status not in (_STATUS_PENDING, _STATUS_FINALIZING):
        return "skip", ""
    expected_scope = str(meta.get("scope_id") or "")
    if status == _STATUS_FINALIZING:
        return "recover", expected_scope
    data = _read_registry_unlocked(project_dir)
    forks = data.setdefault("forks", {})
    row = forks.get(branch)
    if not isinstance(row, dict):
        return "skip", expected_scope
    row["status"] = _STATUS_FINALIZING
    row["worktree"] = str(wt)
    forks[branch] = row
    _write_registry_unlocked(project_dir, data)
    return "run", expected_scope


def _apply_crash_recovery(
    project_dir: Path,
    branch: str,
    wt: Path,
    *,
    expected_scope: str,
    outcome: str,
    head: str,
) -> bool | None:
    """Write crash-recovery result under registry lock.

    Returns ``True``/``False`` when finished, or ``None`` to re-run commit
    for a dirty worktree.
    """
    with _registry_lock(project_dir):
        status, meta = _fork_status_unlocked(project_dir, branch)
        if status in (_STATUS_FINALIZED, _STATUS_MERGED):
            return True
        if meta is None or status != _STATUS_FINALIZING:
            return False
        if str(meta.get("scope_id") or "") != expected_scope:
            return False
        if outcome == "unreadable":
            _mark_fork_failed_unlocked(
                project_dir,
                branch,
                reason="git unreadable after crashed finalize",
            )
            return False
        if outcome == "clean":
            return _write_finalized_unlocked(
                project_dir,
                branch,
                wt,
                head=head,
            )
        return None


def _finish_finalize_unlocked(
    project_dir: Path,
    branch: str,
    wt: Path,
    *,
    expected_scope: str,
    ok: bool,
    head: str,
) -> bool:
    """Persist finalize result under registry lock."""
    status, meta = _fork_status_unlocked(project_dir, branch)
    if status in (_STATUS_FINALIZED, _STATUS_MERGED):
        return True
    if meta is None or status not in (
        _STATUS_PENDING,
        _STATUS_FINALIZING,
    ):
        return False
    if str(meta.get("scope_id") or "") != expected_scope:
        return False
    if not ok:
        data = _read_registry_unlocked(project_dir)
        forks = data.setdefault("forks", {})
        row = forks.get(branch)
        if isinstance(row, dict):
            row["status"] = _STATUS_PENDING
            forks[branch] = row
            _write_registry_unlocked(project_dir, data)
        return False
    return _write_finalized_unlocked(
        project_dir,
        branch,
        wt,
        head=head,
    )


def finalize_fork_worktree(
    worktree_path: str,
    branch: str,
    *,
    message: str | None = None,
) -> bool:
    """Commit dirty changes (if any) and mark the fork finalized.

    Refuses to recreate registry entries that were pruned or superseded —
    late background completion after a new scope must not resurrect ghosts.

    Concurrent callers serialize on a per-branch OS lock held across
    registry updates and ``git status``/``add``/``commit``. A second caller
    blocks, then returns success if the fork is already finalized. After a
    crash, a leftover ``finalizing`` row is healed from the worktree state.
    Recovery Git runs under the per-branch lock but **outside** the project
    registry lock so other forks are not stalled.
    """
    # pylint: disable=too-many-return-statements
    if not worktree_path or not branch:
        return False
    wt = Path(worktree_path).expanduser().resolve()
    if not wt.is_dir():
        return False
    project_dir = project_dir_from_worktree(wt)

    with _fork_finalize_lock(project_dir, branch, blocking=True) as acquired:
        if not acquired:
            return False

        with _registry_lock(project_dir):
            action, expected_scope = _begin_finalize_unlocked(
                project_dir,
                branch,
                wt,
            )
        if action == "done":
            return True
        if action == "skip":
            logger.info(
                "Skipping finalize for unknown/inactive fork %s",
                branch,
            )
            return False
        if action == "recover":
            # Git I/O under per-branch lock only — do not hold registry lock.
            outcome, recovered_head = _inspect_worktree_recovery(wt)
            recovered = _apply_crash_recovery(
                project_dir,
                branch,
                wt,
                expected_scope=expected_scope,
                outcome=outcome,
                head=recovered_head,
            )
            if recovered is not None:
                return recovered

        ok = commit_dirty_worktree(
            str(wt),
            message or f"fork worker {branch}",
        )
        head = _git_stdout(["rev-parse", "HEAD"], wt) or ""
        with _registry_lock(project_dir):
            return _finish_finalize_unlocked(
                project_dir,
                branch,
                wt,
                expected_scope=expected_scope,
                ok=ok,
                head=head,
            )


def finalize_fork_worktree_or_fail(
    worktree_path: str,
    branch: str,
    *,
    message: str | None = None,
) -> bool:
    """Finalize a fork; on failure mark it ``failed`` so gates stay blocked.

    Idempotent when another path already finalized successfully. Uses the
    same per-branch lock as finalize, so a peer cannot be marked failed
    until its in-flight finalize finishes.
    """
    ok = finalize_fork_worktree(
        worktree_path,
        branch,
        message=message,
    )
    if ok:
        return True
    mark_fork_failed(
        worktree_path,
        branch,
        reason="finalize_fork_worktree failed",
    )
    # Peer may have finalized while we failed; treat that as success.
    try:
        wt = Path(worktree_path).expanduser().resolve()
        project_dir = project_dir_from_worktree(wt)
    except OSError:
        return False
    with _registry_lock(project_dir):
        status, _meta = _fork_status_unlocked(project_dir, branch)
    return status in (_STATUS_FINALIZED, _STATUS_MERGED)


def finalize_fork_for_task(
    task_id: str,
    *,
    project_dir: str | Path | None = None,
    workspace_dir: str | Path | None = None,
) -> bool:
    """Finalize the fork bound to a background *task_id*, if any."""
    if not task_id:
        return False
    roots: list[Path] = []
    if project_dir is not None:
        roots.append(Path(project_dir).expanduser().resolve())
    resolved = resolve_integration_project_dir(workspace_dir)
    if resolved is not None:
        roots.append(resolved)
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        with _registry_lock(root):
            data = _read_registry_unlocked(root)
            by_task = data.get("by_task") or {}
            info = by_task.get(task_id) if isinstance(by_task, dict) else None
        if not isinstance(info, dict):
            continue
        branch = str(info.get("branch") or "")
        wt = str(info.get("worktree") or "")
        if branch and wt:
            return finalize_fork_worktree_or_fail(wt, branch)
    return False


def _is_ancestor(project_dir: Path, tip: str) -> bool:
    check = subprocess.run(
        ["git", "merge-base", "--is-ancestor", tip, "HEAD"],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return check.returncode == 0


def _collect_scope_active_forks(
    forks: dict[str, Any],
    scope_id: str | None,
) -> tuple[bool, list[tuple[str, dict[str, Any]]]]:
    """Return ``(has_failed, active)`` for forks in *scope_id*.

    ``has_failed`` is True when any in-scope entry is ``failed`` or a
    non-dict meta is present (fail closed).
    """
    active: list[tuple[str, dict[str, Any]]] = []
    for branch, meta in forks.items():
        if not isinstance(meta, dict):
            return True, []
        if scope_id and str(meta.get("scope_id") or "") != scope_id:
            continue
        status = str(meta.get("status") or _STATUS_PENDING)
        if status == _STATUS_FAILED:
            return True, []
        if status not in _ACTIVE_STATUSES:
            continue
        active.append((branch, dict(meta)))
    return False, active


def forks_merged_into_head(
    project_dir: Path | str | None,
    *,
    scope_id: str | None = None,
) -> bool:
    """Return True when every fork in scope is integrated into HEAD.

    - Any ``failed`` entry in the current scope blocks completion (failed
      workers must not disappear into an empty-active pass).
    - ``merged`` / ``superseded`` are ignored.
    - Each ``pending``/``finalized`` fork must be finalized with tip in HEAD.
    - ``tip == base`` is allowed only when ``no_changes`` was set at finalize.
    - Empty active **and** no failed in scope → True (no forks, or all merged).

    Re-validates the registry under lock after Git checks so a concurrent
    ``register_fork`` cannot fail-open the merge gate.
    """
    # pylint: disable=too-many-return-statements,too-many-branches
    if project_dir is None:
        return False
    root = Path(project_dir).expanduser().resolve()
    with _registry_lock(root):
        data = _read_registry_unlocked(root)
        forks = dict(data.get("forks") or {})
        has_failed, active = _collect_scope_active_forks(forks, scope_id)
        if has_failed:
            return False
        # Empty active under lock — no TOCTOU window before returning True.
        if not active:
            return True
        verified_branches = {branch for branch, _meta in active}

    newly_merged: list[str] = []
    for branch, meta in active:
        if meta.get("finalized") is not True:
            return False
        wt_raw = meta.get("worktree")
        wt: Path | None = None
        if isinstance(wt_raw, str) and wt_raw:
            wt = Path(wt_raw)
            if wt.is_dir():
                porcelain = _git_stdout(["status", "--porcelain"], wt)
                if porcelain:
                    return False
        tip = _git_stdout(["rev-parse", branch], root)
        if tip is None and wt is not None and wt.is_dir():
            tip = _git_stdout(["rev-parse", "HEAD"], wt)
        if not tip:
            return False
        base = str(meta.get("base") or "")
        no_changes = meta.get("no_changes") is True
        if tip == base and not no_changes:
            return False
        if not _is_ancestor(root, tip):
            return False
        newly_merged.append(branch)

    with _registry_lock(root):
        data = _read_registry_unlocked(root)
        forks = data.setdefault("forks", {})
        has_failed, active_now = _collect_scope_active_forks(forks, scope_id)
        if has_failed:
            return False
        active_now_branches = {branch for branch, _meta in active_now}
        # A fork registered during Git checks must keep the gate closed.
        if active_now_branches - verified_branches:
            return False
        for branch in newly_merged:
            meta = forks.get(branch)
            if not isinstance(meta, dict):
                return False
            if scope_id and str(meta.get("scope_id") or "") != scope_id:
                return False
            status = str(meta.get("status") or _STATUS_PENDING)
            if status == _STATUS_FAILED:
                return False
            if status == _STATUS_MERGED:
                continue
            if (
                status != _STATUS_FINALIZED
                or meta.get("finalized") is not True
            ):
                return False
            meta["status"] = _STATUS_MERGED
            forks[branch] = meta
        # Keep failed entries so a mixed success/fail scope stays blocked.
        _prune_statuses_unlocked(data, {_STATUS_MERGED, _STATUS_SUPERSEDED})
        _write_registry_unlocked(root, data)
    return True


def has_registered_forks(
    project_dir: Path | str | None,
    *,
    scope_id: str | None = None,
) -> bool:
    """Return True when active (pending/finalized) forks exist."""
    if project_dir is None:
        return False
    root = Path(project_dir).expanduser().resolve()
    with _registry_lock(root):
        data = _read_registry_unlocked(root)
        forks = data.get("forks") or {}
    for meta in forks.values():
        if not isinstance(meta, dict):
            continue
        status = str(meta.get("status") or _STATUS_PENDING)
        if status not in _ACTIVE_STATUSES:
            continue
        if scope_id and str(meta.get("scope_id") or "") != scope_id:
            continue
        return True
    return False


__all__ = [
    "WORKTREE_REL",
    "REGISTRY_REL",
    "INTEGRATION_PROJECT_REL",
    "ACTIVE_SCOPE_REL",
    "FORK_WORKER_COMMIT_PROTOCOL",
    "resolve_allowed_fork_project_dir",
    "project_dir_from_worktree",
    "bind_workspace_integration_project",
    "resolve_git_project_dir",
    "bind_integration_project_for_workspace",
    "resolve_integration_project_dir",
    "begin_fork_scope",
    "get_active_fork_scope",
    "register_fork",
    "bind_fork_task",
    "mark_fork_failed",
    "mark_fork_failed_for_task",
    "update_fork_head",
    "commit_dirty_worktree",
    "finalize_fork_worktree",
    "finalize_fork_worktree_or_fail",
    "finalize_fork_for_task",
    "forks_merged_into_head",
    "has_registered_forks",
]
