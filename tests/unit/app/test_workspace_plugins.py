# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.workspace.WorkspacePlugins``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.workspace import WorkspacePlugins
from qwenpaw.modes.base import AgentMode
from qwenpaw.runtime.hooks import HookRegistry
from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry


class _Mode(AgentMode):
    def __init__(
        self,
        name: str,
        active: bool = False,
        raise_in_setup: bool = False,
    ) -> None:
        self.name = name
        self._active = active
        self.setup_called_with: object | None = None
        self._raise = raise_in_setup

    def setup(self, workspace: object) -> None:
        if self._raise:
            raise RuntimeError("setup failed")
        self.setup_called_with = workspace

    def is_active(self, ctx) -> bool:
        return self._active


def test_default_factories_produce_distinct_per_instance_registries() -> None:
    a = WorkspacePlugins()
    b = WorkspacePlugins()
    assert isinstance(a.slash_command_registry, SlashCommandRegistry)
    assert isinstance(a.hook_registry, HookRegistry)
    assert a.slash_command_registry is not b.slash_command_registry
    assert a.hook_registry is not b.hook_registry
    assert a.modes is not b.modes


def test_register_mode_triggers_setup_with_workspace() -> None:
    plugins = WorkspacePlugins()
    workspace = SimpleNamespace(id="w1")
    mode = _Mode("coding")

    plugins.register_mode(mode, workspace)

    assert mode in plugins.modes
    assert mode.setup_called_with is workspace


def test_register_mode_rejects_duplicate_name() -> None:
    plugins = WorkspacePlugins()
    plugins.register_mode(_Mode("coding"), SimpleNamespace())

    with pytest.raises(ValueError, match="already registered"):
        plugins.register_mode(_Mode("coding"), SimpleNamespace())


def test_active_mode_names_filters_by_is_active() -> None:
    plugins = WorkspacePlugins()
    plugins.register_mode(_Mode("coding", active=True), SimpleNamespace())
    plugins.register_mode(_Mode("mission", active=False), SimpleNamespace())
    plugins.register_mode(_Mode("plan", active=True), SimpleNamespace())

    assert plugins.active_mode_names(ctx=None) == {"coding", "plan"}
