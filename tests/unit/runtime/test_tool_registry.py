# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for ``qwenpaw.runtime.tool_registry``."""

from __future__ import annotations

import pytest

from qwenpaw.runtime.tool_registry import (
    ToolDescriptor,
    ToolRegistry,
    tool_descriptor,
)


def _desc(name: str, **kwargs) -> ToolDescriptor:
    return ToolDescriptor(name=name, func=lambda: None, **kwargs)


def test_filter_default_returns_all_enabled_unconditional_tools() -> None:
    reg = ToolRegistry()
    reg.register(_desc("a"))
    reg.register(_desc("b"))

    out = reg.filter()
    assert sorted(d.name for d in out) == ["a", "b"]


def test_filter_denied_wins_over_everything() -> None:
    reg = ToolRegistry()
    reg.register(_desc("a"))
    reg.register(_desc("b"))

    out = reg.filter(allowed={"a", "b"}, denied={"a"})
    assert [d.name for d in out] == ["b"]


def test_filter_allowed_enables_disabled_by_default() -> None:
    reg = ToolRegistry()
    reg.register(_desc("a"))
    reg.register(_desc("b", enabled_by_default=False))
    reg.register(_desc("c"))

    # Default: 'b' is excluded (enabled_by_default=False).
    out_default = reg.filter()
    assert sorted(d.name for d in out_default) == ["a", "c"]

    # Explicit allow brings 'b' back; 'c' dropped.
    out_allow = reg.filter(allowed={"a", "b"})
    assert sorted(d.name for d in out_allow) == ["a", "b"]


def test_filter_requires_modes_any_overlap_wins() -> None:
    reg = ToolRegistry()
    reg.register(_desc("coding", requires_modes=("coding",)))
    reg.register(_desc("any"))

    assert sorted(d.name for d in reg.filter(active_modes={"mission"})) == [
        "any",
    ]
    assert sorted(
        d.name for d in reg.filter(active_modes={"coding", "mission"})
    ) == [
        "any",
        "coding",
    ]


def test_filter_requires_features_requires_all() -> None:
    reg = ToolRegistry()
    reg.register(_desc("net", requires_features=("network", "beta")))

    assert not reg.filter(enabled_features={"network"})
    out = reg.filter(enabled_features={"network", "beta"})
    assert [d.name for d in out] == ["net"]


def test_register_duplicate_raises() -> None:
    reg = ToolRegistry()
    reg.register(_desc("a"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_desc("a"))


def test_register_rejects_non_descriptor() -> None:
    reg = ToolRegistry()
    with pytest.raises(TypeError):
        reg.register("not a descriptor")  # type: ignore[arg-type]


def test_decorator_attaches_descriptor_with_defaults() -> None:
    @tool_descriptor(requires_sandbox=("file_read",))
    async def read_file(_path: str) -> str:
        """Read a file."""
        return ""

    desc = read_file._tool_descriptor  # type: ignore[attr-defined]
    assert isinstance(desc, ToolDescriptor)
    assert desc.name == "read_file"
    assert desc.requires_sandbox == ("file_read",)
    assert desc.func is read_file


def test_decorator_can_override_name_and_passes_metadata() -> None:
    @tool_descriptor(name="custom", group="files")
    def fn():
        pass

    desc = fn._tool_descriptor  # type: ignore[attr-defined]
    assert desc.name == "custom"
    assert desc.metadata == {"group": "files"}
