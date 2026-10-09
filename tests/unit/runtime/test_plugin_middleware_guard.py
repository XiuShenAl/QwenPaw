# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
# pylint: disable=unused-argument,unreachable
"""Protect actual AgentScope middleware hooks without replaying downstream."""

import asyncio
import weakref
from unittest.mock import AsyncMock, Mock

import pytest
from agentscope.middleware import MiddlewareBase
from agentscope.event import ReplyEndEvent

from qwenpaw.runtime.builder import _wrap_plugin_middleware
from qwenpaw.runtime.plugin_middleware import _HookCall

STREAM_HOOKS = ("on_reply", "on_reasoning", "on_acting")
AWAIT_HOOKS = ("on_model_call", "on_check_permission", "on_compress_context")


@pytest.fixture
def diagnostic(monkeypatch):
    note = Mock()
    monkeypatch.setattr(
        "qwenpaw.plugins.lifecycle.note_plugin_diagnostic",
        note,
    )
    return note


def middleware(hook, method):
    return type("PluginMiddleware", (MiddlewareBase,), {hook: method})()


@pytest.mark.asyncio
@pytest.mark.parametrize("hook", STREAM_HOOKS)
@pytest.mark.parametrize("when", ["before", "during", "after"])
async def test_stream_fault_uses_downstream_once(hook, when, diagnostic):
    first, last = object(), object()
    calls = []

    async def downstream(**_):
        calls.append(True)
        yield first
        yield last

    async def broken(self, agent, input_kwargs, next_handler):
        if when == "before":
            raise RuntimeError("plugin broke")
        async for item in next_handler():
            if when == "during":
                raise RuntimeError("plugin broke before yielding")
            yield item
        raise RuntimeError("plugin broke after execution")

    guarded = _wrap_plugin_middleware(middleware(hook, broken), "broken")
    result = [
        item async for item in getattr(guarded, hook)(None, {}, downstream)
    ]
    assert result == ([last] if when == "during" else [first, last])
    assert len(calls) == 1
    diagnostic.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("hook", AWAIT_HOOKS)
@pytest.mark.parametrize("after", [False, True])
async def test_await_fault_does_not_repeat_model_or_permission(
    hook,
    after,
    diagnostic,
):
    result = None if hook == "on_compress_context" else object()
    calls = []

    async def downstream(**_):
        calls.append(True)
        return result

    async def broken(self, agent, input_kwargs, next_handler):
        if after:
            await next_handler()
        raise RuntimeError("plugin broke")

    guarded = _wrap_plugin_middleware(middleware(hook, broken), "broken")
    assert await getattr(guarded, hook)(None, {}, downstream) is result
    assert len(calls) == 1
    diagnostic.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_downstream_error_propagates(stream, diagnostic):
    error = RuntimeError("model or tool failed")

    async def downstream_stream(**_):
        raise error
        yield

    async def downstream_await(**_):
        raise error

    async def forward_stream(self, agent, input_kwargs, next_handler):
        async for item in next_handler():
            yield item

    async def forward_await(self, agent, input_kwargs, next_handler):
        return await next_handler()

    hook = "on_reply" if stream else "on_model_call"
    guarded = _wrap_plugin_middleware(
        middleware(hook, forward_stream if stream else forward_await),
        "broken",
    )
    with pytest.raises(RuntimeError) as caught:
        if stream:
            async for _ in guarded.on_reply(None, {}, downstream_stream):
                pass
        else:
            await guarded.on_model_call(None, {}, downstream_await)
    assert caught.value is error
    diagnostic.assert_not_called()


@pytest.mark.asyncio
async def test_prompt_failure_preserves_input_and_hook_detection(diagnostic):
    async def broken(self, agent, current_prompt):
        raise RuntimeError("prompt failed")

    original = middleware("on_system_prompt", broken)
    guarded = _wrap_plugin_middleware(original, "broken")
    assert isinstance(guarded, MiddlewareBase)
    assert guarded.is_implemented("on_system_prompt")
    assert not guarded.is_implemented("on_reply")
    assert (
        await guarded.get_middleware_key()
        == await original.get_middleware_key()
    )
    assert await guarded.on_system_prompt(None, "original") == "original"
    diagnostic.assert_called_once()


@pytest.mark.asyncio
async def test_model_stream_failure_resumes_existing_stream(diagnostic):
    first, last = object(), object()
    calls = []

    async def chunks():
        yield first
        yield last

    async def downstream(**_):
        calls.append(True)
        return chunks()

    async def broken(self, agent, input_kwargs, next_handler):
        stream = await next_handler()

        async def transform():
            async for item in stream:
                yield item
                raise RuntimeError("plugin streaming failure")

        return transform()

    guarded = _wrap_plugin_middleware(
        middleware("on_model_call", broken),
        "broken",
    )
    stream = await guarded.on_model_call(None, {}, downstream)
    assert [item async for item in stream] == [first, last]
    assert len(calls) == 1
    diagnostic.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("hook", (*STREAM_HOOKS, "on_model_call"))
@pytest.mark.parametrize(
    "operation,expected",
    [
        ("transform_first", ["FIRST", "last"]),
        ("transform_all", ["FIRST", "LAST"]),
        ("filter", ["last"]),
        ("combine", ["first:last"]),
        ("consume_then_fail", ["last"]),
    ],
)
async def test_stream_recovery_does_not_replay_consumed_items(
    hook,
    operation,
    expected,
    diagnostic,
):
    calls = []

    async def chunks():
        yield "first"
        yield "last"

    def downstream_stream(**_):
        calls.append(True)
        return chunks()

    async def downstream_model(**_):
        return downstream_stream()

    async def transform(stream):
        if operation == "combine":
            yield ":".join([item async for item in stream])
        else:
            async for item in stream:
                if operation == "filter":
                    if item == "first":
                        continue
                    yield item
                    continue
                if operation.startswith("transform"):
                    yield item.upper()
                if operation != "transform_all":
                    break
        raise RuntimeError("plugin failed after consuming content")

    async def streaming_hook(self, agent, input_kwargs, next_handler):
        async for item in transform(next_handler()):
            yield item

    async def model_hook(self, agent, input_kwargs, next_handler):
        return transform(await next_handler())

    is_model = hook == "on_model_call"
    guarded = _wrap_plugin_middleware(
        middleware(hook, model_hook if is_model else streaming_hook),
        "broken",
    )
    if is_model:
        stream = await guarded.on_model_call(None, {}, downstream_model)
    else:
        stream = getattr(guarded, hook)(None, {}, downstream_stream)
    assert [item async for item in stream] == expected
    assert calls == [True]
    diagnostic.assert_called_once()


@pytest.mark.asyncio
async def test_consumed_stream_items_are_not_retained():
    references = []

    class Chunk:
        pass

    async def chunks(**_):
        for _ in range(100):
            item = Chunk()
            references.append(weakref.ref(item))
            yield item

    call = _HookCall(chunks)

    async def consume():
        async for _ in call.stream_next():
            pass

    await consume()
    # Keep the tracking handles alive, as during an active hook invocation.
    assert call.streams
    assert all(reference() is None for reference in references)
    assert [item async for item in call.recover_stream({})] == []


@pytest.mark.asyncio
async def test_request_cancellation_propagates(diagnostic):
    started = asyncio.Event()

    async def waiting(self, agent, input_kwargs, next_handler):
        started.set()
        await asyncio.Event().wait()

    guarded = _wrap_plugin_middleware(
        middleware("on_model_call", waiting),
        "broken",
    )
    request = asyncio.create_task(guarded.on_model_call(None, {}, None))
    await started.wait()
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    diagnostic.assert_not_called()


@pytest.mark.asyncio
async def test_agent_scope_reply_chain_survives_plugin_hook_fault(diagnostic):
    from agentscope.agent import Agent
    from agentscope.message import Msg

    reply = Msg(
        name="agent",
        role="assistant",
        content=[{"type": "text", "text": "normal reply"}],
    )
    calls = []

    class LocalAgent(Agent):
        async def _reply_impl(self, inputs=None, structured_schema=None):
            calls.append(True)
            yield reply

    async def broken(self, agent, input_kwargs, next_handler):
        raise RuntimeError("plugin failed before reply")
        yield

    guarded = _wrap_plugin_middleware(middleware("on_reply", broken), "broken")
    agent = LocalAgent(
        name="agent",
        system_prompt="",
        model=Mock(),
        middlewares=[guarded],
    )
    assert [item async for item in agent._reply()] == [reply]
    assert calls == [True]
    diagnostic.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["before", "after", "copy"])
async def test_reply_end_fault_does_not_trigger_another_reasoning_round(
    delivery,
    diagnostic,
):
    from agentscope.agent import Agent
    from agentscope.message import Msg, TextBlock
    from agentscope.model import ChatResponse

    model = AsyncMock()
    model.model = "local-test-model"
    model.context_size = 100000
    model.count_tokens.return_value = 0
    model.return_value = ChatResponse(
        content=[TextBlock(text="first answer")],
        is_last=True,
    )

    async def broken(self, agent, input_kwargs, next_handler):
        async for item in next_handler():
            if isinstance(item, ReplyEndEvent):
                if delivery == "after":
                    yield item
                elif delivery == "copy":
                    yield item.model_copy()
                raise RuntimeError("plugin failed at reply end")
            yield item

    agent = Agent(
        name="agent",
        system_prompt="",
        model=model,
        middlewares=[
            _wrap_plugin_middleware(
                middleware("on_reply", broken),
                "broken",
            ),
        ],
    )
    output = [
        item
        async for item in agent._reply(
            inputs=Msg(
                name="user",
                role="user",
                content=[TextBlock(text="hello")],
            ),
        )
    ]
    assert model.await_count == 1
    assert agent.state.cur_iter == 1
    assert sum(isinstance(item, ReplyEndEvent) for item in output) == 1
    assert isinstance(output[-1], Msg)
    assert output[-1].get_text_content() == "first answer"
    diagnostic.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hook,factory_fault",
    [
        *((hook, False) for hook in STREAM_HOOKS),
        ("on_model_call", False),
        ("on_model_call", True),
    ],
)
async def test_unemitted_reply_end_is_recovered_before_downstream_resumes(
    hook,
    factory_fault,
    diagnostic,
):
    end = ReplyEndEvent(session_id="session", reply_id="reply")
    resumed = []

    async def chunks():
        yield end
        resumed.append(True)
        yield "tail"

    def downstream_stream(**_):
        return chunks()

    async def downstream_model(**_):
        return chunks()

    async def broken_stream(stream):
        async for _ in stream:
            raise RuntimeError("plugin failed before delivering end")
            yield

    async def stream_hook(self, agent, input_kwargs, next_handler):
        async for item in broken_stream(next_handler()):
            yield item

    async def model_hook(self, agent, input_kwargs, next_handler):
        result = broken_stream(await next_handler())
        if factory_fault:
            await anext(result)
        return result

    is_model = hook == "on_model_call"
    guarded = _wrap_plugin_middleware(
        middleware(hook, model_hook if is_model else stream_hook),
        "broken",
    )
    if is_model:
        stream = await guarded.on_model_call(None, {}, downstream_model)
    else:
        stream = getattr(guarded, hook)(None, {}, downstream_stream)
    assert await anext(stream) is end
    assert not resumed
    assert [item async for item in stream] == ["tail"]
    assert resumed == [True]
    diagnostic.assert_called_once()


@pytest.mark.asyncio
async def test_downstream_model_stream_error_is_not_plugin_fault(diagnostic):
    error = RuntimeError("model stream failed")

    async def chunks():
        yield "first"
        raise error

    async def downstream(**_):
        return chunks()

    async def forward(self, agent, input_kwargs, next_handler):
        return await next_handler()

    guarded = _wrap_plugin_middleware(
        middleware("on_model_call", forward),
        "broken",
    )
    stream = await guarded.on_model_call(None, {}, downstream)
    assert await anext(stream) == "first"
    with pytest.raises(RuntimeError) as caught:
        await anext(stream)
    assert caught.value is error
    diagnostic.assert_not_called()


@pytest.mark.asyncio
async def test_failed_hook_uses_original_arguments(diagnostic):
    received = []

    async def downstream(**kwargs):
        received.append(kwargs)
        return "safe result"

    async def broken(self, agent, input_kwargs, next_handler):
        input_kwargs["messages"] = "plugin modified"
        raise RuntimeError("plugin failed")

    guarded = _wrap_plugin_middleware(
        middleware("on_model_call", broken),
        "broken",
    )
    assert (
        await guarded.on_model_call(None, {"messages": "original"}, downstream)
        == "safe result"
    )
    assert received == [{"messages": "original"}]


@pytest.mark.asyncio
async def test_successful_hook_keeps_transform_and_metadata(diagnostic):
    class Healthy(MiddlewareBase):
        async def on_reply(self, agent, input_kwargs, next_handler):
            async for item in next_handler():
                yield item.upper()

        async def list_tools(self):
            return ["plugin tool"]

        async def get_middleware_key(self):
            return "stable plugin key"

    async def downstream(**_):
        yield "reply"

    guarded = _wrap_plugin_middleware(Healthy(), "healthy")
    assert [item async for item in guarded.on_reply(None, {}, downstream)] == [
        "REPLY",
    ]
    assert await guarded.list_tools() == ["plugin tool"]
    assert await guarded.get_middleware_key() == "stable plugin key"
    diagnostic.assert_not_called()
