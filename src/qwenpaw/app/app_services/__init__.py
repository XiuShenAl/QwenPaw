# -*- coding: utf-8 -*-
"""Cross-Kernel coordination services held by FastAPI lifespan.

Per ``runtime_refactor_v2.html`` §0, the AppServiceManager is the ONLY
cross-Kernel container, and it is *strictly* limited to three coordinators:

* ``task_tracker``         — observability for streaming runs
* ``tool_coordinator``     — HITL tool-call coordination
* ``approval_coordinator`` — HITL approval coordination

Any state that should be per-Kernel (ToolRegistry, PromptManager,
SlashCommandRegistry, HookRegistry, modes, …) belongs on
``Kernel.service_manager`` / ``Kernel.plugins`` instead — never here.
"""

from __future__ import annotations

from .app_service_manager import AppServiceManager
from .approval_coordinator import ApprovalCoordinator
from .tool_coordinator import ToolCall, ToolCoordinator

__all__ = [
    "AppServiceManager",
    "ApprovalCoordinator",
    "ToolCall",
    "ToolCoordinator",
]
