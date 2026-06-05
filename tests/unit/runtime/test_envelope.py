# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Unit tests for ``qwenpaw.runtime.envelope.Envelope``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.runtime.envelope import Envelope


async def _collect(agen):
    """Exhaust an async generator into a list."""
    items = []
    async for item in agen:
        items.append(item)
    return items


@pytest.mark.asyncio
async def test_emit_response_created():
    env = Envelope()
    items = await _collect(env.emit_response_created())
    assert len(items) == 2
    # Both items reference the same _response object; after iteration
    # its status is InProgress (the final mutation). Verify we got 2 yields.
    assert items[-1].status.value == "in_progress"


@pytest.mark.asyncio
async def test_heartbeat():
    env = Envelope()
    items = await _collect(env.heartbeat())
    assert len(items) == 1


@pytest.mark.asyncio
async def test_from_msg():
    from agentscope.message import Msg
    from agentscope.message._block import TextBlock

    msg = Msg(
        name="assistant",
        role="assistant",
        content=[TextBlock(text="hello world")],
    )
    env = Envelope()
    items = await _collect(env.from_msg(msg))
    assert len(items) >= 3
    assert env._finalized


@pytest.mark.asyncio
async def test_error_envelope():
    env = Envelope()
    items = await _collect(env.error_envelope("something broke"))
    assert any(
        getattr(item, "status", None) and item.status.value == "failed"
        for item in items
    )


@pytest.mark.asyncio
async def test_cancel_envelope():
    env = Envelope()
    items = await _collect(env.cancel_envelope())
    assert len(items) >= 1
    assert env._finalized


@pytest.mark.asyncio
async def test_finalize_idempotent():
    env = Envelope()
    items1 = await _collect(env.finalize())
    items2 = await _collect(env.finalize())
    assert len(items1) >= 1
    assert len(items2) == 0


@pytest.mark.asyncio
async def test_text_block_events():
    from agentscope.event import EventType

    env = Envelope()
    events = [
        SimpleNamespace(type=EventType.TEXT_BLOCK_START, block_id="b1"),
        SimpleNamespace(
            type=EventType.TEXT_BLOCK_DELTA,
            block_id="b1",
            delta="hello ",
        ),
        SimpleNamespace(
            type=EventType.TEXT_BLOCK_DELTA,
            block_id="b1",
            delta="world",
        ),
        SimpleNamespace(type=EventType.TEXT_BLOCK_END, block_id="b1"),
    ]
    all_items = []
    for ev in events:
        all_items.extend(await _collect(env.translate_event(ev)))

    assert env._text_blocks["b1"]["text"] == "hello world"
    content_items = [
        i for i in all_items if hasattr(i, "text") and hasattr(i, "delta")
    ]
    assert len(content_items) >= 2


@pytest.mark.asyncio
async def test_thinking_block_events():
    from agentscope.event import EventType

    env = Envelope()
    events = [
        SimpleNamespace(type=EventType.THINKING_BLOCK_START, block_id="t1"),
        SimpleNamespace(
            type=EventType.THINKING_BLOCK_DELTA,
            block_id="t1",
            delta="hmm",
        ),
        SimpleNamespace(type=EventType.THINKING_BLOCK_END, block_id="t1"),
    ]
    all_items = []
    for ev in events:
        all_items.extend(await _collect(env.translate_event(ev)))

    assert env._reasoning_blocks["t1"]["text"] == "hmm"


@pytest.mark.asyncio
async def test_tool_call_events():
    from agentscope.event import EventType

    env = Envelope()
    events = [
        SimpleNamespace(
            type=EventType.TOOL_CALL_START,
            tool_call_id="tc1",
            tool_call_name="search",
        ),
        SimpleNamespace(
            type=EventType.TOOL_CALL_DELTA,
            tool_call_id="tc1",
            delta='{"q":"hi"}',
        ),
        SimpleNamespace(
            type=EventType.TOOL_CALL_END,
            tool_call_id="tc1",
        ),
    ]
    all_items = []
    for ev in events:
        all_items.extend(await _collect(env.translate_event(ev)))

    plugin_calls = [
        i
        for i in all_items
        if hasattr(i, "type")
        and getattr(i.type, "value", None) == "plugin_call"
    ]
    assert len(plugin_calls) == 1


@pytest.mark.asyncio
async def test_tool_result_events():
    from agentscope.event import EventType

    env = Envelope()
    env._tool_calls["tc1"] = {
        "input_msg_id": "imid",
        "name": "search",
        "args_json_acc": "",
        "output_text_acc": "",
    }
    events = [
        SimpleNamespace(
            type=EventType.TOOL_RESULT_START,
            tool_call_id="tc1",
            tool_call_name="search",
        ),
        SimpleNamespace(
            type=EventType.TOOL_RESULT_TEXT_DELTA,
            tool_call_id="tc1",
            delta="result text",
        ),
        SimpleNamespace(
            type=EventType.TOOL_RESULT_END,
            tool_call_id="tc1",
            state=None,
        ),
    ]
    all_items = []
    for ev in events:
        all_items.extend(await _collect(env.translate_event(ev)))

    output_msgs = [
        i
        for i in all_items
        if hasattr(i, "type")
        and getattr(i.type, "value", None) == "plugin_call_output"
    ]
    assert len(output_msgs) >= 1
