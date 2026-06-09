# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for ``qwenpaw.runtime.executor.AgentExecutor``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.runtime.envelope import Envelope
from qwenpaw.runtime.executor import AgentExecutor


class _FakeAgent:
    """Fake agent that yields a sequence of events from reply_stream."""

    def __init__(self, events):
        self._events = events

    async def reply_stream(
        self,
        inputs=None,
    ):  # pylint: disable=unused-argument
        for ev in self._events:
            yield ev


async def _collect(agen):
    items = []
    async for item in agen:
        items.append(item)
    return items


@pytest.mark.asyncio
async def test_executor_translates_events():
    from agentscope.event import EventType

    events = [
        SimpleNamespace(type=EventType.TEXT_BLOCK_START, block_id="b1"),
        SimpleNamespace(
            type=EventType.TEXT_BLOCK_DELTA,
            block_id="b1",
            delta="hi",
        ),
        SimpleNamespace(type=EventType.TEXT_BLOCK_END, block_id="b1"),
    ]
    agent = _FakeAgent(events)
    envelope = Envelope()
    executor = AgentExecutor(agent, envelope)

    items = await _collect(executor.run([]))
    assert len(items) > 0
    assert envelope._text_blocks.get("b1") is not None


@pytest.mark.asyncio
async def test_executor_handles_empty_stream():
    agent = _FakeAgent([])
    envelope = Envelope()
    executor = AgentExecutor(agent, envelope)

    items = await _collect(executor.run([]))
    assert len(items) == 0
