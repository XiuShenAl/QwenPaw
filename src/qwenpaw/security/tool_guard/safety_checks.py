# -*- coding: utf-8 -*-
"""Reusable safety check primitives.

Called by ACP permissions, ToolGuard guardians, and other security layers
to eliminate duplicated safety rule definitions.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Literal

DestructiveKind = Literal["catastrophic", "system_power"]

# Token boundary after a catastrophic path (whitespace, shell metachar, or
# closing quote).
_PATH_END = r"(?=[\s|;|&)\"']|$)"

# After a recursive ``rm``, these targets are treated as catastrophic.
#
# Design notes:
# - Bare ``/`` / ``/*`` must be complete arguments (so ``/tmp`` is safe).
# - User homes and critical system trees stay blocked.
# - ``/var/...`` / ``/private/...`` stay blocked except macOS temp trees
#   ``/var/folders`` and ``/private/var/folders``.
# - Optional quotes and ``$HOME`` / ``%USERPROFILE%`` are accepted.
# - Path forms like ``/./``, ``//``, ``/tmp/..`` are handled by the
#   resolve-based check in :func:`classify_destructive_command`.
_RM_CATASTROPHIC_TARGET = (
    r"(?:"
    r"['\"]?"
    r"(?:"
    # / or /*
    r"/(?:" + _PATH_END + r"|\*)"
    # user homes / critical top-level trees (incl. /root, /boot, …)
    r"|/(?:home|users|root|boot|dev|applications|etc|usr|bin|sbin|lib|"
    r"opt|system|windows|library|volumes|proc|sys|run|srv|mnt|media)"
    r"(?:/|" + _PATH_END + r")"
    # /var/* except macOS /var/folders
    r"|/var(?!/folders\b)(?:/|" + _PATH_END + r")"
    # /private/* except /private/var/folders
    r"|/private(?!/var/folders\b)(?:/|" + _PATH_END + r")"
    r"|~(?:/|" + _PATH_END + r")"
    r"|\$(?:\{HOME\}|HOME)(?:/|" + _PATH_END + r")"
    r"|%USERPROFILE%(?:\\|/|" + _PATH_END + r")"
    r"|\*"
    r")"
    r"['\"]?"
    r")"
)

_RM_RECURSIVE_LOOKAHEAD = r"(?=[^\n]*(?:-[a-z]*r[a-z]*|--recursive|-Recurse))"

_WIN_DRIVE_ROOT = r"['\"]?[A-Za-z]:\\?(?:\*|['\"]|" + _PATH_END + r")"

# Patterns that warrant default ToolGuard auto-deny (and ACP hard-block).
_CATASTROPHIC_PATTERNS: tuple[str, ...] = (
    (
        r"\brm\b"
        + _RM_RECURSIVE_LOOKAHEAD
        + r"(?:\s+(?:-\S+|--\S+))+\s+"
        + _RM_CATASTROPHIC_TARGET
    ),
    (
        r"\b(?:Remove-Item|ri)\b(?=[^\n]*-(?:Recurse|r)\b)"
        + r"[^\n]*"
        + _WIN_DRIVE_ROOT
    ),
    (r"\brm\b(?=[^\n]*-Recurse\b)" + r"[^\n]*" + _WIN_DRIVE_ROOT),
    # Require recursive (/s) so bare ``del C:\`` / ``rd C:\`` are not hit.
    r"\bdel\b(?=[^\n]*/[sS]\b)\s+(?:/[a-zA-Z]+\s+)*" + _WIN_DRIVE_ROOT,
    (
        r"\b(?:rd|rmdir)\b(?=[^\n]*/[sS]\b)\s+(?:/[a-zA-Z]+\s+)*"
        + _WIN_DRIVE_ROOT
    ),
    r"\bformat\s+[A-Za-z]:",
    # Command-position only — avoids ``npm run mkfs`` false positives.
    r"(?:^|[\n;|&]\s*)(?:sudo\s+)?mkfs(?:\.[a-z0-9_]+)?\b",
    r"(?:^|[\n;|&]\s*)(?:sudo\s+)?mke2fs\b",
    r"(?:^|[\n;|&]\s*)(?:sudo\s+)?dd\s+.*\b(?:if|of)=/dev/",
    r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",
)

# Still hard-blocked by ACP / surfaced for approval, but NOT auto-denied
# by default (bare-word ``reboot`` must not DENY ``npm run reboot``).
_SYSTEM_POWER_PATTERNS: tuple[str, ...] = (
    r"(?:^|[\n;|&]\s*)(?:sudo\s+)?(?:shutdown|reboot|halt|poweroff)\b",
)

_CATASTROPHIC_COMPILED = tuple(
    re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _CATASTROPHIC_PATTERNS
)
_SYSTEM_POWER_COMPILED = tuple(
    re.compile(p, re.IGNORECASE | re.MULTILINE) for p in _SYSTEM_POWER_PATTERNS
)

_RE_RECURSIVE_RM = re.compile(
    r"\brm\b(?=[^\n]*(?:-[a-z]*r[a-z]*|--recursive|-Recurse))",
    re.IGNORECASE,
)

# Kept for callers/tests that iterate blocked pattern strings.
BLOCKED_COMMAND_PATTERNS: tuple[str, ...] = (
    _CATASTROPHIC_PATTERNS + _SYSTEM_POWER_PATTERNS
)

_CATASTROPHIC_TOP_LEVEL = frozenset(
    {
        "home",
        "users",
        "root",
        "boot",
        "dev",
        "applications",
        "etc",
        "usr",
        "bin",
        "sbin",
        "lib",
        "opt",
        "system",
        "windows",
        "library",
        "volumes",
        "proc",
        "sys",
        "run",
        "srv",
        "mnt",
        "media",
        "private",
        "var",
    },
)


def _is_safe_temp_tree(resolved: Path) -> bool:
    """Return True for typical temp / pytest workspace roots."""
    parts = resolved.parts
    if len(parts) >= 2 and parts[1] == "tmp":
        return True
    if len(parts) >= 3 and parts[1] == "var" and parts[2] == "tmp":
        return True
    if len(parts) >= 3 and parts[1] == "var" and parts[2] == "folders":
        return True
    if len(parts) >= 3 and parts[1] == "private" and parts[2] == "tmp":
        return True
    if (
        len(parts) >= 4
        and parts[1] == "private"
        and parts[2] == "var"
        and parts[3] == "folders"
    ):
        return True
    return False


def _is_resolved_path_catastrophic(resolved: Path) -> bool:
    """Return True when a fully resolved path is a catastrophic wipe target."""
    parts = resolved.parts
    if not parts:
        return False

    # POSIX / Windows root.
    if resolved.anchor and len(parts) == 1:
        return True
    if parts == ("/",):
        return True

    if _is_safe_temp_tree(resolved):
        return False

    # Windows drive root already handled by len(parts)==1 + anchor.
    # POSIX: ('/', 'etc', ...)
    if parts[0] == "/" and len(parts) >= 2:
        if parts[1].lower() in _CATASTROPHIC_TOP_LEVEL:
            return True
    return False


def _token_needs_resolve_check(token: str) -> bool:
    """Only canonicalize absolute / home / traversal-like rm targets."""
    if token in {"*", "~"}:
        return True
    if token.startswith(("~/", "~\\", "$", "%")):
        return True
    if token.startswith(("/", "\\")) or re.match(r"[A-Za-z]:[\\/]", token):
        return True
    if ".." in token.split("/") or ".." in token.split("\\"):
        return True
    if "/." in token or "\\." in token or "//" in token or "\\\\" in token:
        return True
    return False


def _extract_recursive_rm_targets(command: str) -> list[str]:
    """Best-effort path tokens from recursive ``rm`` command segments."""
    targets: list[str] = []
    for segment in re.split(r"[|&;]", command):
        if not _RE_RECURSIVE_RM.search(segment):
            continue
        try:
            tokens = shlex.split(segment, posix=os.name != "nt")
        except ValueError:
            tokens = segment.split()
        rm_idx = next(
            (
                i
                for i, tok in enumerate(tokens)
                if tok == "rm" or tok.endswith("/rm")
            ),
            None,
        )
        if rm_idx is None:
            continue
        for tok in tokens[rm_idx + 1 :]:
            if tok == "--":
                continue
            if tok.startswith("-") and tok != "-":
                continue
            targets.append(tok)
    return targets


def _rm_resolved_target_is_catastrophic(command: str) -> bool:
    """Catch ``/./``, ``//``, ``/tmp/..`` and similar after canonicalize."""
    if not _RE_RECURSIVE_RM.search(command):
        return False
    for token in _extract_recursive_rm_targets(command):
        if not _token_needs_resolve_check(token):
            continue
        if token == "*":
            return True
        try:
            expanded = os.path.expandvars(token)
            candidate = Path(expanded).expanduser()
            if not candidate.is_absolute():
                candidate = Path.cwd() / candidate
            resolved = candidate.resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if _is_resolved_path_catastrophic(resolved):
            return True
    return False


def classify_destructive_command(command: str) -> DestructiveKind | None:
    """Classify a shell command's destructive risk.

    Returns
    -------
    ``"catastrophic"``
        Wipe / mkfs / dd / fork-bomb style commands.  Safe for default
        ToolGuard auto-deny.
    ``"system_power"``
        ``shutdown`` / ``reboot`` / … in command position.  Still blocked
        by ACP hard-block and surfaced for approval, but not auto-denied
        by default (avoids ``npm run reboot`` hard failures).
    ``None``
        Not matched.
    """
    if not command or not command.strip():
        return None
    if any(p.search(command) for p in _CATASTROPHIC_COMPILED):
        return "catastrophic"
    if _rm_resolved_target_is_catastrophic(command):
        return "catastrophic"
    if any(p.search(command) for p in _SYSTEM_POWER_COMPILED):
        return "system_power"
    return None


def is_command_catastrophic(command: str) -> bool:
    """Return True for wipe/mkfs/dd/fork-bomb commands (auto-deny worthy)."""
    return classify_destructive_command(command) == "catastrophic"


def is_command_destructive(command: str) -> bool:
    """Check whether *command* matches a known dangerous pattern.

    Includes both catastrophic wipes and command-position system power
    commands (for ACP hard-block parity).
    """
    return classify_destructive_command(command) is not None


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
