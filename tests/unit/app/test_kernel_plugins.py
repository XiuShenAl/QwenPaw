# -*- coding: utf-8 -*-
"""Unit tests for ``qwenpaw.app.kernel.KernelPlugins``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.app.kernel import KernelPlugins
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

    def setup(self, kernel: object) -> None:
        if self._raise:
            raise RuntimeError("setup failed")
        self.setup_called_with = kernel

    def is_active(self, ctx) -> bool:
        return self._active


def test_default_factories_produce_distinct_per_instance_registries() -> None:
    a = KernelPlugins()
    b = KernelPlugins()
    assert isinstance(a.slash_command_registry, SlashCommandRegistry)
    assert isinstance(a.hook_registry, HookRegistry)
    assert a.slash_command_registry is not b.slash_command_registry
    assert a.hook_registry is not b.hook_registry
    assert a.modes is not b.modes


def test_register_mode_triggers_setup_with_kernel() -> None:
    plugins = KernelPlugins()
    kernel = SimpleNamespace(id="k1")
    mode = _Mode("coding")

    plugins.register_mode(mode, kernel)

    assert mode in plugins.modes
    assert mode.setup_called_with is kernel


def test_register_mode_rejects_duplicate_name() -> None:
    plugins = KernelPlugins()
    plugins.register_mode(_Mode("coding"), SimpleNamespace())

    with pytest.raises(ValueError, match="already registered"):
        plugins.register_mode(_Mode("coding"), SimpleNamespace())


def test_active_mode_names_filters_by_is_active() -> None:
    plugins = KernelPlugins()
    plugins.register_mode(_Mode("coding", active=True), SimpleNamespace())
    plugins.register_mode(_Mode("mission", active=False), SimpleNamespace())
    plugins.register_mode(_Mode("plan", active=True), SimpleNamespace())

    assert plugins.active_mode_names(ctx=None) == {"coding", "plan"}
