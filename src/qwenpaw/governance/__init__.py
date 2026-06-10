# -*- coding: utf-8 -*-
"""Governance interface stubs (NOT IMPLEMENTED).

Future workspace-level policy evaluator that replaces
GuardedFunctionTool's check_permissions via GovernanceAwareTool.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class GovernanceAction(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"
    SANDBOX_FALLBACK = "sandbox_fallback"


@dataclass
class GovernanceDecision:
    action: GovernanceAction
    reason: str
    sandbox_config: dict[str, Any] | None = None


class GovernanceAdapter:
    """Future workspace-level policy evaluator — NOT IMPLEMENTED.

    Integration point: replaces GuardedFunctionTool's check_permissions
    via a thin GovernanceAwareTool wrapper.
    """

    async def evaluate(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: Any,
    ) -> GovernanceDecision:
        raise NotImplementedError


__all__ = [
    "GovernanceAction",
    "GovernanceAdapter",
    "GovernanceDecision",
]
