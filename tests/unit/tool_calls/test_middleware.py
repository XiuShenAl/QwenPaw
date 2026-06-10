# -*- coding: utf-8 -*-
"""Tests for ToolCoordinatorMiddleware."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolResponse

from qwenpaw.tool_calls._coordinator import ToolCoordinator
from qwenpaw.tool_calls._middleware import ToolCoordinatorMiddleware


def test_is_implemented_on_acting():
    coordinator = ToolCoordinator()
    mw = ToolCoordinatorMiddleware(coordinator=coordinator)
    assert mw.is_implemented("on_acting") is True


def test_is_not_implemented_other_hooks():
    coordinator = ToolCoordinator()
    mw = ToolCoordinatorMiddleware(coordinator=coordinator)
    assert mw.is_implemented("on_reply") is False
    assert mw.is_implemented("on_reasoning") is False
    assert mw.is_implemented("on_model_call") is False
    assert mw.is_implemented("on_system_prompt") is False


@pytest.mark.asyncio
async def test_on_acting_delegates_to_coordinator():
    coordinator = ToolCoordinator()

    async def _mock_next_handler(**_kwargs):
        yield ToolResponse(
            content=[TextBlock(type="text", text="result")],
            id="tc-1",
            state=ToolResultState.SUCCESS,
        )

    mw = ToolCoordinatorMiddleware(coordinator=coordinator)

    agent = SimpleNamespace(
        _request_context={
            "session_id": "s-1",
            "agent_id": "a-1",
            "root_session_id": "rs-1",
        },
    )
    tool_call = SimpleNamespace(
        name="test_tool",
        id="tc-1",
        input={},
    )
    input_kwargs = {"tool_call": tool_call}

    results = []
    async for item in mw.on_acting(agent, input_kwargs, _mock_next_handler):
        results.append(item)

    assert len(results) >= 1
    final = results[-1]
    assert isinstance(final, ToolResponse)
    assert final.state == ToolResultState.SUCCESS


@pytest.mark.asyncio
async def test_on_acting_passes_context_fields():
    received_kwargs = {}

    async def _capture_execute(  # pylint: disable=unused-argument
        tool_call,
        next_handler,
        *,
        session_id,
        agent_id,
        root_session_id,
        **kwargs,
    ):
        received_kwargs["session_id"] = session_id
        received_kwargs["agent_id"] = agent_id
        received_kwargs["root_session_id"] = root_session_id
        yield ToolResponse(
            content=[TextBlock(type="text", text="ok")],
            id=tool_call.id,
        )

    coordinator = MagicMock()
    coordinator.execute = _capture_execute
    mw = ToolCoordinatorMiddleware(coordinator=coordinator)

    agent = SimpleNamespace(
        _request_context={
            "session_id": "sess-42",
            "agent_id": "agent-7",
            "root_session_id": "root-99",
        },
    )
    tool_call = SimpleNamespace(name="tool", id="tc-2", input={})

    async for _ in mw.on_acting(agent, {"tool_call": tool_call}, None):
        pass

    assert received_kwargs["session_id"] == "sess-42"
    assert received_kwargs["agent_id"] == "agent-7"
    assert received_kwargs["root_session_id"] == "root-99"
