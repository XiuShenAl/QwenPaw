# -*- coding: utf-8 -*-
"""Reusable safety check primitives.

Called by ACP permissions, ToolGuard guardians, and other security layers
to eliminate duplicated safety rule definitions.
"""
from __future__ import annotations

import re
from pathlib import Path

# Token boundary after a catastrophic path (whitespace, shell metachar, or
# closing quote).
_PATH_END = r"(?=[\s|;|&)\"']|$)"

# After a recursive ``rm``, these targets are treated as catastrophic.
#
# Design notes:
# - Bare ``/`` / ``/*`` must be complete arguments (so ``/tmp`` is safe).
# - ``/home/...`` and ``/Users/...`` stay blocked (user-home wipes).
# - ``/var/...`` and ``/private/...`` stay blocked, except macOS temp
#   trees ``/var/folders`` and ``/private/var/folders`` used by pytest
#   and typical local workspaces.
# - Critical system prefixes (``/etc``, ``/usr``, …) stay blocked.
# - Optional quotes around the target token are accepted.
# - ``$HOME`` / ``${HOME}`` / ``%USERPROFILE%`` are treated like ``~``.
_RM_CATASTROPHIC_TARGET = (
    r"(?:"
    r"['\"]?"
    r"(?:"
    # / or /*
    r"/(?:" + _PATH_END + r"|\*)"
    # user homes and all subpaths
    r"|/(?:home|users)(?:/|" + _PATH_END + r")"
    # critical system trees
    r"|/(?:etc|usr|bin|sbin|lib|opt|system|windows)(?:/|" + _PATH_END + r")"
    # /var/* except macOS /var/folders (temp / workspace roots)
    r"|/var(?!/folders\b)(?:/|" + _PATH_END + r")"
    # /private/* except /private/var/folders
    r"|/private(?!/var/folders\b)(?:/|" + _PATH_END + r")"
    # ~/... or bare ~
    r"|~(?:/|" + _PATH_END + r")"
    # shell / Windows home-directory expansions
    r"|\$(?:\{HOME\}|HOME)(?:/|" + _PATH_END + r")"
    r"|%USERPROFILE%(?:\\|/|" + _PATH_END + r")"
    r"|\*"
    r")"
    r"['\"]?"
    r")"
)

# Recursive flag in any position among short/long options.
_RM_RECURSIVE_LOOKAHEAD = r"(?=[^\n]*(?:-[a-z]*r[a-z]*|--recursive|-Recurse))"

# Drive-root token: optional quotes, ``C:`` / ``C:\`` / ``C:\*``.
_WIN_DRIVE_ROOT = r"['\"]?[A-Za-z]:\\?(?:\*|['\"]|" + _PATH_END + r")"

BLOCKED_COMMAND_PATTERNS: tuple[str, ...] = (
    # POSIX / PowerShell-unix-style: flags may appear in any order.
    # Covers: rm -rf /, rm -f -r /, rm --force --recursive /, …
    (
        r"\brm\b"
        + _RM_RECURSIVE_LOOKAHEAD
        + r"(?:\s+(?:-\S+|--\S+))+\s+"
        + _RM_CATASTROPHIC_TARGET
    ),
    # Windows PowerShell Remove-Item family (incl. rm/ri aliases)
    # targeting a drive root.  ``rm -Recurse`` is required for the rm
    # alias so Unix ``rm -rf /`` is not double-matched here.
    (
        r"\b(?:Remove-Item|ri)\b(?=[^\n]*-(?:Recurse|r)\b)"
        + r"[^\n]*"
        + _WIN_DRIVE_ROOT
    ),
    (r"\brm\b(?=[^\n]*-Recurse\b)" + r"[^\n]*" + _WIN_DRIVE_ROOT),
    # Windows cmd: recursive quiet delete of a drive root (optional *).
    r"\bdel\s+(?:/[a-zA-Z]+\s+)*" + _WIN_DRIVE_ROOT,
    # Windows cmd: recursive remove of a drive root only.
    r"\b(?:rd|rmdir)\s+(?:/[a-zA-Z]+\s+)*" + _WIN_DRIVE_ROOT,
    # Windows format of a drive letter.
    r"\bformat\s+[A-Za-z]:",
    # Filesystem and raw block-device operations.
    r"\bmkfs(?:\.[a-z0-9_]+)?\b",
    r"\bmke2fs\b",
    r"\bdd\s+.*\b(?:if|of)=/dev/",
    # System shutdown/reboot.
    r"\b(?:shutdown|reboot|halt|poweroff)\b",
    # Classic fork bomb.
    r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
)

_COMPILED = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern in BLOCKED_COMMAND_PATTERNS
)


def is_command_destructive(command: str) -> bool:
    """Check whether *command* matches a known dangerous pattern."""
    return any(pattern.search(command) for pattern in _COMPILED)


def is_path_outside_boundary(
    path: str | Path,
    cwd: str | Path,
    *,
    cwd_is_resolved: bool = False,
    path_is_resolved: bool = False,
) -> bool:
    """Return ``True`` if *path* resolves outside *cwd*.

    Uses :py:meth:`pathlib.PurePath.relative_to` rather than
    string-prefix matching, which is vulnerable to sibling-directory
    bypasses (``/foo/bar_evil/...`` would prefix-match ``/foo/bar``).

    Pass ``cwd_is_resolved=True`` / ``path_is_resolved=True`` when the
    caller has already ``resolve()``-d the value, to avoid extra
    filesystem syscalls on the hot ToolGuard path.

    **Cross-platform note:** On Windows, paths on different drive
    letters (e.g. ``C:\\workspace`` vs ``D:\\evil``) are correctly
    rejected because ``relative_to()`` raises ``ValueError`` when
    the drives differ.
    """
    if cwd_is_resolved:
        cwd_resolved = Path(cwd)
    else:
        cwd_resolved = Path(cwd).resolve()

    if path_is_resolved:
        resolved = Path(path)
    else:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = cwd_resolved / candidate
        try:
            resolved = candidate.resolve()
        except OSError:
            return True

    try:
        resolved.relative_to(cwd_resolved)
        return False
    except ValueError:
        return True
