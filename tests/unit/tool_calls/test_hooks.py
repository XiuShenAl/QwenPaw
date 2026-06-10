# -*- coding: utf-8 -*-
"""Tests for ToolHookRegistry."""
from qwenpaw.tool_calls._hooks import ToolHookRegistry


def test_get_unregistered_returns_empty_pair():
    registry = ToolHookRegistry()
    pair = registry.get("unknown_tool")
    assert pair.before is None
    assert pair.after is None
    assert pair.default_timeout_secs is None
    assert pair.max_internal_timeout_secs is None


def test_register_timeout_only():
    registry = ToolHookRegistry()
    registry.register("shell", default_timeout_secs=60.0)
    pair = registry.get("shell")
    assert pair.default_timeout_secs == 60.0
    assert pair.before is None


def test_register_merge_preserves_existing():
    registry = ToolHookRegistry()

    async def before_hook(inp, _ctx):
        return inp

    registry.register("shell", before=before_hook, default_timeout_secs=60.0)
    registry.register("shell", max_internal_timeout_secs=300.0)

    pair = registry.get("shell")
    assert pair.before is before_hook
    assert pair.default_timeout_secs == 60.0
    assert pair.max_internal_timeout_secs == 300.0


def test_register_overwrite():
    registry = ToolHookRegistry()
    registry.register("tool", default_timeout_secs=10.0)
    registry.register("tool", default_timeout_secs=20.0)
    assert registry.get("tool").default_timeout_secs == 20.0


def test_unregister():
    registry = ToolHookRegistry()
    registry.register("tool", default_timeout_secs=10.0)
    registry.unregister("tool")
    pair = registry.get("tool")
    assert pair.default_timeout_secs is None


def test_unregister_nonexistent_no_error():
    registry = ToolHookRegistry()
    registry.unregister("nonexistent")  # should not raise
