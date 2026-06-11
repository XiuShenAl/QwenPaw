# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for ``qwenpaw.app.app_services.AppServiceManager``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.app_services import (
    AppServiceManager,
    ApprovalCoordinator,
    ToolCoordinator,
)


def _make_app_services() -> AppServiceManager:
    """AppServiceManager with both cross-singletons stubbed out.

    The ``TaskTracker`` injection is required in the test environment to
    avoid eagerly importing ``app.runner.__init__``, which transitively
    imports agentscope 2.0-only modules that the test venv may lack.
    """
    fake_tracker = MagicMock(name="TaskTracker")
    fake_service = MagicMock(name="ApprovalService")
    return AppServiceManager(
        task_tracker=fake_tracker,
        approval_service=fake_service,
    )


def test_three_field_whitelist_is_enforced_by_slots() -> None:
    asm = _make_app_services()

    # __slots__ forbids any other attribute name — this is the cheapest
    # mechanical guard against silently adding a 4th cross-workspace field.
    with pytest.raises(AttributeError):
        # pylint: disable-next=assigning-non-slot
        asm.foo = object()  # type: ignore[attr-defined]

    expected_fields = {
        "task_tracker",
        "tool_coordinator",
        "approval_coordinator",
    }
    assert set(asm.__slots__) == expected_fields


def test_construction_wires_the_three_coordinators() -> None:
    asm = _make_app_services()
    assert asm.task_tracker is not None
    assert isinstance(asm.tool_coordinator, ToolCoordinator)
    assert isinstance(asm.approval_coordinator, ApprovalCoordinator)
    assert asm.tool_coordinator.list_entries() == []


@pytest.mark.asyncio
async def test_start_and_stop_invoke_lifecycle_methods_in_order() -> None:
    """When task_tracker exposes start/stop, AppServiceManager calls them."""
    fake_tracker = MagicMock()
    fake_tracker.start = AsyncMock()
    fake_tracker.stop = AsyncMock()
    fake_service = MagicMock()

    asm = AppServiceManager(
        task_tracker=fake_tracker,
        approval_service=fake_service,
    )

    call_log: list[str] = []
    fake_tracker.start.side_effect = lambda: call_log.append("tracker.start")
    fake_tracker.stop.side_effect = lambda: call_log.append("tracker.stop")
    original_shutdown = asm.tool_coordinator.shutdown

    async def _spy_shutdown():
        call_log.append("tool.shutdown")
        await original_shutdown()

    asm.tool_coordinator.shutdown = _spy_shutdown  # type: ignore[assignment]

    await asm.start()
    await asm.stop()

    assert call_log == ["tracker.start", "tool.shutdown", "tracker.stop"]


@pytest.mark.asyncio
async def test_start_and_stop_are_no_ops_when_tracker_has_no_lifecycle() -> (
    None
):
    """AppServiceManager silently skips missing start/stop."""
    minimal_tracker = object()  # no .start / no .stop
    asm = AppServiceManager(
        task_tracker=minimal_tracker,  # type: ignore[arg-type]
        approval_service=MagicMock(),
    )
    await asm.start()
    await asm.stop()


def test_approval_coordinator_forwards_via_getattr() -> None:
    fake = MagicMock()
    fake.list_pending.return_value = ["pa1"]
    coord = ApprovalCoordinator(service=fake)

    assert coord.list_pending() == ["pa1"]
    fake.list_pending.assert_called_once()
