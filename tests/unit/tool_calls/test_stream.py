# -*- coding: utf-8 -*-
"""Tests for ToolStream fan-out notifier."""
import asyncio

import pytest

from qwenpaw.tool_calls._stream import ToolStream


@pytest.mark.asyncio
async def test_single_subscriber_receives_chunks():
    stream = ToolStream(tool_call_id="tc-1", session_id="s-1")
    received = []

    async def reader():
        async for chunk in stream.subscribe():
            received.append(chunk)

    task = asyncio.create_task(reader())
    await asyncio.sleep(0.01)
    await stream.append("chunk-1")
    await stream.append("chunk-2")
    await stream.close()
    await task

    assert received == ["chunk-1", "chunk-2"]


@pytest.mark.asyncio
async def test_multiple_subscribers_same_order():
    stream = ToolStream(tool_call_id="tc-1", session_id="s-1")
    received_a = []
    received_b = []

    async def reader(output):
        async for chunk in stream.subscribe():
            output.append(chunk)

    task_a = asyncio.create_task(reader(received_a))
    task_b = asyncio.create_task(reader(received_b))
    await asyncio.sleep(0.01)
    await stream.append("x")
    await stream.append("y")
    await stream.close()
    await asyncio.gather(task_a, task_b)

    assert received_a == ["x", "y"]
    assert received_b == ["x", "y"]


@pytest.mark.asyncio
async def test_close_idempotent():
    stream = ToolStream(tool_call_id="tc-1", session_id="s-1")
    await stream.close()
    await stream.close()  # should not raise


@pytest.mark.asyncio
async def test_append_after_close_ignored():
    stream = ToolStream(tool_call_id="tc-1", session_id="s-1")
    await stream.close()
    await stream.append("late-chunk")  # should not raise


@pytest.mark.asyncio
async def test_subscribe_after_close_returns_immediately():
    stream = ToolStream(tool_call_id="tc-1", session_id="s-1")
    await stream.close()

    received = []
    async for chunk in stream.subscribe():
        received.append(chunk)

    assert not received
