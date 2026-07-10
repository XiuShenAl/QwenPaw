# -*- coding: utf-8 -*-
"""Reusable safety check primitives.

Called by ACP permissions, ToolGuard guardians, and other security layers
to eliminate duplicated safety rule definitions.
"""
from __future__ import annotations

import re
from pathlib import Path

BLOCKED_COMMAND_PATTERNS: tuple[str, ...] = (
    # Catastrophic recursive deletion targets.
    (
        r"\brm\s+(?:-[a-z]*r[a-z]*|--recursive)(?:\s+(?:-\S+|--\S+))*\s+"
        r"(?:/|/(?:home|users|etc|var|usr|bin|sbin|lib|opt|private|"
        r"system|windows)\b|~(?:/|$)|\*)"
    ),
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


def is_path_outside_boundary(path: str, cwd: str) -> bool:
    """Return ``True`` if *path* resolves outside *cwd*.

    Uses :py:meth:`Path.is_relative_to` rather than string-prefix
    matching, which is vulnerable to sibling-directory bypasses
    (``/foo/bar_evil/...`` would prefix-match ``/foo/bar``).
    """
    cwd_resolved = Path(cwd).resolve()
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
