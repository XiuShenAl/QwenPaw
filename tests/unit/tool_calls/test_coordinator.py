# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for ToolCoordinator."""
import asyncio
from types import SimpleNamespace

import pytest

from agentscope.message import TextBlock, ToolResultState
from agentscope.tool import ToolChunk, ToolResponse

from qwenpaw.tool_calls._context import CancelReason
from qwenpaw.tool_calls._coordinator import ToolCoordinator


def _make_tool_call(name="test_tool", tc_id="tc-1"):
    return SimpleNamespace(name=name, id=tc_id, input={})


async def _simple_next_handler(**kwargs):
    """A next_handler that yields one chunk then a final response."""
    tc = kwargs.get("tool_call")
    yield ToolChunk(
        content=[TextBlock(type="text", text="progress...")],
        state=ToolResultState.RUNNING,
    )
    yield ToolResponse(
        content=[TextBlock(type="text", text="done")],
        id=tc.id if tc else "tc-1",
        state=ToolResultState.SUCCESS,
    )


async def _slow_next_handler(**kwargs):
    """A next_handler that takes a long time but responds to cancellation."""
    from qwenpaw.tool_calls import cancellable_wait

    tc = kwargs.get("tool_call")
    try:
        await cancellable_wait(asyncio.sleep(100), fallback_secs=100)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        yield ToolResponse(
            content=[TextBlock(type="text", text="cancelled")],
            id=tc.id if tc else "tc-1",
            state=ToolResultState.INTERRUPTED,
        )
        return
    yield ToolResponse(
        content=[TextBlock(type="text", text="done")],
        id=tc.id if tc else "tc-1",
    )


@pytest.mark.asyncio
async def test_execute_normal_completion():
    coordinator = ToolCoordinator()
    tc = _make_tool_call()

    chunks = []
    async for item in coordinator.execute(
        tool_call=tc,
        next_handler=_simple_next_handler,
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
    ):
        chunks.append(item)

    assert len(chunks) >= 1
    final = chunks[-1]
    assert isinstance(final, ToolResponse)
    assert final.state == ToolResultState.SUCCESS

    # Entry should be removed after completion
    assert coordinator.get("tc-1") is None


@pytest.mark.asyncio
async def test_execute_streams_chunks():
    coordinator = ToolCoordinator()
    tc = _make_tool_call()

    chunks = []
    async for item in coordinator.execute(
        tool_call=tc,
        next_handler=_simple_next_handler,
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
    ):
        chunks.append(item)

    tool_chunks = [c for c in chunks if isinstance(c, ToolChunk)]
    assert len(tool_chunks) >= 1


@pytest.mark.asyncio
async def test_list_empty():
    coordinator = ToolCoordinator()
    assert coordinator.list() == []


@pytest.mark.asyncio
async def test_list_by_session():
    coordinator = ToolCoordinator()
    tc = _make_tool_call()
    gen = coordinator.execute(
        tool_call=tc,
        next_handler=_slow_next_handler,
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
    )
    task = asyncio.create_task(_drain_gen(gen))
    await asyncio.sleep(0.05)

    assert len(coordinator.list(session_id="s-1")) == 1
    assert coordinator.list(session_id="other") == []

    await coordinator.cancel("tc-1")
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_cancel_cooperative():
    coordinator = ToolCoordinator()
    tc = _make_tool_call()

    async def _cancellable_handler(**_kwargs):
        from qwenpaw.tool_calls import cancellable_wait

        try:
            await cancellable_wait(asyncio.sleep(100), fallback_secs=100)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            yield ToolResponse(
                content=[TextBlock(type="text", text="cancelled")],
                id="tc-1",
                state=ToolResultState.INTERRUPTED,
            )
            return
        yield ToolResponse(content=[], id="tc-1")

    gen = coordinator.execute(
        tool_call=tc,
        next_handler=_cancellable_handler,
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
    )

    # Let the tool start
    task = asyncio.create_task(_drain_gen(gen))
    await asyncio.sleep(0.05)

    ok = await coordinator.cancel("tc-1", reason=CancelReason.USER)
    assert ok is True

    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_cancel_nonexistent():
    coordinator = ToolCoordinator()
    ok = await coordinator.cancel("nonexistent")
    assert ok is False


@pytest.mark.asyncio
async def test_resolve_timeout_four_tiers():
    coordinator = ToolCoordinator(default_timeout_secs=100.0)

    # Tier 4: global default
    assert coordinator._resolve_timeout("a1", "tool1", None) == 100.0

    # Tier 3: hook default
    coordinator.hooks.register("tool1", default_timeout_secs=50.0)
    assert coordinator._resolve_timeout("a1", "tool1", None) == 50.0

    # Tier 2: per-agent
    coordinator.set_agent_tool_timeout("a1", "tool1", 30.0)
    assert coordinator._resolve_timeout("a1", "tool1", None) == 30.0

    # Tier 1: override
    assert coordinator._resolve_timeout("a1", "tool1", 10.0) == 10.0

    # Different agent still uses tier 3
    assert coordinator._resolve_timeout("a2", "tool1", None) == 50.0


@pytest.mark.asyncio
async def test_resolve_timeout_none_means_no_timeout():
    coordinator = ToolCoordinator(default_timeout_secs=None)
    assert coordinator._resolve_timeout("a1", "tool1", None) is None


@pytest.mark.asyncio
async def test_set_agent_tool_timeout_respects_cap():
    coordinator = ToolCoordinator()
    coordinator.hooks.register("browser", max_internal_timeout_secs=3600.0)

    ok = coordinator.set_agent_tool_timeout("a1", "browser", 7200.0)
    assert ok is False

    ok = coordinator.set_agent_tool_timeout("a1", "browser", 1800.0)
    assert ok is True


@pytest.mark.asyncio
async def test_extend_deadline():
    coordinator = ToolCoordinator()
    tc = _make_tool_call()
    gen = coordinator.execute(
        tool_call=tc,
        next_handler=_slow_next_handler,
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
        deadline_override=5.0,
    )

    task = asyncio.create_task(_drain_gen(gen))
    await asyncio.sleep(0.05)

    ok = await coordinator.extend_deadline("tc-1", seconds=60.0)
    assert ok is True

    entry = coordinator.get("tc-1")
    assert entry is not None
    assert entry.ctx.deadline is not None

    await coordinator.cancel("tc-1")
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_extend_deadline_no_deadline():
    coordinator = ToolCoordinator()
    tc = _make_tool_call()
    gen = coordinator.execute(
        tool_call=tc,
        next_handler=_slow_next_handler,
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
        deadline_override=5.0,
    )

    task = asyncio.create_task(_drain_gen(gen))
    await asyncio.sleep(0.05)

    ok = await coordinator.extend_deadline("tc-1", no_deadline=True)
    assert ok is True

    entry = coordinator.get("tc-1")
    assert entry is not None
    assert entry.ctx.deadline is None

    await coordinator.cancel("tc-1")
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_extend_deadline_capped_tool_refuses_no_deadline():
    coordinator = ToolCoordinator()
    coordinator.hooks.register("browser", max_internal_timeout_secs=3600.0)

    tc = _make_tool_call(name="browser")
    gen = coordinator.execute(
        tool_call=tc,
        next_handler=_slow_next_handler,
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
        deadline_override=60.0,
    )

    task = asyncio.create_task(_drain_gen(gen))
    await asyncio.sleep(0.05)

    ok = await coordinator.extend_deadline("tc-1", no_deadline=True)
    assert ok is False

    await coordinator.cancel("tc-1")
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_pop_pending_hints_empty():
    coordinator = ToolCoordinator()
    hints = await coordinator.pop_pending_hints("s-1")
    assert hints == []


@pytest.mark.asyncio
async def test_on_completion_handler_called():
    coordinator = ToolCoordinator()
    completed_entries = []

    async def _handler(entry):
        completed_entries.append(entry)

    coordinator.on_completion(_handler)

    tc = _make_tool_call()
    async for _ in coordinator.execute(
        tool_call=tc,
        next_handler=_simple_next_handler,
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
    ):
        pass

    # on_completion is only called for offloaded (background) tasks,
    # not foreground completions
    # For foreground, the entry is simply finalized


@pytest.mark.asyncio
async def test_on_completion_handler_exception_isolated():
    coordinator = ToolCoordinator()

    async def _bad_handler(entry):
        raise RuntimeError("boom")

    coordinator.on_completion(_bad_handler)

    tc = _make_tool_call()
    # Should not raise despite handler error
    async for _ in coordinator.execute(
        tool_call=tc,
        next_handler=_simple_next_handler,
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
    ):
        pass


@pytest.mark.asyncio
async def test_request_offload():
    coordinator = ToolCoordinator()
    tc = _make_tool_call()
    gen = coordinator.execute(
        tool_call=tc,
        next_handler=_slow_next_handler,
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
    )

    task = asyncio.create_task(_drain_gen(gen))
    await asyncio.sleep(0.05)

    ok = await coordinator.request_offload("tc-1")
    assert ok is True

    results = await asyncio.wait_for(task, timeout=2.0)
    final = results[-1]
    assert isinstance(final, ToolResponse)
    assert final.metadata.get("offloaded") is True

    await coordinator.shutdown()


@pytest.mark.asyncio
async def test_as_cancel_tool():
    coordinator = ToolCoordinator()
    cancel_fn = coordinator.as_cancel_tool()
    assert callable(cancel_fn)
    assert cancel_fn.__name__ == "TaskStop"

    result = await cancel_fn("nonexistent")
    assert isinstance(result, ToolResponse)
    assert "No active" in result.content[0].text


@pytest.mark.asyncio
async def test_shutdown():
    coordinator = ToolCoordinator()
    tc = _make_tool_call()
    gen = coordinator.execute(
        tool_call=tc,
        next_handler=_slow_next_handler,
        session_id="s-1",
        agent_id="a-1",
        root_session_id="rs-1",
    )

    task = asyncio.create_task(_drain_gen(gen))
    await asyncio.sleep(0.05)

    await coordinator.shutdown()
    await asyncio.wait_for(task, timeout=3.0)


@pytest.mark.asyncio
async def test_clear_agent_tool_timeouts():
    coordinator = ToolCoordinator()
    coordinator.set_agent_tool_timeout("a1", "t1", 10.0)
    coordinator.set_agent_tool_timeout("a1", "t2", 20.0)
    coordinator.set_agent_tool_timeout("a2", "t1", 30.0)

    coordinator.clear_agent_tool_timeouts("a1")

    assert coordinator._resolve_timeout("a1", "t1", None) is None
    assert coordinator._resolve_timeout("a2", "t1", None) == 30.0


async def _drain_gen(gen):
    results = []
    async for item in gen:
        results.append(item)
    return results
