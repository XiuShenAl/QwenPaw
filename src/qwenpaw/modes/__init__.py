# -*- coding: utf-8 -*-
"""Mode abstractions (Phase 1 skeleton).

Each ``AgentMode`` packages the commands / tools / hooks / prompt
contributors that belong to one runtime mode (``coding`` / ``mission``
/ ``plan``). Concrete modes land in Phase 5; Phase 1 only ships the
base class and the ``ModeGatedHook`` mix-in so future authors have one
place to write against.
"""

from __future__ import annotations

from .base import AgentMode, ModeGatedHook

__all__ = ["AgentMode", "ModeGatedHook"]
