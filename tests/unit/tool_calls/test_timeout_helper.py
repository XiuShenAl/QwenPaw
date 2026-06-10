# -*- coding: utf-8 -*-
"""Tests for cancellable_wait and effective_timeout."""
import asyncio

import pytest

from qwenpaw.tool_calls._context import ToolCallContext
from qwenpaw.tool_calls._ctxvars import (
    get_call_context,
    reset_call_context,
    set_call_context,
)
from qwenpaw.tool_calls._timeout_helper import (
    cancellable_wait,
    effective_timeout,
)


@pytest.mark.asyncio
async def test_cancellable_wait_no_ctx_no_fallback():
    assert get_call_context() is None
    result = await cancellable_wait(asyncio.sleep(0, result=42))
    assert result == 42


@pytest.mark.asyncio
async def test_cancellable_wait_no_ctx_with_fallback_success():
    result = await cancellable_wait(
        asyncio.sleep(0, result="ok"),
        fallback_secs=5.0,
    )
    assert result == "ok"


@pytest.mark.asyncio
async def test_cancellable_wait_no_ctx_with_fallback_timeout():
    with pytest.raises(asyncio.TimeoutError):
        await cancellable_wait(
            asyncio.sleep(100),
            fallback_secs=0.01,
        )


@pytest.mark.asyncio
async def test_cancellable_wait_with_ctx_normal_completion():
    loop = asyncio.get_event_loop()
    ctx = ToolCallContext(
        tool_call_id="tc-1",
        tool_name="test",
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
        started_at=loop.time(),
        deadline=loop.time() + 10.0,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    try:
        result = await cancellable_wait(asyncio.sleep(0, result="done"))
        assert result == "done"
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_cancellable_wait_with_ctx_cancelled():
    loop = asyncio.get_event_loop()
    ctx = ToolCallContext(
        tool_call_id="tc-1",
        tool_name="test",
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
        started_at=loop.time(),
        deadline=loop.time() + 100.0,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    try:

        async def _cancel_soon():
            await asyncio.sleep(0.05)
            ctx.cancel_event.set()

        asyncio.create_task(_cancel_soon())
        with pytest.raises(asyncio.CancelledError):
            await cancellable_wait(asyncio.sleep(100))
    finally:
        reset_call_context(token)


def test_effective_timeout_no_ctx():
    assert effective_timeout(30.0) == 30.0


@pytest.mark.asyncio
async def test_effective_timeout_with_ctx():
    loop = asyncio.get_event_loop()
    ctx = ToolCallContext(
        tool_call_id="tc-1",
        tool_name="test",
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
        started_at=loop.time(),
        deadline=loop.time() + 5.0,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    try:
        result = effective_timeout(30.0)
        assert 4.0 < result <= 5.0
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_effective_timeout_clamped():
    loop = asyncio.get_event_loop()
    ctx = ToolCallContext(
        tool_call_id="tc-1",
        tool_name="test",
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
        started_at=loop.time(),
        deadline=loop.time() + 1000.0,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    try:
        result = effective_timeout(10.0, max_amplify=5.0)
        assert result <= 50.0
    finally:
        reset_call_context(token)
