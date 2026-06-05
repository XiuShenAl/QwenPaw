# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for ``qwenpaw.app.app_services.tool_coordinator``."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.app.app_services.tool_coordinator import (
    ToolCall,
    ToolCallState,
    ToolCoordinator,
)


def _make_coordinator() -> ToolCoordinator:
    tracker = MagicMock(name="TaskTracker")
    tracker.register_external_task = AsyncMock()
    tracker.unregister_external_task = AsyncMock()
    return ToolCoordinator(task_tracker=tracker)


def _make_call(call_id: str = "c1", **kwargs) -> ToolCall:
    defaults = {"agent_id": "a1", "tool_name": "shell", "session_id": "s1"}
    defaults.update(kwargs)
    return ToolCall(call_id=call_id, **defaults)


@pytest.mark.asyncio
async def test_register_and_list_active() -> None:
    tc = _make_coordinator()
    c1 = _make_call("c1")
    await tc.register(c1)
    assert len(tc.list_active()) == 1
    assert tc.list_active()[0].call_id == "c1"


@pytest.mark.asyncio
async def test_state_transitions_pending_to_running_to_done() -> None:
    tc = _make_coordinator()
    c1 = _make_call("c1")
    await tc.register(c1)
    assert c1.state == ToolCallState.PENDING

    await tc.mark_running("c1")
    assert c1.state == ToolCallState.RUNNING

    await tc.mark_done("c1")
    assert c1.state == ToolCallState.DONE
    assert tc.list_active() == []


@pytest.mark.asyncio
async def test_cancel_sets_state_and_rejects_future() -> None:
    tc = _make_coordinator()
    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    c1 = _make_call("c1", future=fut)
    await tc.register(c1)
    await tc.mark_running("c1")

    await tc.cancel("c1")
    assert c1.state == ToolCallState.CANCELLED
    assert fut.done()
    with pytest.raises(asyncio.CancelledError):
        fut.result()


@pytest.mark.asyncio
async def test_cancel_noop_on_done() -> None:
    tc = _make_coordinator()
    c1 = _make_call("c1")
    await tc.register(c1)
    await tc.mark_done("c1")
    await tc.cancel("c1")
    assert c1.state == ToolCallState.DONE


@pytest.mark.asyncio
async def test_move_to_background_calls_task_tracker() -> None:
    tc = _make_coordinator()
    c1 = _make_call("c1")
    await tc.register(c1)
    await tc.mark_running("c1")

    await tc.move_to_background("c1")
    assert c1.state == ToolCallState.BACKGROUND

    tc._task_tracker.register_external_task.assert_awaited_once_with(
        "toolcall-c1",
    )


@pytest.mark.asyncio
async def test_list_active_filters_by_root_session() -> None:
    tc = _make_coordinator()
    c1 = _make_call("c1", root_session_id="r1")
    c2 = _make_call("c2", root_session_id="r2")
    await tc.register(c1)
    await tc.register(c2)

    r1_calls = tc.list_active(root_session_id="r1")
    assert len(r1_calls) == 1
    assert r1_calls[0].call_id == "c1"


@pytest.mark.asyncio
async def test_shutdown_cancels_futures_and_clears() -> None:
    tc = _make_coordinator()
    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    c1 = _make_call("c1", future=fut)
    await tc.register(c1)

    await tc.shutdown()
    assert fut.cancelled()
    assert tc.list_active() == []
