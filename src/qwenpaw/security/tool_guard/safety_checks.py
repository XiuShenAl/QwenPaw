# -*- coding: utf-8 -*-
"""Reusable safety check primitives.

Called by ACP permissions, ToolGuard guardians, and other security layers
to eliminate duplicated safety rule definitions.
"""
from __future__ import annotations

import re
from pathlib import Path

# After ``rm -rf``, only these targets are treated as catastrophic.
#
# Bare ``/`` and top-level system dirs (``/home``, ``/var``, …) MUST be
# complete arguments.  Prefix matching would false-positive on
# ``rm -rf /tmp`` and on workspace absolute paths such as
# ``/home/user/proj/build`` or macOS ``/private/var/folders/...``.
# Critical non-workspace prefixes (``/etc/``, ``/usr/``, …) stay covered.
_RM_CATASTROPHIC_TARGET = (
    r"(?:"
    # / or /*
    r"/(?=[\s|;|&)]|$|\*)"
    # complete system dir only (not /home/user/...)
    r"|/(?:home|users|etc|var|usr|bin|sbin|lib|opt|private|"
    r"system|windows)(?=[\s|;|&)]|$)"
    # critical system prefixes that are not typical workspaces
    r"|/(?:etc|usr|bin|sbin|lib|opt|System|Windows)/"
    # ~/... or bare ~
    r"|~(?:/|(?=[\s|;|&)]|$))"
    r"|\*"
    r")"
)

BLOCKED_COMMAND_PATTERNS: tuple[str, ...] = (
    # POSIX catastrophic recursive deletion targets.
    (
        r"\brm\s+(?:-[a-z]*r[a-z]*|--recursive)(?:\s+(?:-\S+|--\S+))*\s+"
        + _RM_CATASTROPHIC_TARGET
    ),
    # Windows PowerShell: recursive force delete of a drive root.
    (
        r"\bRemove-Item\b(?=[^\n]*-(?:Recurse|r)\b)"
        r"[^\n]*[A-Za-z]:\\(?:\*|(?=[\s\"';|&)]|$))"
    ),
    # Windows cmd: recursive quiet delete of a drive root glob.
    r"\bdel\s+(?:/[a-zA-Z]+\s+)*[A-Za-z]:\\\*",
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
