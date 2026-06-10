# -*- coding: utf-8 -*-
"""Kernel — Workspace + per-Kernel plugin layer.

Extends ``Workspace`` with a ``KernelPlugins`` instance and a
``bootstrap_plugins()`` method that populates the per-Kernel
registries (tools, commands, hooks, modes, prompt contributors)
with the built-in classes discovered once at lifespan startup.

The naming convention follows the runtime refactor HTML §0:
``Kernel = Workspace + plugins``.  All existing ``Workspace``
behaviour is preserved via inheritance — nothing is overridden.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from .kernel_plugins import KernelPlugins
from ..workspace.local_workspace import QwenPawLocalWorkspace
from ..workspace.workspace import Workspace

logger = logging.getLogger(__name__)


class Kernel(Workspace):
    """Workspace extended with per-Kernel pluggable registries."""

    def __init__(self, agent_id: str, workspace_dir: str) -> None:
        super().__init__(agent_id, workspace_dir)
        self.plugins = KernelPlugins()
        self._local_workspace = QwenPawLocalWorkspace(
            tool_registry=self.plugins.tool_registry,
            workdir=str(self.workspace_dir),
            workspace_id=agent_id,
            default_mcps=[],
            skill_paths=[],
        )

    @property
    def local_workspace(self) -> QwenPawLocalWorkspace:
        """AgentScope LocalWorkspace routing tools to ToolRegistry."""
        return self._local_workspace

    def bootstrap_plugins(  # pylint: disable=too-many-branches
        self,
        *,
        builtin_tool_funcs: Iterable[Any] | None = None,
        builtin_contributor_clses: Iterable[type] | None = None,
        builtin_mode_clses: Iterable[type] | None = None,
        builtin_hook_clses: Iterable[type] | None = None,
        builtin_command_specs: Iterable[Any] | None = None,
        builtin_fallback_handler: Any | None = None,
    ) -> None:
        """Populate per-Kernel registries with built-in classes.

        Called once by ``KernelRegistry`` immediately after Kernel creation.
        """
        # Tools → ToolRegistry (lives in plugins)
        if builtin_tool_funcs:
            tr = self.plugins.tool_registry
            for func in builtin_tool_funcs:
                try:
                    desc = getattr(func, "_tool_descriptor", None)
                    if desc is not None:
                        tr.register(desc)
                    else:
                        logger.debug(
                            "bootstrap: %s has no _tool_descriptor, skipped",
                            getattr(func, "__name__", func),
                        )
                except Exception:
                    logger.debug(
                        "bootstrap: tool register failed for %s",
                        getattr(func, "__name__", func),
                        exc_info=True,
                    )

        # Prompt contributors → PromptManager (lives in plugins)
        if builtin_contributor_clses:
            for cls in builtin_contributor_clses:
                try:
                    self.plugins.prompt_manager.register(cls())
                except Exception:
                    logger.debug(
                        "bootstrap: contributor register failed for %s",
                        cls,
                        exc_info=True,
                    )

        # Lifecycle hooks → HookRegistry (lives in plugins)
        if builtin_hook_clses:
            for cls in builtin_hook_clses:
                try:
                    self.plugins.hook_registry.register(cls())
                except Exception:
                    logger.debug(
                        "bootstrap: hook register failed for %s",
                        cls,
                        exc_info=True,
                    )

        # Slash commands → SlashCommandRegistry (lives in plugins)
        if builtin_command_specs:
            for spec in builtin_command_specs:
                try:
                    self.plugins.slash_command_registry.register(spec)
                except Exception:
                    logger.debug(
                        "bootstrap: command register failed for %s",
                        getattr(spec, "name", spec),
                        exc_info=True,
                    )

        # Skill fallback → SlashCommandRegistry (lives in plugins)
        if builtin_fallback_handler is not None:
            try:
                self.plugins.slash_command_registry.register_fallback(
                    builtin_fallback_handler,
                )
            except Exception:
                logger.debug(
                    "bootstrap: fallback handler register failed",
                    exc_info=True,
                )

        # Modes → KernelPlugins.register_mode (runs mode.setup(kernel))
        if builtin_mode_clses:
            for cls in builtin_mode_clses:
                try:
                    mode = cls()
                    self.plugins.register_mode(mode, self)
                except Exception:
                    logger.debug(
                        "bootstrap: mode register failed for %s",
                        cls,
                        exc_info=True,
                    )

        # pylint: disable=protected-access
        n_hooks = len(self.plugins.hook_registry._by_phase)
        n_cmds = len(
            self.plugins.slash_command_registry._by_name,
        )
        # pylint: enable=protected-access
        logger.info(
            "kernel %s: bootstrap_plugins complete "
            "(hooks=%d commands=%d modes=%d)",
            self.agent_id,
            n_hooks,
            n_cmds,
            len(self.plugins.modes),
        )


__all__ = ["Kernel"]
