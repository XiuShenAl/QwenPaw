# -*- coding: utf-8 -*-
"""Per-Kernel pluggable layer.

Concretizes the HTML §0 "插件/Hook（注册进 Runtime）" tier as a single
dataclass holding the three per-Kernel registries that ``Runtime.run()``
reads each request:

* :class:`SlashCommandRegistry` — slash dispatch
* :class:`HookRegistry`         — 8-phase hook orchestration
* ``modes``                     — list of :class:`AgentMode` instances

Every field is **per-Kernel** — no cross-Kernel sharing. The
matching cross-Kernel container is ``AppServiceManager`` and is strictly
limited to its three coordinators (see ``app/app_services/``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...runtime.hooks import HookRegistry
from ...runtime.slash_command_registry import SlashCommandRegistry

if TYPE_CHECKING:
    from ...modes.base import AgentMode
    from ...runtime.hooks import HookContext


@dataclass
class KernelPlugins:
    """Three per-Kernel pluggable registries packed into one container."""

    slash_command_registry: SlashCommandRegistry = field(
        default_factory=SlashCommandRegistry,
    )
    hook_registry: HookRegistry = field(default_factory=HookRegistry)
    modes: list["AgentMode"] = field(default_factory=list)

    def register_mode(self, mode: "AgentMode", kernel: object) -> None:
        """Add ``mode`` and immediately run its ``setup(kernel)``.

        Duplicate names are rejected — collisions usually mean two
        bootstrap paths both think they own the mode and silently
        double-registering would cause subtle dispatch ambiguities.
        """
        if any(m.name == mode.name for m in self.modes):
            raise ValueError(f"AgentMode {mode.name!r} already registered")
        self.modes.append(mode)
        mode.setup(kernel)

    def active_mode_names(self, ctx: "HookContext") -> set[str]:
        """Return the names of every mode reporting ``is_active(ctx)``.

        Used by ``ToolRegistry.filter`` (and any other code that needs
        the runtime-active set) so per-Kernel mode state never leaks
        into cross-Kernel containers.
        """
        return {m.name for m in self.modes if m.is_active(ctx)}


__all__ = ["KernelPlugins"]
