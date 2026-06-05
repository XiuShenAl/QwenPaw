# -*- coding: utf-8 -*-
# pylint: disable=protected-access,unused-argument
"""Unit tests for ``qwenpaw.runtime.runtime.Runtime``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qwenpaw.runtime.hooks import (
    HookAction,
    HookBase,
    HookRegistry,
    HookResult,
)
from qwenpaw.runtime.phases import Phase
from qwenpaw.runtime.runtime import Runtime


def _make_kernel(hook_registry=None, slash_registry=None, tool_registry=None):
    """Build a minimal Kernel-like object for tests."""
    from qwenpaw.runtime.slash_command_registry import SlashCommandRegistry
    from qwenpaw.runtime.tool_registry import ToolRegistry

    plugins = SimpleNamespace(
        hook_registry=hook_registry or HookRegistry(),
        slash_command_registry=slash_registry or SlashCommandRegistry(),
        tool_registry=tool_registry or ToolRegistry(),
    )
    return SimpleNamespace(
        plugins=plugins,
        workspace_dir=None,
        agent_id="test",
    )


def _make_request(session_id="s1"):
    from qwenpaw.schemas import AgentRequest

    return AgentRequest(
        input=[],
        session_id=session_id,
    )


# ------------------------------------------------------------------ tests


@pytest.mark.asyncio
async def test_runtime_normalize_assigns_session_id():
    """_normalize fills in session_id when missing."""
    r = Runtime._normalize({"input": []})
    assert r.session_id
    assert r.user_id == r.session_id


@pytest.mark.asyncio
async def test_runtime_runs_pre_dispatch_and_finally():
    """PRE_DISPATCH and FINALLY hooks fire on a minimal run."""
    log = []

    class LogHook(HookBase):
        def __init__(self, phase, name, prio=100, action=HookAction.CONTINUE):
            self.phase = phase
            self.name = name
            self.priority = prio
            self._action = action

        async def run(self, ctx):
            log.append(self.name)
            return HookResult(action=self._action)

    reg = HookRegistry()
    reg.register(
        LogHook(Phase.PRE_DISPATCH, "pre", action=HookAction.SKIP_AGENT),
    )
    reg.register(LogHook(Phase.POST_RESPONSE, "post"))
    reg.register(LogHook(Phase.FINALLY, "fin"))

    kernel = _make_kernel(hook_registry=reg)
    rt = Runtime(kernel=kernel, app_services=None)

    items = []
    async for item in rt.run(_make_request()):
        items.append(item)

    assert "pre" in log
    assert "post" in log
    assert "fin" in log
    assert log.index("pre") < log.index("post") < log.index("fin")


@pytest.mark.asyncio
async def test_runtime_short_circuit_skips_agent():
    """SHORT_CIRCUIT yields payload, skips build/execute."""
    from agentscope.message import Msg
    from agentscope.message._block import TextBlock

    payload = Msg(
        name="sys",
        role="assistant",
        content=[TextBlock(text="short-circuited")],
    )

    class ShortCircuit(HookBase):
        phase = Phase.PRE_DISPATCH
        name = "sc"
        priority = 10

        async def run(self, ctx):
            return HookResult(
                action=HookAction.SHORT_CIRCUIT,
                payload=payload,
            )

    reg = HookRegistry()
    reg.register(ShortCircuit())

    kernel = _make_kernel(hook_registry=reg)
    rt = Runtime(kernel=kernel, app_services=None)

    items = []
    async for item in rt.run(_make_request()):
        items.append(item)

    assert len(items) > 0


@pytest.mark.asyncio
async def test_runtime_skip_agent_still_runs_post_response():
    """SKIP_AGENT skips build+execute but POST_RESPONSE still fires."""
    log = []

    class SkipHook(HookBase):
        phase = Phase.PRE_DISPATCH
        name = "skip"
        priority = 10

        async def run(self, ctx):
            log.append("skip")
            return HookResult(action=HookAction.SKIP_AGENT)

    class PostResponse(HookBase):
        phase = Phase.POST_RESPONSE
        name = "post"
        priority = 50

        async def run(self, ctx):
            log.append("post")
            return HookResult()

    class Finally(HookBase):
        phase = Phase.FINALLY
        name = "fin"
        priority = 50

        async def run(self, ctx):
            log.append("fin")
            return HookResult()

    reg = HookRegistry()
    reg.register(SkipHook())
    reg.register(PostResponse())
    reg.register(Finally())

    kernel = _make_kernel(hook_registry=reg)
    rt = Runtime(kernel=kernel, app_services=None)

    async for _ in rt.run(_make_request()):
        pass

    assert "skip" in log
    assert "post" in log
    assert "fin" in log


@pytest.mark.asyncio
async def test_runtime_on_error_fires_on_exception():
    """ON_ERROR and FINALLY fire when build raises."""
    log = []

    class ErrorLogger(HookBase):
        phase = Phase.ON_ERROR
        name = "err"
        priority = 10

        async def run(self, ctx):
            log.append(f"err:{type(ctx.error).__name__}")
            return HookResult()

    class FinallyLogger(HookBase):
        phase = Phase.FINALLY
        name = "fin"
        priority = 10

        async def run(self, ctx):
            log.append("fin")
            return HookResult()

    class BuildBreaker(HookBase):
        phase = Phase.PRE_AGENT_BUILD
        name = "break"
        priority = 10

        async def run(self, ctx):
            raise ValueError("boom")

    reg = HookRegistry()
    reg.register(BuildBreaker())
    reg.register(ErrorLogger())
    reg.register(FinallyLogger())

    kernel = _make_kernel(hook_registry=reg)
    rt = Runtime(kernel=kernel, app_services=None)

    items = []
    with pytest.raises(ValueError, match="boom"):
        async for item in rt.run(_make_request()):
            items.append(item)

    assert "err:ValueError" in log
    assert "fin" in log
