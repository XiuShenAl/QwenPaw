# -*- coding: utf-8 -*-
"""Hard checks for forked-worker integration before phase advance."""

from __future__ import annotations

from typing import Any


def forks_integrated(state: dict[str, Any] | None) -> bool:
    """Return True when state.json records successful fork merges."""
    if not isinstance(state, dict):
        return False
    return bool(state.get("forks_integrated"))


FORKS_INTEGRATED_REMINDER = """\
BLOCKED: forked worker results are not integrated yet.

{protocol}

Then update state.json: set forks_integrated=true.
Do NOT advance the workflow phase until that flag is set.
"""


def merge_blocked_continuation(protocol: str) -> str:
    """Controller prompt when the gate rejects a premature phase advance."""
    return FORKS_INTEGRATED_REMINDER.format(protocol=protocol)
