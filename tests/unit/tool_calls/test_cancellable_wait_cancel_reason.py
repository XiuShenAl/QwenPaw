# -*- coding: utf-8 -*-
"""cancellable_wait cancel vs timeout reason separation."""
from __future__ import annotations

import asyncio

import pytest

from qwenpaw.tool_calls import (
    cancellable_wait,
    reset_call_context,
    set_call_context,
)
from qwenpaw.tool_calls._context import CancelReason, ToolCallContext


@pytest.mark.asyncio
async def test_user_cancel_raises_cancelled_with_user_reason():
    ctx = ToolCallContext(
        tool_call_id="tc-cancel",
        tool_name="shell",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=0.0,
        offload_deadline=None,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    try:

        async def work() -> str:
            await asyncio.sleep(10)
            return "done"

        async def cancel_soon() -> None:
            await asyncio.sleep(0.01)
            ctx.cancel_reason = CancelReason.USER
            ctx.cancel_event.set()

        asyncio.create_task(cancel_soon())
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await cancellable_wait(
                work(),
                fallback_secs=5,
                as_kill_deadline=True,
            )
        assert "reason=user" in str(exc_info.value)
    finally:
        reset_call_context(token)


@pytest.mark.asyncio
async def test_timeout_cancel_raises_cancelled_with_timeout_reason():
    ctx = ToolCallContext(
        tool_call_id="tc-timeout",
        tool_name="shell",
        session_id="s",
        agent_id="a",
        root_session_id="r",
        started_at=0.0,
        offload_deadline=None,
        cancel_event=asyncio.Event(),
    )
    token = set_call_context(ctx)
    try:

        async def work() -> str:
            await asyncio.sleep(10)
            return "done"

        async def timeout_soon() -> None:
            await asyncio.sleep(0.01)
            ctx.cancel_reason = CancelReason.TIMEOUT
            ctx.cancel_event.set()

        asyncio.create_task(timeout_soon())
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await cancellable_wait(
                work(),
                fallback_secs=5,
                as_kill_deadline=True,
            )
        assert "reason=timeout" in str(exc_info.value)
    finally:
        reset_call_context(token)
