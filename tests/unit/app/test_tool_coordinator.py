# -*- coding: utf-8 -*-
"""Unit tests for ToolCoordinator re-export from app_services.

The old ``qwenpaw.app.app_services.tool_coordinator`` module was replaced by
``qwenpaw.tool_calls``.  These tests verify the re-export path still works
and the new coordinator is constructable.  Detailed behavioural tests live in
``tests/unit/tool_calls/test_coordinator.py``.
"""

from __future__ import annotations

import pytest

from qwenpaw.app.app_services import ToolCallEntry, ToolCoordinator
from qwenpaw.tool_calls import ToolCallStatus


def test_coordinator_importable_from_app_services() -> None:
    assert ToolCoordinator is not None
    assert ToolCallEntry is not None


def test_coordinator_constructable() -> None:
    tc = ToolCoordinator()
    assert tc.list_entries() == []


def test_tool_call_status_values() -> None:
    assert ToolCallStatus.RUNNING == "running"
    assert ToolCallStatus.OFFLOADED == "offloaded"
    assert ToolCallStatus.COMPLETED == "completed"


@pytest.mark.asyncio
async def test_cancel_nonexistent_returns_false() -> None:
    tc = ToolCoordinator()
    ok = await tc.cancel("nonexistent")
    assert ok is False


@pytest.mark.asyncio
async def test_pop_pending_hints_empty() -> None:
    tc = ToolCoordinator()
    hints = await tc.pop_pending_hints("s-1")
    assert hints == []


@pytest.mark.asyncio
async def test_shutdown_noop_when_empty() -> None:
    tc = ToolCoordinator()
    await tc.shutdown()
