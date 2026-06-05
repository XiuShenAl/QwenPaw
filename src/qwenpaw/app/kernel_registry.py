# -*- coding: utf-8 -*-
"""KernelRegistry — MultiAgentManager that creates ``Kernel`` instances.

Extends ``MultiAgentManager`` with:
- ``app_services`` reference (cross-Kernel shared)
- ``bootstrap_plugins_kwargs`` — the 5 built-in class lists discovered
  once at lifespan startup, injected into each new Kernel

The parent's ``Workspace`` creation is overridden to produce ``Kernel``
instances instead.  All other behaviour (lazy loading, hot reload,
parallel startup) is inherited unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from .multi_agent_manager import MultiAgentManager

logger = logging.getLogger(__name__)


class KernelRegistry(MultiAgentManager):
    """MultiAgentManager that creates ``Kernel`` (not ``Workspace``)."""

    def __init__(
        self,
        *,
        app_services: Any = None,
        bootstrap_plugins_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.app_services = app_services
        self._bootstrap_kwargs = bootstrap_plugins_kwargs or {}

    def _create_workspace(self, agent_id: str, workspace_dir: str) -> Any:
        """Override to produce ``Kernel`` and run bootstrap_plugins."""
        from .kernel import Kernel

        kernel = Kernel(agent_id=agent_id, workspace_dir=workspace_dir)
        if self._bootstrap_kwargs:
            kernel.bootstrap_plugins(**self._bootstrap_kwargs)
        return kernel


__all__ = ["KernelRegistry"]
