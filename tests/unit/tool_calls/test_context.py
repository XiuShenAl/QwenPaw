# -*- coding: utf-8 -*-
"""Tests for ToolCallContext."""
import asyncio

import pytest

from qwenpaw.tool_calls._context import (
    CancelReason,
    OffloadReason,
    ToolCallContext,
)


def _make_ctx(**overrides):
    defaults = {
        "tool_call_id": "tc-1",
        "tool_name": "test_tool",
        "session_id": "s-1",
        "agent_id": "a-1",
        "root_session_id": "rs-1",
        "started_at": 0.0,
        "deadline": None,
        "cancel_event": asyncio.Event(),
    }
    defaults.update(overrides)
    return ToolCallContext(**defaults)


def test_is_cancelled_initially_false():
    ctx = _make_ctx()
    assert ctx.is_cancelled is False


def test_is_cancelled_after_set():
    ctx = _make_ctx()
    ctx.cancel_event.set()
    assert ctx.is_cancelled is True


def test_remaining_none_when_no_deadline():
    ctx = _make_ctx(deadline=None)
    assert ctx.remaining() is None


@pytest.mark.asyncio
async def test_remaining_positive():
    loop = asyncio.get_event_loop()
    now = loop.time()
    ctx = _make_ctx(deadline=now + 10.0)
    remaining = ctx.remaining()
    assert remaining is not None
    assert 9.0 < remaining <= 10.0


@pytest.mark.asyncio
async def test_remaining_zero_when_past_deadline():
    loop = asyncio.get_event_loop()
    now = loop.time()
    ctx = _make_ctx(deadline=now - 1.0)
    assert ctx.remaining() == 0.0


def test_cancel_reason_enum():
    assert CancelReason.USER == "user"
    assert CancelReason.TIMEOUT == "timeout"
    assert CancelReason.AGENT == "agent"
    assert CancelReason.SHUTDOWN == "shutdown"


def test_offload_reason_enum():
    assert OffloadReason.USER == "user"
    assert OffloadReason.TIMEOUT == "timeout"


def test_extra_and_governance_metadata_default_empty():
    ctx = _make_ctx()
    assert not ctx.extra
    assert not ctx.governance_metadata
